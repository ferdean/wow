"""Provide the only source of time.

The only source of time for the app (ICD IF-04, 4.4.1; AD-08, AD-22).
"""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Time source of the app."""

    def monotonic(self) -> float:
        """Return the monotonic time in seconds."""
        ...

    def utc(self) -> datetime:
        """Return the current UTC time."""
        ...

    def synchronised(self) -> bool:
        """Return whether the system time is synchronised."""
        ...

    async def sleep_until(self, mono: float) -> None:
        """Wait until the monotonic time reaches mono."""
        ...
