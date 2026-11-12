"""Decide the trainer command of each step.

The trainer command for each step and when to send it (AD-11; 3A,
core/target_policy; APP-302 to APP-304, APP-313).

Slice SL-02: ERG steps. Ramps, resistance blocks and free ride follow in
SL-05.
"""

from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol

from wow.core.devices import Erg, Range
from wow.core.numbers import exact, round_half_up
from wow.core.plan import Plan


@dataclass(frozen=True)
class Target:
    """A trainer command with the power asked for."""

    command: Erg
    requested_power: int

    @property
    def limited(self) -> bool:
        """Return whether the trainer range changed the power."""
        return self.command.power != self.requested_power


class TargetPolicy(Protocol):
    """Decide the target of a step and when to send it."""

    def target(self, step: int, intensity_pct: int) -> Target:
        """Return the target of a step at an intensity."""
        ...

    def send_time(self, step: int, step_start: float,
                  intensity_pct: int) -> float | None:
        """Return when to send the target of a step, if at all."""
        ...


def erg_target(watts: Fraction | float, intensity_pct: int,
               power_range: Range) -> Target:
    """Return an ERG target limited to the trainer range."""
    requested = round_half_up(exact(watts) * intensity_pct / 100,
                              power_range.step)
    sent = min(max(requested, power_range.minimum), power_range.maximum)
    return Target(Erg(sent), requested)


class PlanPolicy:
    """Target policy that follows a plan."""

    def __init__(self, plan: Plan, power_range: Range, lead_time: float):
        self._plan = plan
        self._range = power_range
        self._lead_time = lead_time

    def target(self, step: int, intensity_pct: int) -> Target:
        """Return the target of a step at an intensity."""
        return erg_target(self._plan.steps[step].power, intensity_pct,
                          self._range)

    def send_time(self, step: int, step_start: float,
                  intensity_pct: int) -> float | None:
        """Return when to send the target of a step, if at all."""
        if step + 1 >= len(self._plan.steps):
            return None
        following = self.target(step + 1, intensity_pct)
        if following.command == self.target(step, intensity_pct).command:
            return None
        boundary = self._plan.steps[step].end
        return max(boundary - self._lead_time, step_start)
