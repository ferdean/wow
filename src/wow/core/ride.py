"""Run a ride as a state machine.

Ride state machine (ICD IF-04, 4.4.2 and 4.4.3; 3A, core/ride).

Slice SL-02: Start, the wait for the first power, steps on schedule with
the lead time, the end of the workout, Finish and Cancel. Pause, skip,
intensity, mode switches, free ride and Discard follow in SL-05; the idle
finish in SL-10.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from wow.core.devices import (
    Erg, Range, Resistance, TrainerCapabilities, TrainerCommand,
)
from wow.core.jsonform import Registry
from wow.core.plan import Plan, make_plan
from wow.core.target_policy import PlanPolicy, Target
from wow.core.workout import Block, PowerTarget, Step, Workout
from wow.core.vocab import Mode, Problem
from typing import Final

ARMED_TIMEOUT: Final[float] = 1800.0
FIRST_POWER_MIN: Final[int] = 1
EPSILON: Final[float] = 1e-6


class RidePhase(StrEnum):
    """Phase of the ride."""

    IDLE = "idle"
    ARMED = "armed"
    RUNNING = "running"
    WORKOUT_DONE = "workout_done"
    FINISHED = "finished"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Start:
    """Event: the rider starts a ride."""

    workout: Workout
    ftp: int
    capabilities: TrainerCapabilities
    lead_time: float
    intensity_pct: int = 100


@dataclass(frozen=True)
class CancelStart:
    """Event: the rider cancels the wait for the first power."""

    pass


@dataclass(frozen=True)
class PowerSeen:
    """Event: the trainer reported power."""

    power: int


@dataclass(frozen=True)
class Finish:
    """Event: the rider finishes the ride."""

    pass


@dataclass(frozen=True)
class TrainerLink:
    """Event: the trainer link went up or down."""

    up: bool


@dataclass(frozen=True)
class HrmLink:
    """Event: the strap link went up or down."""

    up: bool


@dataclass(frozen=True)
class Tick:
    """Event: a deadline of the ride has come."""

    pass


RideEvent = (Start | CancelStart | PowerSeen | Finish | TrainerLink | HrmLink
             | Tick)


@dataclass(frozen=True)
class SetTrainer:
    """Action: send a command to the trainer."""

    command: TrainerCommand


@dataclass(frozen=True)
class Journal:
    """Action: write a journal record."""

    event: str
    t_ride: float | None
    data: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Refused:
    """Action: a request was refused."""

    reason: Problem


@dataclass(frozen=True)
class Ended:
    """Action: the ride has ended."""

    cause: RidePhase


RideAction = SetTrainer | Journal | Refused | Ended

RIDE_FORMS: Final[Registry] = Registry(
    Start, CancelStart, PowerSeen, Finish, TrainerLink, HrmLink, Tick,
    SetTrainer, Journal, Refused, Ended, Workout, Block, Step, PowerTarget,
    TrainerCapabilities, Range, Erg, Resistance,
)


ACTIVE: Final[tuple[RidePhase, ...]] = (
    RidePhase.ARMED, RidePhase.RUNNING, RidePhase.WORKOUT_DONE)


@dataclass(frozen=True)
class _Course:
    plan: Plan
    policy: PlanPolicy
    lowest_level: int | None


class Ride:
    """The state of one ride."""

    def __init__(self) -> None:
        self._phase = RidePhase.IDLE
        self._trainer_up = False
        self._hrm_up = False
        self._course: _Course | None = None
        self._intensity = 100
        self._armed_at = 0.0
        self._started_at: float | None = None
        self._step = 0
        self._step_start = 0.0
        self._lead_due: float | None = None

    @property
    def phase(self) -> RidePhase:
        """Return the current phase."""
        return self._phase

    @property
    def plan(self) -> Plan | None:
        """Return the plan being ridden, if any."""
        return None if self._course is None else self._course.plan

    @property
    def step(self) -> int:
        """Return the index of the current step."""
        return self._step

    @property
    def intensity_pct(self) -> int:
        """Return the intensity in percent."""
        return self._intensity

    @property
    def trainer_up(self) -> bool:
        """Return whether the trainer link is up."""
        return self._trainer_up

    @property
    def hrm_up(self) -> bool:
        """Return whether the strap link is up."""
        return self._hrm_up

    def ride_time(self, now: float) -> float:
        """Return the ride time in seconds at now."""
        if self._started_at is None:
            return 0.0
        return max(0.0, now - self._started_at)

    def step_target(self, step: int | None = None) -> Target | None:
        """Return the target of a step; the current one by default."""
        course = self._course
        index = self._step if step is None else step
        if course is None or not 0 <= index < len(course.plan.steps):
            return None
        return course.policy.target(index, self._intensity)

    def handle(self, event: RideEvent, now: float) -> list[RideAction]:
        """Handle an event and return the actions to carry out."""
        match event:
            case Start():
                return self._on_start(event, now)
            case CancelStart():
                return self._on_cancel(now)
            case PowerSeen(power=power):
                return self._on_power(power, now)
            case Finish():
                return self._on_finish(now)
            case TrainerLink(up=up):
                self._trainer_up = up
            case HrmLink(up=up):
                self._hrm_up = up
            case Tick():
                return self._on_tick(now)
        return []

    def next_deadline(self) -> float | None:
        """Return the time of the next Tick, if any."""
        if self._phase == RidePhase.ARMED:
            return self._armed_at + ARMED_TIMEOUT
        course, started = self._course, self._started_at
        if self._phase != RidePhase.RUNNING or not course or started is None:
            return None
        due = course.plan.steps[self._step].end
        if self._lead_due is not None:
            due = min(due, self._lead_due)
        return started + due

    def _t(self, now: float) -> float | None:
        if self._started_at is None:
            return None
        return round(now - self._started_at, 3)

    def _on_start(self, event: Start, now: float) -> list[RideAction]:
        if self._phase in ACTIVE:
            return [Refused(Problem.RIDE_RUNNING)]
        if not self._trainer_up:
            return [Refused(Problem.TRAINER_MISSING)]
        power = event.capabilities.power
        if power is None:
            return [Refused(Problem.ERG_UNAVAILABLE)]
        resistance = event.capabilities.resistance
        plan = make_plan(event.workout, event.ftp)
        course = _Course(plan, PlanPolicy(plan, power, event.lead_time),
                         None if resistance is None else resistance.minimum)
        self._course = course
        self._intensity = event.intensity_pct
        self._phase = RidePhase.ARMED
        self._armed_at = now
        self._started_at = None
        self._step = 0
        self._step_start = 0.0
        self._lead_due = None
        armed = Journal("armed", None, {
            "workout_ref": event.workout.ref, "plan_id": plan.plan_id,
            "ftp": event.ftp, "lead_time": event.lead_time})
        return [Journal("command", None, {"name": "start"}), armed,
                *self._send(course.policy.target(0, self._intensity), now)]

    def _on_cancel(self, now: float) -> list[RideAction]:
        if self._phase != RidePhase.ARMED:
            return [Refused(Problem.NOT_ARMED)]
        return [Journal("command", None, {"name": "cancel_start"}),
                *self._end(RidePhase.CANCELLED, "rider", now)]

    def _on_power(self, power: int, now: float) -> list[RideAction]:
        course = self._course
        if (self._phase != RidePhase.ARMED or power < FIRST_POWER_MIN
                or course is None):
            return []
        self._phase = RidePhase.RUNNING
        self._started_at = now
        self._lead_due = course.policy.send_time(0, 0.0, self._intensity)
        return [Journal("ride_started", 0.0, {"power": power}),
                self._step_started("schedule")]

    def _on_finish(self, now: float) -> list[RideAction]:
        if self._phase not in (RidePhase.RUNNING, RidePhase.WORKOUT_DONE):
            return [Refused(Problem.NOT_RIDING)]
        return [Journal("command", self._t(now), {"name": "finish"}),
                *self._end(RidePhase.FINISHED, "rider", now)]

    def _on_tick(self, now: float) -> list[RideAction]:
        if self._phase == RidePhase.ARMED:
            if now >= self._armed_at + ARMED_TIMEOUT - EPSILON:
                return self._end(RidePhase.CANCELLED, "timeout", now)
            return []
        actions: list[RideAction] = []
        course = self._course
        while self._phase == RidePhase.RUNNING and course is not None:
            step = self._step
            t = self.ride_time(now) + EPSILON
            lead = self._lead_due
            if lead is not None and t >= lead:
                self._lead_due = None
                actions += self._send(
                    course.policy.target(step + 1, self._intensity), now)
            elif t >= course.plan.steps[step].end:
                actions += self._advance(course, now)
            else:
                break
        return actions

    def _advance(self, course: _Course, now: float) -> list[RideAction]:
        self._step += 1
        if self._step == len(course.plan.steps):
            self._phase = RidePhase.WORKOUT_DONE
            return [Journal("workout_done", self._t(now)),
                    *self._lowest(now)]
        self._step_start = course.plan.steps[self._step].start
        self._lead_due = course.policy.send_time(
            self._step, self._step_start, self._intensity)
        return [self._step_started("schedule", now)]

    def _step_started(self, cause: str, now: float | None = None) -> Journal:
        plan = self.plan
        scheduled = 0.0 if plan is None else plan.steps[self._step].start
        t_ride = 0.0 if now is None else self._t(now)
        return Journal("step_started", t_ride, {
            "index": self._step, "cause": cause, "scheduled": scheduled})

    def _send(self, target: Target, now: float) -> list[RideAction]:
        t_ride = self._t(now)
        actions: list[RideAction] = [
            SetTrainer(target.command),
            Journal("trainer_command", t_ride, {
                "mode": Mode.ERG, "power": target.command.power,
                "due_mono_ms": round(now * 1000, 1)}),
        ]
        if target.limited:
            actions.append(Journal("target_limited", t_ride, {
                "requested_power": target.requested_power,
                "sent_power": target.command.power}))
        return actions

    def _lowest(self, now: float) -> list[RideAction]:
        level = None if self._course is None else self._course.lowest_level
        if level is None:
            return []
        return [SetTrainer(Resistance(level)),
                Journal("trainer_command", self._t(now), {
                    "mode": Mode.RESISTANCE, "level_raw": level,
                    "due_mono_ms": round(now * 1000, 1)})]

    def _end(self, phase: RidePhase, cause: str,
             now: float) -> list[RideAction]:
        t_ride = self._t(now)
        self._phase = phase
        self._lead_due = None
        return [Journal(phase.value, t_ride, {"cause": cause}),
                *self._lowest(now), Ended(phase)]
