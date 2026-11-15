"""Declare the port that uploads rides to intervals.icu."""

from pathlib import Path
from typing import Protocol

from wow.core.upload import Outcome


class ActivityUploader(Protocol):
    """Where finished rides go (ICD IF-08, 4.8.3)."""

    async def upload(self, fit: Path, name: str) -> Outcome:
        """Upload a FIT file; return what the server made of it."""
        ...
