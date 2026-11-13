"""Flatten a workout into a ride plan.

Flattens a workout at an FTP into a ride plan: steps with their start
and end ride times and targets in watts (3A, core/plan; APP-203, APP-302).
"""

from dataclasses import dataclass
from fractions import Fraction

from wow.core.workout import Step, StepKind, Workout


@dataclass(frozen=True)
class PlanStep:
    """One step of a plan, in ride time and watts."""

    index: int
    block: int
    start: float
    end: float
    power: Fraction | None
    text: str | None
    end_power: Fraction | None = None
    kind: StepKind = StepKind.ERG

    @property
    def duration(self) -> float:
        """Return the length of the step in seconds."""
        return self.end - self.start

    @property
    def ramp(self) -> bool:
        """Return whether the power changes during the step."""
        return self.end_power is not None and self.end_power != self.power

    def power_at(self, t_ride: float) -> Fraction | None:
        """Return the planned power at a ride time within the step."""
        if self.power is None or self.end_power is None:
            return self.power
        share = min(max((t_ride - self.start) / self.duration, 0.0), 1.0)
        return self.power + (self.end_power - self.power) * Fraction(
            str(share))


@dataclass(frozen=True)
class Plan:
    """A workout flattened at an FTP."""

    plan_id: str
    workout: Workout
    ftp: int
    steps: tuple[PlanStep, ...]

    @property
    def duration(self) -> float:
        """Return the length of the plan in seconds."""
        return self.steps[-1].end


def make_plan(workout: Workout, ftp: int) -> Plan:
    """Flatten a workout at an FTP."""
    steps: list[PlanStep] = []
    start = 0.0
    for block_index, block in enumerate(workout.blocks):
        for _ in range(block.repeats):
            for step in block.steps:
                steps.append(_plan_step(step, len(steps), block_index,
                                        start, ftp))
                start += step.duration
    return Plan(f"{workout.ref}@{ftp}", workout, ftp, tuple(steps))


def _plan_step(step: Step, index: int, block: int, start: float,
               ftp: int) -> PlanStep:
    power = None if step.target is None else step.target.watts(ftp)
    end = None if step.end is None else step.end.watts(ftp)
    kind = step.kind if step.target is not None else (
        step.kind if step.kind != StepKind.ERG else StepKind.UNSUPPORTED)
    return PlanStep(index, block, start, start + step.duration, power,
                    step.text, end, kind)
