"""Declare the status LED port (3A, ports/StatusLed; APP-826)."""

from typing import Protocol


class StatusLed(Protocol):
    """A light that is on or off."""

    def set(self, on: bool) -> None:
        """Switch the light on or off."""
        ...
