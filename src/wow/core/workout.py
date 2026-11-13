"""Define workout value types.

Workout value types (3A, core/workout): steps hold one power, a ramp
from one power to another, free ride, or a target the app can't apply.
"""

from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction

from wow.core.numbers import exact


class PowerUnit(StrEnum):
    """Unit of a power target."""

    WATTS = "w"
    PERCENT_FTP = "%ftp"


class StepKind(StrEnum):
    """What a step asks of the trainer."""

    ERG = "erg"
    FREE_RIDE = "free_ride"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class PowerTarget:
    """A power value in a unit."""

    value: float
    units: PowerUnit

    def watts(self, ftp: int) -> Fraction:
        """Return the target in watts at an FTP."""
        if self.units == PowerUnit.WATTS:
            return exact(self.value)
        return exact(self.value) * ftp / 100


@dataclass(frozen=True)
class Step:
    """A timed step; a ramp has an end target."""

    duration: float
    target: PowerTarget | None
    text: str | None
    end: PowerTarget | None = None
    kind: StepKind = StepKind.ERG


@dataclass(frozen=True)
class Block:
    """Steps repeated a number of times."""

    label: str | None
    repeats: int
    steps: tuple[Step, ...]

    @property
    def duration(self) -> float:
        """Return the length of the block in seconds."""
        return sum(step.duration for step in self.steps) * self.repeats


@dataclass(frozen=True)
class Workout:
    """A named workout of blocks."""

    ref: str
    name: str
    description: str | None
    blocks: tuple[Block, ...]
