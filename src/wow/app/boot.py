"""Read the boot ID.

The boot ID that tells a restart of the app from a reboot of the Pi
(ICD IF-09, 4.9.2 and 4.9.4).
"""

import uuid
from pathlib import Path
from typing import Final

LINUX_BOOT_ID: Final[Path] = Path("/proc/sys/kernel/random/boot_id")


def boot_id(source: Path = LINUX_BOOT_ID) -> str:
    """Return the ID of the current boot of the machine."""
    try:
        return source.read_text(encoding="ascii").strip()
    except OSError:
        return f"process-{uuid.uuid4()}"
