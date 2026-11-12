"""Define the device ports used by the controllers.

Device ports used by the controllers (ICD IF-05, 4.5).
"""

from typing import Protocol

from wow.core.devices import LinkState, TrainerCapabilities, TrainerCommand


class Trainer(Protocol):
    """A trainer the ride controller commands."""

    def capabilities(self) -> TrainerCapabilities | None:
        """Return the trainer capabilities, if known."""
        ...

    def link(self) -> LinkState:
        """Return the link state."""
        ...

    def set_command(self, command: TrainerCommand) -> None:
        """Set the command the trainer should hold."""
        ...

    def responding(self) -> bool:
        """Return whether the trainer answers in time."""
        ...

    def in_control(self) -> bool:
        """Return whether the app holds control."""
        ...


class HeartRateMonitor(Protocol):
    """A heart-rate strap."""

    def link(self) -> LinkState:
        """Return the link state."""
        ...

    def battery_pct(self) -> int | None:
        """Return the battery level, if known."""
        ...
