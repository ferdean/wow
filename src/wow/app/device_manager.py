"""Own the trainer and strap connections.

Owns the trainer and strap connections (3A, app/device_manager).

Connect both when the Pre-ride screen opens, one at a time, and keep
trying while a device isn't found; after a loss, reconnect for as long
as the app runs (APP-318, APP-319, APP-805, APP-806); show a dropout
after 3 s without data and close a trainer link silent for 10 s (ICD
4.1.6); drop loss reports of older connections (F-32); release the
trainer in an orderly way (APP-320). The idle release and the device
scan follow in SL-10.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Final, Protocol

from wow.core.devices import DeviceKind, LinkState
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

    def open_pre_ride(self) -> None:
        """Start connecting both devices."""
        for slot in (self._trainer, self._hrm):
            busy = slot.task is not None and not slot.task.done()
            if slot.address is not None and slot.client is None and not busy:
                slot.device.set_link(LinkState.SEARCHING)
                slot.task = asyncio.get_running_loop().create_task(
                    self._connect(slot, slot.address))

    async def close(self) -> None:
        """Stop connecting and release the devices."""
        self._closing = True
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

    async def _connect(self, slot: _Slot, address: str,
                       again: bool = False) -> None:
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
