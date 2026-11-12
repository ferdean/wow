"""Define the contract of core state machines.

The contract every core state machine follows (ICD IF-04, 4.4.1).
"""

from typing import Protocol


class StateMachine[E, A](Protocol):
    """A state machine driven by events and deadlines."""

    def handle(self, event: E, now: float) -> list[A]:
        """Handle an event and return the actions to carry out."""
        ...

    def next_deadline(self) -> float | None:
        """Return the time of the next Tick, if any."""
        ...
