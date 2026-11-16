"""Play a Bluetooth log back behind the GATT ports.

ReplayConnector (ICD IF-11, 4.11; APP-820): connects succeed when the
log has a `connected` record for the address; reads return the recorded
values in order; received values are delivered at their recorded times;
each write of the app is compared with the next recorded write on that
characteristic. A different value, or a time more than 100 ms off, is a
mismatch that names both sides.
"""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from wow.ports.clock import Clock
from wow.ports.gatt import Advertisement, DeviceNotFound, GattError, Uuid

TOLERANCE: Final[float] = 0.1
RECEIVED: Final[frozenset[str]] = frozenset({"notify", "indicate"})


@dataclass(frozen=True)
class LogLine:
    """One record of a Bluetooth log (IF-11)."""

    mono: float
    addr: str
    gen: int | None
    op: str
    uuid: str | None
    data: bytes | None

    @staticmethod
    def of(record: Mapping[str, Any]) -> "LogLine":
        """Return the line of a JSON record."""
        hex_text = record.get("hex")
        return LogLine(float(record["mono_ms"]) / 1000,
                       str(record["addr"]).upper(), record.get("gen"),
                       str(record["op"]), record.get("uuid"),
                       None if hex_text is None else bytes.fromhex(hex_text))

    def text(self) -> str:
        """Return the line as people read it."""
        value = "" if self.data is None else self.data.hex()
        return f"{self.mono:.3f} s {self.op} {self.uuid} {value}"


class ReplayConnector:
    """GattConnector that replays a Bluetooth log."""

    def __init__(self, clock: Clock,
                 records: Sequence[Mapping[str, Any]]) -> None:
        self._clock = clock
        self._lines = [LogLine.of(r) for r in records]
        self._next_link: dict[str, int] = {}
        self.mismatches: list[str] = []

    async def scan(self, service_uuids: Sequence[Uuid],
                   duration: float) -> list[Advertisement]:
        """Return no advertisements: replays connect by address."""
        await self._clock.sleep_until(self._clock.monotonic() + duration)
        return []

    async def connect(self, address: str, timeout: float,
                      on_lost: Callable[[int], None]) -> "ReplayClient":
        """Connect when the log next connected to the address."""
        key = address.upper()
        start = self._next_link.get(key, 0)
        found = next(((i, line) for i, line in enumerate(self._lines)
                      if i >= start and line.addr == key
                      and line.op == "connected"), None)
        now = self._clock.monotonic()
        if found is None or found[1].mono > now + timeout:
            await self._clock.sleep_until(now + timeout)
            raise DeviceNotFound(address)
        index, line = found
        self._next_link[key] = index + 1
        await self._clock.sleep_until(line.mono)
        mine = [x for x in self._lines[index + 1:]
                if x.addr == key and x.gen == line.gen]
        return ReplayClient(self, self._clock, key, line.gen or 0, mine,
                            on_lost)


class ReplayClient:
    """Client of one replayed connection."""

    def __init__(self, connector: ReplayConnector, clock: Clock,
                 address: str, generation: int, lines: list[LogLine],
                 on_lost: Callable[[int], None]) -> None:
        self._connector = connector
        self._clock = clock
        self._address = address
        self._generation = generation
        self._lines = lines
        self._tasks: list[asyncio.Task[None]] = []
        self._used: set[int] = set()
        lost = next((x for x in lines if x.op == "disconnected"), None)
        if lost is not None:
            self._at(lost.mono, lambda: on_lost(generation))

    @property
    def address(self) -> str:
        """Return the address of the device."""
        return self._address

    @property
    def generation(self) -> int:
        """Return the number of this connection."""
        return self._generation

    async def read(self, char: Uuid) -> bytes:
        """Return the next recorded value of a read."""
        line = self._take("read", char)
        if line is None or line.data is None:
            raise GattError(f"no recorded read of {char}")
        await self._clock.sleep_until(line.mono)
        return line.data

    async def write(self, char: Uuid, data: bytes) -> None:
        """Compare a write with the next recorded one."""
        now = self._clock.monotonic()
        line = self._take("write", char)
        if line is None:
            self._connector.mismatches.append(
                f"app wrote {data.hex()} at {now:.3f} s; log has no write")
            return
        if line.data != data or abs(line.mono - now) > TOLERANCE:
            self._connector.mismatches.append(
                f"app: {now:.3f} s write {char} {data.hex()} | "
                f"log: {line.text()}")
        done = self._take("write_done", char)
        if done is not None:
            await self._clock.sleep_until(done.mono)

    async def subscribe(self, char: Uuid,
                        on_value: Callable[[bytes], None]) -> None:
        """Deliver the recorded values of a characteristic in time."""
        values = [(line.mono, line.data) for line in self._lines
                  if line.op in RECEIVED and line.uuid == char and line.data]
        self._tasks.append(asyncio.get_running_loop().create_task(
            self._deliver(values, on_value)))

    async def close(self) -> None:
        """Stop delivering values."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def _take(self, op: str, char: Uuid) -> LogLine | None:
        for i, line in enumerate(self._lines):
            if i not in self._used and line.op == op and line.uuid == char:
                self._used.add(i)
                return line
        return None

    async def _deliver(self, values: list[tuple[float, bytes]],
                       on_value: Callable[[bytes], None]) -> None:
        for mono, data in values:
            await self._clock.sleep_until(mono)
            on_value(data)

    def _at(self, mono: float, action: Callable[[], None]) -> None:
        async def later() -> None:
            await self._clock.sleep_until(mono)
            action()

        self._tasks.append(asyncio.get_running_loop().create_task(later()))
