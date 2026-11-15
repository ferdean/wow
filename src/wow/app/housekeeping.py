"""Watch the free space on the Pi's card.

Housekeeping (3A, app/housekeeping; APP-612): the free space of the data
directory, read at most once a minute, and the warning below 1 GB.
"""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Final

from wow.ports.clock import Clock

MB: Final[int] = 1_000_000
STORAGE_LOW_MB: Final[int] = 1000
REREAD_AFTER: Final[float] = 60.0


def disk_free(path: Path) -> int:
    """Return the free bytes of the file system holding path."""
    return shutil.disk_usage(path).free


class FreeSpace:
    """The free space of the data directory, in MB."""

    def __init__(self, clock: Clock, data: Path,
                 free_bytes: Callable[[Path], int] = disk_free) -> None:
        self._clock = clock
        self._data = data
        self._free_bytes = free_bytes
        self._value: int | None = None
        self._read_at = 0.0

    def free_mb(self) -> int:
        """Return the free space in MB, read at most once a minute."""
        now = self._clock.monotonic()
        if self._value is None or now - self._read_at >= REREAD_AFTER:
            target = self._data if self._data.exists() else Path("/")
            self._value = self._free_bytes(target) // MB
            self._read_at = now
        return self._value

    def low(self) -> bool:
        """Return whether less than 1 GB is free (APP-612)."""
        return self.free_mb() < STORAGE_LOW_MB
