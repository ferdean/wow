"""Flatten a workout into a ride plan.

Flattens a workout at an FTP into a ride plan: steps with their start
and end ride times and targets in watts (3A, core/plan; APP-203, APP-302).
"""

from dataclasses import dataclass
from fractions import Fraction

from wow.core.workout import Workout


@dataclass(frozen=True)
class PlanStep:
    """One step of a plan, in ride time and watts."""

    index: int
    block: int
    start: float
    end: float
    power: Fraction
    text: str | None

    @property
    def duration(self) -> float:
        """Return the length of the step in seconds."""
        return self.end - self.start


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
                steps.append(PlanStep(len(steps), block_index, start,
                                      start + step.duration,
                                      step.target.watts(ftp), step.text))
                start += step.duration
    return Plan(f"{workout.ref}@{ftp}", workout, ftp, tuple(steps))
