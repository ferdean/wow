"""Provide a clock that moves only when a test moves it.

Stepped clock: time moves only when a test moves it (AD-22, A-61).

Sleepers wake in deadline order; after each wake the event loop runs
until the zero-time work that wake started has finished, so a simulated
4-hour ride takes seconds and runs the same way every time.
"""

import asyncio
import heapq
import itertools
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Final

SETTLE_ROUNDS: Final[int] = 32
DEFAULT_START: Final[float] = 1000.0
DEFAULT_UTC: Final[datetime] = datetime(2026, 11, 10, 17, 40, 48, tzinfo=UTC)


class SteppedClock:
    """Clock with simulated time."""

    def __init__(
        self,
        start: float = DEFAULT_START,
        utc_start: datetime = DEFAULT_UTC,
        synchronised: bool = True,
    ) -> None:
        self._start = start
        self._now = start
        self._utc_start = utc_start
        self._synchronised = synchronised
        self._sleepers: list[tuple[float, int, asyncio.Future[None]]] = []
        self._order = itertools.count()

    def monotonic(self) -> float:
        """Return the monotonic time in seconds."""
        return self._now

    def utc(self) -> datetime:
        """Return the simulated UTC time."""
        return self._utc_start + timedelta(seconds=self._now - self._start)

    def synchronised(self) -> bool:
        """Return whether the time counts as synchronised."""
        return self._synchronised

    def set_synchronised(self, value: bool) -> None:
        """Set whether the time counts as synchronised."""
        self._synchronised = value

    def sleepers(self) -> int:
        """Return the number of waiting sleepers."""
        return sum(1 for _, _, future in self._sleepers if not future.done())

    async def sleep_until(self, mono: float) -> None:
        """Wait until the monotonic time reaches mono."""
        if mono <= self._now:
            await asyncio.sleep(0)
            return
        future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._sleepers, (mono, next(self._order), future))
        await future

    async def advance(self, seconds: float) -> None:
        """Move time forward, waking sleepers in order."""
        await self.run_until(self._now + seconds)

    async def run_until(self, mono: float) -> None:
        """Move time forward to mono."""
        await self.settle()
        while self._sleepers and self._sleepers[0][0] <= mono:
            deadline, _, future = heapq.heappop(self._sleepers)
            if future.done():
                continue
            self._now = max(self._now, deadline)
            future.set_result(None)
            await self.settle()
        self._now = max(self._now, mono)
        await self.settle()

    async def drive[T](  # noqa: D102
        self, work: Awaitable[T], limit: float = 86400.0
    ) -> T:
        """Run work, moving time when everything waits."""
        task = asyncio.ensure_future(work)
        end = self._now + limit
        await self.settle()
        while not task.done():
            wake = self._next_wake()
            if wake is None or wake > end:
                task.cancel()
                raise TimeoutError("the work cannot finish on this clock")
            await self.run_until(wake)
        return task.result()

    def _next_wake(self) -> float | None:
        while self._sleepers and self._sleepers[0][2].done():
            heapq.heappop(self._sleepers)
        return self._sleepers[0][0] if self._sleepers else None

    async def settle(self) -> None:
        """Let all zero-time work finish."""
        for _ in range(SETTLE_ROUNDS):
            await asyncio.sleep(0)
