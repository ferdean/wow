"""Decide the trainer command of each step.

The trainer command for each step and when to send it (AD-11; 3A,
core/target_policy; APP-302 to APP-306, APP-313). ERG steps hold their
power; ramps send the value one lead time ahead at least every second;
free-ride and unsupported steps ride at the free-ride level.
"""

import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Final, Protocol

from wow.core.devices import Erg, Range, Resistance, TrainerCommand
from wow.core.numbers import exact, round_half_up
from wow.core.plan import Plan

RAMP_INTERVAL: Final[float] = 1.0
EPSILON: Final[float] = 1e-6


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


class TargetPolicy(Protocol):
    """Decide the target of a step and when to send it."""

    def target(self, step: int, intensity_pct: int,
               at: float | None = None) -> Target:
        """Return the target of a step at an intensity and ride time."""
        ...

    def send_time(self, step: int, step_start: float,
                  intensity_pct: int) -> float | None:
        """Return when to send the next step's target, if at all."""
        ...

    def ramp_tick(self, step: int, after: float,
                  intensity_pct: int) -> float | None:
        """Return the next ride time a ramp sends a command, if any."""
        ...


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

    def __init__(self, plan: Plan, power_range: Range, lead_time: float,
                 free_level: int | None = None) -> None:
        self._plan = plan
        self._range = power_range
        self._lead_time = lead_time
        self._free_level = free_level

    def target(self, step: int, intensity_pct: int,
               at: float | None = None) -> Target:
        """Return the target of a step at an intensity and ride time."""
        planned = self._plan.steps[step]
        watts = planned.power if at is None else planned.power_at(
            min(at, planned.end))
        if watts is None:
            return self.free_ride()
        return erg_target(watts, intensity_pct, self._range)

    def free_ride(self) -> Target:
        """Return the free-ride command."""
        if self._free_level is None:
            return Target(Erg(self._range.minimum), None)
        return Target(Resistance(self._free_level), None)

    def send_time(self, step: int, step_start: float,
                  intensity_pct: int) -> float | None:
        """Return when to send the next step's target, if at all."""
        steps = self._plan.steps
        if step + 1 >= len(steps):
            return None
        boundary = steps[step].end
        following = self.target(step + 1, intensity_pct)
        current = self.target(step, intensity_pct, boundary)
        if following.command == current.command:
            return None
        return max(boundary - self._lead_time, step_start)

    def ramp_tick(self, step: int, after: float,
                  intensity_pct: int) -> float | None:
        """Return the next ride time a ramp sends a command, if any."""
        planned = self._plan.steps[step]
        if not planned.ramp:
            return None
        last = planned.end - self._lead_time
        count = math.floor((after - planned.start) / RAMP_INTERVAL
                           + EPSILON) + 1
        tick = planned.start + count * RAMP_INTERVAL
        if tick < last - EPSILON:
            return tick
        boundary_send = self.send_time(step, planned.start, intensity_pct)
        if after < last - EPSILON and boundary_send is None:
            return max(last, after)
        return None

    @property
    def lead_time(self) -> float:
        """Return the lead time in seconds."""
        return self._lead_time
