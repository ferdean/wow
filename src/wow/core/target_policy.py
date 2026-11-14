"""Decide the trainer command of each step.

The ERG target of each step and the resistance levels (AD-11; 3A,
core/target_policy; APP-302 to APP-306, APP-313). The ride decides when
each command goes out: lead time, ramp ticks and the free-ride level.
"""

from dataclasses import dataclass
from fractions import Fraction
from typing import Final

from wow.core.devices import Erg, Range, TrainerCommand
from wow.core.numbers import exact, round_half_up
from wow.core.plan import Plan

RAMP_INTERVAL: Final[float] = 1.0


@dataclass(frozen=True)
class Target:
    """A trainer command with the power asked for."""

    command: TrainerCommand
    requested_power: int | None

    @property
    def limited(self) -> bool:
        """Return whether the trainer range changed the power."""
        return (isinstance(self.command, Erg)
                and self.requested_power is not None
                and self.command.power != self.requested_power)

    @property
    def power(self) -> int | None:
        """Return the power sent, or None for a resistance command."""
        return self.command.power if isinstance(self.command, Erg) else None


def erg_target(watts: Fraction | float, intensity_pct: int,
               power_range: Range) -> Target:
    """Return an ERG target limited to the trainer range."""
    requested = round_half_up(exact(watts) * intensity_pct / 100,
                              power_range.step)
    sent = min(max(requested, power_range.minimum), power_range.maximum)
    return Target(Erg(sent), requested)


def level_raw(pct: int, level_range: Range) -> int:
    """Return the raw resistance level at a percentage of the range."""
    span = level_range.maximum - level_range.minimum
    raw = level_range.minimum + exact(span) * pct / 100
    return round_half_up(raw - level_range.minimum,
                         level_range.step) + level_range.minimum


class PlanPolicy:
    """Target policy that follows a plan."""

    def __init__(self, plan: Plan, power_range: Range) -> None:
        self._plan = plan
        self._range = power_range

    def target(self, step: int, intensity_pct: int,
               at: float | None = None) -> Target:
        """Return the ERG target of a step at an intensity and ride time."""
        planned = self._plan.steps[step]
        watts = planned.power if at is None else planned.power_at(
            min(at, planned.end))
        assert watts is not None
        return erg_target(watts, intensity_pct, self._range)
