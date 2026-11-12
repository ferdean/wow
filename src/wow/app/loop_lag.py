"""Measure how late the event loop wakes up.

Measures how late the event loop wakes up (AD-06, A-51): any lag over
50 ms is logged and counted.
"""

import logging

from wow.ports.clock import Clock
from typing import Final

logger = logging.getLogger(__name__)

INTERVAL: Final[float] = 0.1
THRESHOLD: Final[float] = 0.05


class LoopLagMonitor:
    """Logs and counts wake-ups that are late."""

    def __init__(self, clock: Clock, interval: float = INTERVAL,
                 threshold: float = THRESHOLD) -> None:
        self._clock = clock
        self._interval = interval
        self._threshold = threshold
        self.worst = 0.0
        self.late = 0

    async def run(self) -> None:
        """Measure until cancelled."""
        due = self._clock.monotonic()
        while True:
            due += self._interval
            await self._clock.sleep_until(due)
            lag = self._clock.monotonic() - due
            self.worst = max(self.worst, lag)
            if lag > self._threshold:
                self.late += 1
                logger.warning("event loop %.0f ms late", lag * 1000)
                due = self._clock.monotonic()
