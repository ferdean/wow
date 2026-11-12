"""Provide the clocks of the machine.

The Pi's clocks (ICD IF-04; AD-08, AD-22).
"""

import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

TIMESYNC_MARKER: Final[Path] = Path("/run/systemd/timesync/synchronized")


def default_sync_marker() -> Path | None:
    """Return the time-sync marker of this machine, if any."""
    return TIMESYNC_MARKER if sys.platform == "linux" else None


class SystemClock:
    """Clock on the machine time."""

    def __init__(self, sync_marker: Path | None) -> None:
        self._sync_marker = sync_marker

    def monotonic(self) -> float:
        """Return the monotonic time in seconds."""
        return time.monotonic()

    def utc(self) -> datetime:
        """Return the current UTC time."""
        return datetime.now(UTC)

    def synchronised(self) -> bool:
        """Return whether the machine time is synchronised."""
        return self._sync_marker is None or self._sync_marker.exists()

    async def sleep_until(self, mono: float) -> None:
        """Wait until the monotonic time reaches mono."""
        await asyncio.sleep(max(0.0, mono - time.monotonic()))
