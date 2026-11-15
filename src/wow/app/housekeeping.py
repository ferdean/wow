"""Watch the free space on the Pi's card and the certificate's end.

Housekeeping (3A, app/housekeeping): the free space of the data
directory, read at most once a minute, and the warning below 1 GB
(APP-612); the days left of the display's certificate, read when the
app starts (APP-830).
"""

import logging
import math
import shutil
import ssl
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Final

from wow.core.certificate import CertificateError, not_after
from wow.core.timefmt import utc_text
from wow.ports.clock import Clock

logger = logging.getLogger(__name__)

MB: Final[int] = 1_000_000
STORAGE_LOW_MB: Final[int] = 1000
REREAD_AFTER: Final[float] = 60.0
DAY: Final[float] = 86400.0


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


def certificate_end(path: Path) -> datetime | None:
    """Return when a PEM certificate file stops being valid, if readable."""
    try:
        pem = path.read_text(encoding="ascii")
        return not_after(ssl.PEM_cert_to_DER_cert(pem))
    except (OSError, ValueError, CertificateError) as error:
        logger.warning("certificate %s unreadable: %r", path, error)
        return None


class CertificateWatch:
    """The end of validity of the display's certificate (APP-830)."""

    def __init__(self, clock: Clock, cert: Path) -> None:
        self._clock = clock
        self._end = certificate_end(cert)

    @property
    def valid_until(self) -> str | None:
        """Return the end of validity in UTC, if known."""
        return None if self._end is None else utc_text(self._end)

    def days_left(self) -> int | None:
        """Return the whole days left before the certificate ends."""
        if self._end is None:
            return None
        left = (self._end - self._clock.utc()).total_seconds()
        return math.floor(left / DAY)
