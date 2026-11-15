"""Log the times of taps and painted views while a ride runs.

The ride's `timing.jsonl` (ICD 4.6.7, 4.9.5; APP-802, APP-803): one
line per tap that changes the target, level, mode or intensity, with the
start of the trainer write it led to, and one line per painted view
with the arrival of the newest value it shows. Times are in ms on the
Pi's monotonic clock; the page converts its own with the offset of its
best ping, whose round trip each line carries.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from wow.core.vocab import CommandName
from wow.ports.clock import Clock

TAP_COMMANDS: Final[frozenset[str]] = frozenset({
    CommandName.INTENSITY, CommandName.RESISTANCE, CommandName.SWITCH_MODE,
    CommandName.FREE_RIDE_POWER, CommandName.PAUSE, CommandName.RESUME,
    CommandName.SKIP})
WRITE_WAIT: Final[float] = 1.0
TAP: Final[str] = "tap"
PAINT: Final[str] = "paint"


@dataclass
class _Tap:
    name: str
    tap_ms: float
    recv_ms: float
    pending: bool
    rtt_ms: float | None


def _ms(mono: float) -> float:
    return round(mono * 1000, 1)


class TimingLog:
    """Collects tap and paint times into the ride's timing.jsonl."""

    def __init__(self, clock: Clock, write: Callable[[Mapping[str, object]],
                                                     None],
                 riding: Callable[[], bool],
                 pending: Callable[[], bool]) -> None:
        self._clock = clock
        self._write = write
        self._riding = riding
        self._pending = pending
        self._waiting: list[_Tap] = []
        self._tasks: set[asyncio.Task[None]] = set()

    def received(self) -> tuple[float, bool]:
        """Return when a command arrived and whether a procedure pends.

        Both are taken before the command is carried out.
        """
        return self._clock.monotonic(), self._pending()

    def tap(self, name: str, tap_ms: object, rtt_ms: object,
            arrival: tuple[float, bool]) -> None:
        """Note a carried-out command; its line waits for the write."""
        recv, pending = arrival
        recv_ms = _ms(recv)
        if (name not in TAP_COMMANDS or not self._riding()
                or not isinstance(tap_ms, (int, float))
                or isinstance(tap_ms, bool) or tap_ms > recv_ms):
            return
        tap = _Tap(name, float(tap_ms), recv_ms, pending, _number(rtt_ms))
        self._waiting.append(tap)
        task = asyncio.get_running_loop().create_task(self._expire(tap, recv))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def written(self, mono: float) -> None:
        """Note the start of a control point write."""
        due, self._waiting = self._waiting, []
        for tap in due:
            self._line(tap, _ms(mono))

    def painted(self, seq: int, data_ms: float | None, sent_ms: float,
                paint_ms: object, rtt_ms: object) -> None:
        """Note a view the page painted."""
        if (data_ms is None or not self._riding()
                or not isinstance(paint_ms, (int, float))
                or isinstance(paint_ms, bool)):
            return
        self._write({"kind": PAINT, "seq": seq, "data_mono_ms": data_ms,
                     "sent_mono_ms": sent_ms,
                     "paint_mono_ms": float(paint_ms),
                     "rtt_ms": _number(rtt_ms)})

    async def close(self) -> None:
        """Write the taps still waiting and stop."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        due, self._waiting = self._waiting, []
        for tap in due:
            self._line(tap, None)

    async def _expire(self, tap: _Tap, recv: float) -> None:
        await self._clock.sleep_until(recv + WRITE_WAIT)
        if tap in self._waiting:
            self._waiting.remove(tap)
            self._line(tap, None)

    def _line(self, tap: _Tap, write_ms: float | None) -> None:
        self._write({"kind": TAP, "name": tap.name, "tap_mono_ms": tap.tap_ms,
                     "recv_mono_ms": tap.recv_ms, "write_mono_ms": write_ms,
                     "pending": tap.pending, "rtt_ms": tap.rtt_ms})


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
