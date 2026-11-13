"""Own the trainer and strap connections.

Owns the trainer and strap connections (3A, app/device_manager).

Slice SL-01: connect both when the Pre-ride screen opens, keep trying
while a device isn't found, drop loss reports of older connections
(F-32), release the trainer in an orderly way (APP-320). Reconnecting
during a ride, the idle release and the device scan follow in SL-06
and SL-10.
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


class _Slot:
    def __init__(self, name: str, address: str | None, device: _Device):
        self.name = name
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
        self._trainer = _Slot(DeviceKind.TRAINER, choice.trainer, trainer)
        self._hrm = _Slot(DeviceKind.HRM, choice.hrm, hrm)
        self._one_at_a_time = asyncio.Lock()

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
        for slot in (self._trainer, self._hrm):
            if slot.task is not None:
                slot.task.cancel()
                await asyncio.gather(slot.task, return_exceptions=True)
        if self._trainer.client is not None:
            await self.trainer.release()
            self._trainer.client = None
        if self._hrm.client is not None:
            await self.hrm.close()
            self._hrm.client = None
        await self.trainer.stop()

    async def _connect(self, slot: _Slot, address: str) -> None:
        slot.device.set_link(LinkState.SEARCHING)
        while True:
            client = await self._attempt(slot, address)
            if client is not None:
                slot.client = client
                slot.device.set_link(LinkState.CONNECTED)
                logger.info("%s connected (generation %d)", slot.name,
                            client.generation)
                return
            slot.device.set_link(LinkState.NOT_FOUND)
            await self._clock.sleep_until(
                self._clock.monotonic() + RETRY_PAUSE)

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
        slot.client = None
        slot.device.detach()
        slot.device.set_link(LinkState.DROPOUT)
        logger.warning("%s link lost (generation %d)", slot.name, generation)


async def _close_quietly(client: GattClient) -> None:
    try:
        await client.close()
    except GattError as error:
        logger.info("closing after a failed set-up: %r", error)
