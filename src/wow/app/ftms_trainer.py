"""Run the FTMS session over a GATT client.

Runs the FTMS session over a GattClient: reads and subscribes on
connect, carries out the session's writes and feeds it indications,
statuses and timer expiries (3A, app/ftms_trainer; ICD S-1, S-6).
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from wow.core import ftms_codec as codec
from wow.core import uuids
from wow.core.devices import (
    LinkState, TrainerCapabilities, TrainerCommand, TrainerSample,
)
from wow.core.ftms_codec import Dropped
from wow.core.ftms_session import (
    CloseLink, FtmsSession, Indication, LinkDown, LinkUp, Logged,
    ModeUnavailable, Phase, Release, SessionAction, SessionEvent, SetCommand,
    StatusForwarded, StatusNotification, Tick, WarningChanged, Write,
)
from wow.app.machine_driver import MachineDriver
from wow.ports.clock import Clock
from wow.ports.gatt import GattClient, GattError, LinkLost

logger = logging.getLogger(__name__)


class FtmsTrainer:
    """The trainer on its GATT client."""

    def __init__(
        self,
        clock: Clock,
        on_sample: Callable[[TrainerSample], None] | None = None,
        on_status: Callable[[bytes], None] | None = None,
    ) -> None:
        self._clock = clock
        self._session = FtmsSession()
        self._driver: MachineDriver[SessionEvent, SessionAction] = (
            MachineDriver(self._session, clock, self._perform, Tick()))
        self._client: GattClient | None = None
        self._link: LinkState = LinkState.NOT_CONFIGURED
        self._assembler = codec.BikeDataAssembler()
        self._resistance_width = 2
        self._warnings: set[str] = set()
        self._closed = asyncio.Event()
        self._closing = False
        self._tasks: set[asyncio.Task[None]] = set()
        self.on_sample = on_sample or (lambda _sample: None)
        self.on_link: Callable[[LinkState], None] = lambda _state: None
        self.on_status = on_status or (lambda _data: None)

    def capabilities(self) -> TrainerCapabilities | None:
        """Return the capabilities, if known."""
        if self._client is None:
            return None
        return self._session.capabilities()

    def link(self) -> LinkState:
        """Return the link state."""
        return self._link

    def set_link(self, state: LinkState) -> None:
        """Set the link state and tell on_link."""
        self._link = state
        self.on_link(state)

    def set_command(self, command: TrainerCommand) -> None:
        """Set the command the trainer should hold."""
        self._driver.post(SetCommand(command))

    def responding(self) -> bool:
        """Return whether the trainer answers in time."""
        return self._session.responding()

    def in_control(self) -> bool:
        """Return whether the app holds control."""
        return self._session.in_control()

    def warnings(self) -> frozenset[str]:
        """Return the active warnings."""
        return frozenset(self._warnings)

    async def attach(self, client: GattClient) -> None:
        """Take over a connected client and start the session."""
        features = codec.decode_features(
            await client.read(uuids.FITNESS_MACHINE_FEATURE))
        if isinstance(features, Dropped):
            raise GattError(f"unreadable features {features.data.hex()}")
        power = await _optional(client, uuids.SUPPORTED_POWER_RANGE,
                                codec.decode_power_range)
        resistance = await _optional(
            client, uuids.SUPPORTED_RESISTANCE_LEVEL_RANGE,
            codec.decode_resistance_range)
        await _optional(client, uuids.SUPPORTED_INCLINATION_RANGE,
                        codec.decode_inclination_range)
        self._resistance_width = (
            2 if resistance is None else resistance.data_width)
        capabilities = codec.trainer_capabilities(
            features, power, None if resistance is None else resistance.range)
        self._assembler = codec.BikeDataAssembler()
        await client.subscribe(uuids.INDOOR_BIKE_DATA, self._on_bike_data)
        await client.subscribe(
            uuids.FITNESS_MACHINE_STATUS,
            lambda data: self._driver.post(StatusNotification(data)))
        await client.subscribe(
            uuids.FITNESS_MACHINE_CONTROL_POINT,
            lambda data: self._driver.post(Indication(data)))
        self._client = client
        self._closed.clear()
        self._closing = False
        self._driver.post(LinkUp(capabilities))

    def detach(self) -> None:
        """Forget the client after the link was lost."""
        self._client = None
        self._driver.post(LinkDown())
        self._closed.set()

    async def release(self) -> None:
        """Release control and drop to the lowest level."""
        if self._client is None:
            return
        self._driver.post(Release())
        if not self._closing and self._session.phase == Phase.DISCONNECTED:
            self._begin_close()
        await self._closed.wait()

    async def stop(self) -> None:
        """Stop the session and its timers."""
        self._driver.close()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _on_bike_data(self, data: bytes) -> None:
        record = codec.decode_indoor_bike_data(data, self._resistance_width)
        if isinstance(record, Dropped):
            logger.warning("indoor bike data dropped (%s): %s",
                           record.reason, record.data.hex())
            return
        joined = self._assembler.add(record)
        capabilities = self._session.capabilities()
        if joined is not None and capabilities is not None:
            self.on_sample(codec.trainer_sample(
                joined, capabilities, self._clock.monotonic()))

    def _perform(self, actions: list[SessionAction]) -> None:
        for action in actions:
            match action:
                case Write(data=data):
                    self._spawn(self._write(data))
                case CloseLink():
                    self._begin_close()
                case WarningChanged(kind=kind, active=active):
                    self._warning(kind, active)
                case StatusForwarded(data=data):
                    self.on_status(data)
                case ModeUnavailable(mode=mode):
                    logger.warning("trainer refused %s mode", mode)
                case Logged(event=event, data=data):
                    logger.warning("trainer %s: %s", event, data.hex())

    def _warning(self, kind: str, active: bool) -> None:
        if active:
            self._warnings.add(kind)
            logger.warning("trainer warning on: %s", kind)
        else:
            self._warnings.discard(kind)
            logger.info("trainer warning off: %s", kind)

    async def _write(self, data: bytes) -> None:
        client = self._client
        if client is None:
            return
        try:
            await client.write(uuids.FITNESS_MACHINE_CONTROL_POINT, data)
        except GattError as error:
            logger.warning("control point write %s failed: %r",
                           data.hex(), error)

    def _begin_close(self) -> None:
        self._closing = True
        self._spawn(self._close())

    async def _close(self) -> None:
        client, self._client = self._client, None
        try:
            if client is not None:
                await client.close()
        except GattError as error:
            logger.warning("closing the trainer link failed: %r", error)
        finally:
            self._closed.set()

    def _spawn(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


async def _optional[T](
    client: GattClient, char: str, decode: Callable[[bytes], T | Dropped]
) -> T | None:
    try:
        value = decode(await client.read(char))
    except LinkLost:
        raise
    except GattError as error:
        logger.info("trainer has no readable %s: %r", char, error)
        return None
    if isinstance(value, Dropped):
        logger.warning("%s not usable (%s): %s", char, value.reason,
                       value.data.hex())
        return None
    return value
