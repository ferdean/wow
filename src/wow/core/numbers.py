"""Round numbers and place power in zones.

Rounding and power zones (ICD 1.4; APP-302, APP-702).
"""

import math
from collections.abc import Sequence
from fractions import Fraction
from typing import Final

DEFAULT_ZONES_PCT: Final[tuple[int, ...]] = (55, 75, 90, 105, 120)


def exact(value: float | int | Fraction) -> Fraction:
    """Return the exact fraction of a number."""
    if isinstance(value, Fraction):
        return value
    if isinstance(value, float):
        return Fraction(str(value))
    return Fraction(value)


def round_half_up(value: float | int | Fraction, step: int = 1) -> int:
    """Round to a multiple of step, halves upward."""
    return math.floor(exact(value) / step + Fraction(1, 2)) * step


def zone_of(
    power: float | Fraction, ftp: int,
    zones_pct: Sequence[int] = DEFAULT_ZONES_PCT,
) -> int:
    """Return the power zone, counted from 1."""
    share = exact(power) * 100 / ftp
    for zone, upper in enumerate(zones_pct, start=1):
        if share <= upper:
            return zone
    return len(zones_pct) + 1
