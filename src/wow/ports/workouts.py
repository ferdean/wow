"""Define the port that reads workouts from intervals.icu."""

from datetime import date
from typing import Any, Protocol


class ProviderError(Exception):
    """The workouts could not be read."""


class WorkoutProvider(Protocol):
    """Where planned and library workouts come from (ICD IF-08)."""

    async def planned(self, oldest: date, newest: date) -> list[Any]:
        """Return the calendar events between two local dates."""
        ...

    async def library(self) -> list[Any]:
        """Return the workouts of the library."""
        ...
