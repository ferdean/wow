"""Run the timed behaviour of simulated devices.

Runs the simulated devices' timed behaviour on the app's Clock.
"""

import asyncio
import itertools
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from wow.ports.clock import Clock


class SimScheduler:
    """Schedules callbacks on the Clock."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self._tasks: set[asyncio.Task[None]] = set()

    def now(self) -> float:
        """Return the monotonic time in seconds."""
        return self.clock.monotonic()

    def call_at(
        self, mono: float, callback: Callable[[], None]
    ) -> asyncio.Task[None]:
        """Call back once at mono."""
        async def wait() -> None:
            await self.clock.sleep_until(mono)
            callback()

        return self._spawn(wait())

    def repeat(
        self,
        start: float,
        intervals: Sequence[float],
        callback: Callable[[], None],
    ) -> asyncio.Task[None]:
        """Call back from start on, cycling through the intervals."""
        async def loop() -> None:
            due = start
            for count in itertools.count():
                await self.clock.sleep_until(due)
                callback()
                due += intervals[count % len(intervals)]

        return self._spawn(loop())

    async def close(self) -> None:
        """Cancel everything scheduled."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _spawn(
        self, work: Coroutine[Any, Any, None]
    ) -> asyncio.Task[None]:
        task = asyncio.get_running_loop().create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
