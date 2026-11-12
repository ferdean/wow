"""Log every Bluetooth operation.

Logs every Bluetooth operation of any GattConnector (ICD IF-11; APP-813).
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from wow.core import uuids
from wow.core.timefmt import utc_text
from wow.ports.clock import Clock
from wow.ports.gatt import (
    Advertisement, GattClient, GattConnector, GattError, Uuid,
)
from wow.core.devices import DeviceKind
from typing import Final

INDICATED: Final[frozenset[str]] = frozenset(
    {uuids.FITNESS_MACHINE_CONTROL_POINT})


@dataclass(frozen=True)
class BleLogRecord:
    """One Bluetooth log record."""

    utc: str
    mono_ms: float
    dev: str
    addr: str
    gen: int | None
    op: str
    uuid: str | None = None
    hex: str | None = None
    extra: Mapping[str, object] = field(default_factory=dict)


def record_line(record: BleLogRecord) -> str:
    """Return the JSON line of a record."""
    fields = {
        "utc": record.utc, "mono_ms": record.mono_ms, "dev": record.dev,
        "addr": record.addr, "gen": record.gen, "op": record.op,
        "uuid": record.uuid, "hex": record.hex,
    }
    return json.dumps({**fields, **record.extra}, separators=(", ", ": "))


def device_kind(advertisement: Advertisement) -> DeviceKind:
    """Return the role of an advertising device."""
    services = set(advertisement.service_uuids)
    if uuids.FITNESS_MACHINE_SERVICE in services:
        return DeviceKind.TRAINER
    if uuids.HEART_RATE_SERVICE in services:
        return DeviceKind.HRM
    return DeviceKind.OTHER


BleSink = Callable[[BleLogRecord], None]


class _Recorder:
    def __init__(self, clock: Clock, sink: BleSink) -> None:
        self._clock = clock
        self._sink = sink

    def __call__(
        self, dev: str, addr: str, gen: int | None, op: str,
        uuid: str | None = None, data: bytes | None = None,
        **extra: object,
    ) -> None:
        self._sink(BleLogRecord(
            utc=utc_text(self._clock.utc()),
            mono_ms=round(self._clock.monotonic() * 1000, 1),
            dev=dev, addr=addr, gen=gen, op=op, uuid=uuid,
            hex=None if data is None else data.hex(), extra=extra,
        ))


class LoggingConnector:
    """Connector that logs what the wrapped one does."""

    def __init__(
        self,
        inner: GattConnector,
        clock: Clock,
        sink: BleSink,
        role_of: Callable[[str], str],
    ) -> None:
        self._inner = inner
        self._record = _Recorder(clock, sink)
        self._role_of = role_of

    def stale_release(self, address: str, outcome: str) -> None:
        """Log the release of a stale link."""
        self._record(self._role_of(address), address, None, "released_stale",
                     outcome=outcome)

    async def scan(
        self, service_uuids: Sequence[Uuid], duration: float
    ) -> list[Advertisement]:
        """Scan and log the result."""
        found = await self._inner.scan(service_uuids, duration)
        for advertisement in found:
            self._record(
                device_kind(advertisement), advertisement.address, None,
                "scan_result", rssi_dbm=advertisement.rssi_dbm,
                service_data={key: value.hex() for key, value
                              in advertisement.service_data.items()})
        return found

    async def connect(
        self, address: str, timeout: float, on_lost: Callable[[int], None]
    ) -> GattClient:
        """Connect and log the connection."""
        dev = self._role_of(address)
        self._record(dev, address, None, "connect_start")
        link = _Link()

        def lost(generation: int) -> None:
            if link.open:
                link.open = False
                self._record(dev, address, generation, "disconnected")
            on_lost(generation)

        try:
            client = await self._inner.connect(address, timeout, lost)
        except GattError:
            self._record(dev, address, None, "connect_failed")
            raise
        self._record(dev, address, client.generation, "connected")
        return LoggingClient(client, dev, self._record, link)


@dataclass
class _Link:
    open: bool = True


class LoggingClient:
    """Client that logs what the wrapped one does."""

    def __init__(
        self, inner: GattClient, dev: str, record: _Recorder, link: _Link
    ) -> None:
        self._inner = inner
        self._dev = dev
        self._record = record
        self._link = link

    @property
    def address(self) -> str:
        """Return the address of the device."""
        return self._inner.address

    @property
    def generation(self) -> int:
        """Return the number of this connection."""
        return self._inner.generation

    def _log(self, op: str, uuid: str | None = None,
             data: bytes | None = None) -> None:
        self._record(self._dev, self.address, self.generation, op, uuid, data)

    async def read(self, char: Uuid) -> bytes:
        """Read a characteristic and log it."""
        value = await self._inner.read(char)
        self._log("read", char, value)
        return value

    async def write(self, char: Uuid, data: bytes) -> None:
        """Write a characteristic and log it."""
        self._log("write", char, data)
        try:
            await self._inner.write(char, data)
        except GattError:
            self._log("write_failed", char, data)
            raise
        self._log("write_done", char, data)

    async def subscribe(
        self, char: Uuid, on_value: Callable[[bytes], None]
    ) -> None:
        """Subscribe and log each notification."""
        op = "indicate" if char in INDICATED else "notify"

        def received(data: bytes) -> None:
            self._log(op, char, data)
            on_value(data)

        await self._inner.subscribe(char, received)

    async def close(self) -> None:
        """Close the connection and log it."""
        await self._inner.close()
        if self._link.open:
            self._link.open = False
            self._log("disconnected")
