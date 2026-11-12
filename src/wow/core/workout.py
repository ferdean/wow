"""Define workout value types.

Workout value types (3A, core/workout).

Slice SL-02: power targets in watts or percent of FTP; ranges, zones,
ramps, free ride and unsupported targets follow in SL-04.
"""

from dataclasses import dataclass
from fractions import Fraction
from enum import StrEnum

from wow.core.numbers import exact


class PowerUnit(StrEnum):
    """Unit of a power target."""

    WATTS = "w"
    PERCENT_FTP = "%ftp"


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
    """A timed power step."""

    duration: float
    target: PowerTarget
    text: str | None


@dataclass(frozen=True)
class Block:
    """Steps repeated a number of times."""

    label: str | None
    repeats: int
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class Workout:
    """A named workout of blocks."""

    ref: str
    name: str
    description: str | None
    blocks: tuple[Block, ...]
