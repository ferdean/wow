"""Define the port that encodes FIT activity files."""

from typing import Protocol

from wow.core.activity import Activity


class FitWriter(Protocol):
    """Turns a finished ride into a FIT file (ICD IF-12)."""

    def encode(self, activity: Activity) -> bytes:
        """Return the FIT file of an activity."""
        ...
