"""Own the trainer and strap connections.

Owns the trainer and strap connections (3A, app/device_manager).

Connect both when the Pre-ride screen opens, one at a time, and keep
trying while a device isn't found; after a loss, reconnect for as long
as the app runs (APP-318, APP-319, APP-805, APP-806); show a dropout
after 3 s without data and close a trainer link silent for 10 s (ICD
4.1.6); drop loss reports of older connections (F-32); release the
trainer in an orderly way (APP-320), also after 10 minutes with no ride,
calibration or Pre-ride open (APP-110); scan for the fitness devices
nearby and switch to the one the rider chooses (APP-114).
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Final, Protocol

from wow.core import uuids
from wow.core.devices import (
    DeviceKind, FoundDevice, LinkState, device_kind,
)
from wow.app.ftms_trainer import FtmsTrainer
from wow.app.hrm_link import HrmLink
from wow.ports.clock import Clock
from wow.ports.gatt import GattClient, GattConnector, GattError

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT: Final[float] = 10.0
RETRY_PAUSE: Final[float] = 2.0
EPSILON: Final[float] = 1e-6
DATA_DROPOUT: Final[float] = 3.0
SILENT_LINK_RESET: Final[float] = 10.0
IDLE_RELEASE: Final[float] = 600.0
SCAN_DURATION: Final[float] = 5.0
SCAN_SERVICES: Final[tuple[str, ...]] = (
    uuids.FITNESS_MACHINE_SERVICE, uuids.HEART_RATE_SERVICE,
    uuids.CYCLING_SPEED_AND_CADENCE_SERVICE)
SCAN_ORDER: Final[tuple[DeviceKind, ...]] = (
    DeviceKind.TRAINER, DeviceKind.HRM, DeviceKind.CADENCE)


@dataclass(frozen=True)
class DeviceChoice:
    """The addresses of the devices to use."""

    trainer: str | None
    hrm: str | None


class _Device(Protocol):
    def link(self) -> LinkState: ...

    def set_link(self, state: LinkState) -> None: ...

    async def attach(self, client: GattClient) -> None: ...

    def detach(self) -> None: ...

    def last_data(self) -> float: ...

    def mark_silent(self) -> None: ...


class _Slot:
    def __init__(self, name: str, address: str | None, device: _Device,
                 resets: bool):
        self.name = name
        self.resets = resets
        self.watch: asyncio.Task[None] | None = None
        self.address = address
        self.device = device
        self.client: GattClient | None = None
        self.task: asyncio.Task[None] | None = None
        device.set_link(LinkState.NOT_CONFIGURED if address is None
                        else LinkState.NOT_FOUND)


class DeviceManager:
    """Connects the trainer and the strap and keeps them connected."""

    def __init__(
        self,
        connector: GattConnector,
        clock: Clock,
        trainer: FtmsTrainer,
        hrm: HrmLink,
        choice: DeviceChoice,
    ) -> None:
        self._connector = connector
        self._clock = clock
        self.trainer = trainer
        self.hrm = hrm
        self._trainer = _Slot(DeviceKind.TRAINER, choice.trainer, trainer,
                              True)
        self._hrm = _Slot(DeviceKind.HRM, choice.hrm, hrm, False)
        self._one_at_a_time = asyncio.Lock()
        self._closing = False
        self._in_use = False
        self._idle: asyncio.Task[None] | None = None
        self._releasing: asyncio.Task[None] | None = None

    def open_pre_ride(self) -> None:
        """Start connecting both devices, and keep them (APP-102)."""
        self.hold(True)
        for slot in (self._trainer, self._hrm):
            self._start(slot)

    def hold(self, in_use: bool) -> None:
        """Say whether a ride, calibration or Pre-ride is open.

        Ten minutes after the last one closes, both devices are released,
        the trainer at its lowest level first (APP-110, APP-320).
        """
        if in_use:
            self._in_use = True
            if self._idle is not None and self._releasing is None:
                self._idle.cancel()
                self._idle = None
            return
        if self._in_use:
            self._in_use = False
            self._idle = asyncio.get_running_loop().create_task(
                self._release_when_idle(
                    self._clock.monotonic() + IDLE_RELEASE))

    def role_of(self, address: str) -> str:
        """Return the role of an address, for the Bluetooth log."""
        for slot in (self._trainer, self._hrm):
            if slot.address is not None and (
                    slot.address.upper() == address.upper()):
                return slot.name
        return DeviceKind.OTHER

    def address(self, kind: DeviceKind) -> str | None:
        """Return the address in use for a role."""
        return self._slot(kind).address

    async def scan(self, duration: float = SCAN_DURATION) -> list[FoundDevice]:
        """Return the fitness devices advertising nearby (APP-114)."""
        try:
            async with self._one_at_a_time:
                seen = await self._connector.scan(SCAN_SERVICES, duration)
        except GattError as error:
            logger.warning("scan failed: %r", error)
            return []
        found: dict[str, FoundDevice] = {}
        for advertisement in seen:
            kind = device_kind(advertisement.service_uuids)
            address = advertisement.address.upper()
            known = found.get(address)
            if kind == DeviceKind.OTHER or (
                    known is not None
                    and known.rssi_dbm >= advertisement.rssi_dbm):
                continue
            found[address] = FoundDevice(address, advertisement.name,
                                         advertisement.rssi_dbm, kind)
        return sorted(found.values(), key=lambda f: (
            SCAN_ORDER.index(f.kind), -f.rssi_dbm))

    async def choose(self, kind: DeviceKind, address: str | None) -> None:
        """Use another device for a role from now on (APP-114)."""
        slot = self._slot(kind)
        if slot.address == address:
            return
        await self._let_go(slot)
        slot.address = address
        slot.device.set_link(LinkState.NOT_CONFIGURED if address is None
                             else LinkState.NOT_FOUND)
        logger.info("%s is now %s", slot.name, address)
        if self._in_use:
            self._start(slot)

    async def close(self) -> None:
        """Stop connecting and release the devices."""
        self._closing = True
        for task in (self._idle, self._releasing):
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        for slot in (self._trainer, self._hrm):
            for task in (slot.task, slot.watch):
                if task is not None:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        if self._trainer.client is not None:
            await self.trainer.release()
            self._trainer.client = None
        if self._hrm.client is not None:
            await self.hrm.close()
            self._hrm.client = None
        await self.trainer.stop()

    def _slot(self, kind: DeviceKind) -> _Slot:
        return self._trainer if kind == DeviceKind.TRAINER else self._hrm

    def _start(self, slot: _Slot) -> None:
        busy = slot.task is not None and not slot.task.done()
        if slot.address is None or slot.client is not None or busy:
            return
        slot.device.set_link(LinkState.SEARCHING)
        slot.task = asyncio.get_running_loop().create_task(
            self._connect(slot, slot.address, after=self._releasing))

    async def _release_when_idle(self, due: float) -> None:
        await self._clock.sleep_until(due)
        if self._in_use:
            return
        logger.info("no ride, calibration or Pre-ride for %.0f s: "
                    "releasing the devices", IDLE_RELEASE)
        self._releasing = asyncio.current_task()
        try:
            for slot in (self._trainer, self._hrm):
                await self._let_go(slot)
        finally:
            self._releasing = None
            self._idle = None
        if self._in_use:
            for slot in (self._trainer, self._hrm):
                self._start(slot)

    async def _let_go(self, slot: _Slot) -> None:
        for task in (slot.task, slot.watch):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        slot.task = slot.watch = None
        client, slot.client = slot.client, None
        if client is not None and slot.resets:
            await self.trainer.release()
        elif client is not None:
            await self.hrm.close()
        if slot.address is not None:
            slot.device.set_link(LinkState.NOT_FOUND)

    async def _connect(self, slot: _Slot, address: str,
                       again: bool = False,
                       after: asyncio.Task[None] | None = None) -> None:
        if after is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(after)
        if not again:
            slot.device.set_link(LinkState.SEARCHING)
        while True:
            client = await self._attempt(slot, address)
            if client is not None:
                slot.client = client
                slot.device.set_link(LinkState.CONNECTED)
                logger.info("%s connected (generation %d)", slot.name,
                            client.generation)
                slot.watch = asyncio.get_running_loop().create_task(
                    self._watch(slot, client))
                return
            if not again:
                slot.device.set_link(LinkState.NOT_FOUND)
            await self._clock.sleep_until(
                self._clock.monotonic() + RETRY_PAUSE)

    async def _watch(self, slot: _Slot, client: GattClient) -> None:
        device = slot.device
        while slot.client is client:
            now = self._clock.monotonic()
            quiet = now - device.last_data()
            if slot.resets and quiet >= SILENT_LINK_RESET - EPSILON:
                logger.warning("%s silent for %.0f s: closing the link",
                               slot.name, quiet)
                self._forget(slot)
                await _close_quietly(client)
                self._reconnect(slot)
                return
            if quiet >= DATA_DROPOUT - EPSILON:
                device.mark_silent()
                due = (device.last_data() + SILENT_LINK_RESET if slot.resets
                       else now + DATA_DROPOUT)
            else:
                due = device.last_data() + DATA_DROPOUT
            await self._clock.sleep_until(due)

    def _forget(self, slot: _Slot) -> None:
        slot.client = None
        slot.device.detach()
        slot.device.set_link(LinkState.DROPOUT)

    def _reconnect(self, slot: _Slot) -> None:
        busy = slot.task is not None and not slot.task.done()
        if self._closing or slot.address is None or busy:
            return
        slot.task = asyncio.get_running_loop().create_task(
            self._connect(slot, slot.address, again=True))

    async def _attempt(self, slot: _Slot, address: str) -> GattClient | None:
        try:
            async with self._one_at_a_time:
                client = await self._connector.connect(
                    address, CONNECT_TIMEOUT,
                    lambda generation: self._lost(slot, generation))
        except GattError as error:
            logger.info("%s not found: %r", slot.name, error)
            return None
        try:
            await slot.device.attach(client)
        except GattError as error:
            logger.warning("%s set-up failed: %r", slot.name, error)
            await _close_quietly(client)
            return None
        except asyncio.CancelledError:
            await _close_quietly(client)
            raise
        return client

    def _lost(self, slot: _Slot, generation: int) -> None:
        client = slot.client
        if client is None or client.generation != generation:
            logger.info("%s: ignored loss report of generation %d",
                        slot.name, generation)
            return
        self._forget(slot)
        logger.warning("%s link lost (generation %d)", slot.name, generation)
        self._reconnect(slot)


async def _close_quietly(client: GattClient) -> None:
    try:
        await client.close()
    except GattError as error:
        logger.info("closing after a failed set-up: %r", error)
