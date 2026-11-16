"""Drive the Pi's green ACT LED through sysfs.

The status LED (3A, adapters/led_sysfs; APP-826; A-36): the LED's trigger
is set to `none`, then `brightness` is written. The systemd unit gives
the group wow write access to both files; without it the LED is left
alone and the app runs on.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SysfsLed:
    """An LED under /sys/class/leds."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lit: bool | None = None
        self._ok = self._write("trigger", "none")
        self._maximum = self._read_maximum() if self._ok else "1"

    def set(self, on: bool) -> None:
        """Switch the LED on or off."""
        if not self._ok or on == self._lit:
            return
        self._lit = on
        self._ok = self._write("brightness", self._maximum if on else "0")

    def _read_maximum(self) -> str:
        try:
            return (self._path / "max_brightness").read_text().strip() or "1"
        except OSError:
            return "1"

    def _write(self, name: str, value: str) -> bool:
        try:
            (self._path / name).write_text(value)
        except OSError as error:
            logger.warning("LED %s: %s; the LED is left alone",
                           self._path / name, error)
            return False
        return True
