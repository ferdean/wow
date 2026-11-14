"""Run a ride as a state machine.

Ride state machine (ICD IF-04, 4.4.2 and 4.4.3; 3A, core/ride).

Start, the wait for the first power, steps on schedule with the lead
time, ramps, ERG and resistance blocks, free-ride steps, pause, skip,
intensity, mode switches, resistance levels remembered per target, free
ride without a plan, dropouts in the journal, the end of the workout,
Finish, Discard and Cancel. The idle finish follows in SL-10.

Times: `now` is monotonic; ride time stops in a pause; plan time is
ride time plus the time skipped, so the plan's step times stay valid
after a skip.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from wow.core.devices import (
    Erg, Range, Resistance, TrainerCapabilities, TrainerCommand,
)
from wow.core.jsonform import Registry
from wow.core.numbers import round_half_up
from wow.core.plan import Plan, make_plan
from wow.core.target_policy import (
    RAMP_INTERVAL, PlanPolicy, Target, level_raw,
)
from wow.core.vocab import Mode, Problem
from wow.core.workout import (
    FREE_RIDE_REF, Block, PowerTarget, Step, StepKind, Workout,
)

ARMED_TIMEOUT: Final[float] = 1800.0
FIRST_POWER_MIN: Final[int] = 1
EPSILON: Final[float] = 1e-6
INTENSITY_STEP_PCT: Final[int] = 5
INTENSITY_MIN_PCT: Final[int] = 50
INTENSITY_MAX_PCT: Final[int] = 150
LEVEL_STEP_PCT: Final[int] = 5
FREE_RIDE_POWER_STEP: Final[int] = 5


class RidePhase(StrEnum):
    """Phase of the ride."""

    IDLE = "idle"
    ARMED = "armed"
    RUNNING = "running"
    PAUSED = "paused"
    WORKOUT_DONE = "workout_done"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class Start:
    """Event: the rider starts a ride."""

    workout: Workout
    ftp: int
    capabilities: TrainerCapabilities
    lead_time: float
    intensity_pct: int = 100
    free_ride_level_pct: int = 0
    block_modes: tuple[Mode, ...] = ()


@dataclass(frozen=True)
class CancelStart:
    """Event: the rider cancels the wait for the first power."""


@dataclass(frozen=True)
class PowerSeen:
    """Event: the trainer reported power."""

    power: int


@dataclass(frozen=True)
class Pause:
    """Event: the rider pauses."""


@dataclass(frozen=True)
class Resume:
    """Event: the rider resumes."""


@dataclass(frozen=True)
class Skip:
    """Event: the rider skips the rest of the step."""


@dataclass(frozen=True)
class Finish:
    """Event: the rider finishes the ride."""


@dataclass(frozen=True)
class Discard:
    """Event: the rider discards the ride."""


@dataclass(frozen=True)
class IntensityStep:
    """Event: intensity up (+1) or down (-1) by 5 points."""

    step: int


@dataclass(frozen=True)
class SwitchMode:
    """Event: switch the current block, or the free ride, to a mode."""

    mode: Mode
    power: int | None = None


@dataclass(frozen=True)
class ResistanceStep:
    """Event: resistance up (+1) or down (-1) by 5 % of the range."""

    step: int


@dataclass(frozen=True)
class FreeRidePowerStep:
    """Event: free-ride ERG target up (+1) or down (-1) by 5 W."""

    step: int


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


RideEvent = (Start | CancelStart | PowerSeen | Pause | Resume | Skip
             | Finish | Discard | IntensityStep | SwitchMode | ResistanceStep
             | FreeRidePowerStep | TrainerLink | HrmLink | Tick)


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


@dataclass(frozen=True)
class FreeRideLevel:
    """Action: keep the free-ride level for later rides (APP-705)."""

    level_pct: int


RideAction = SetTrainer | Journal | Refused | Ended | FreeRideLevel

RIDE_FORMS: Final[Registry] = Registry(
    Start, CancelStart, PowerSeen, Pause, Resume, Skip, Finish, Discard,
    IntensityStep, SwitchMode, ResistanceStep, FreeRidePowerStep,
    TrainerLink, HrmLink, Tick, SetTrainer, Journal, Refused, Ended,
    FreeRideLevel, Workout, Block, Step, PowerTarget, TrainerCapabilities,
    Range, Erg, Resistance,
)

ACTIVE: Final[tuple[RidePhase, ...]] = (
    RidePhase.ARMED, RidePhase.RUNNING, RidePhase.PAUSED,
    RidePhase.WORKOUT_DONE)
RIDING: Final[tuple[RidePhase, ...]] = (
    RidePhase.RUNNING, RidePhase.PAUSED, RidePhase.WORKOUT_DONE)
TIMED: Final[tuple[RidePhase, ...]] = (
    RidePhase.ARMED, RidePhase.RUNNING, RidePhase.PAUSED)


@dataclass(frozen=True)
class _Course:
    plan: Plan
    policy: PlanPolicy
    power: Range
    resistance: Range | None
    lead_time: float
    free: bool
    planned_modes: tuple[Mode, ...]


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _mode_of(command: TrainerCommand) -> Mode:
    return Mode.ERG if isinstance(command, Erg) else Mode.RESISTANCE


class Ride:
    """The state of one ride."""

    def __init__(self) -> None:
        self._trainer_up = False
        self._hrm_up = False
        self._reset(None)

    def _reset(self, course: _Course | None) -> None:
        self._phase = RidePhase.IDLE
        self._course = course
        self._intensity = 100
        self._armed_at = 0.0
        self._started_at: float | None = None
        self._paused_total = 0.0
        self._paused_at: float | None = None
        self._skipped = 0.0
        self._step = 0
        self._lead_sent = False
        self._ramp_next: float | None = None
        self._block_modes: dict[int, Mode] = {}
        self._levels: dict[int, int] = {}
        self._level_pct = 0
        self._free_pct = 0
        self._free_mode = Mode.RESISTANCE
        self._free_power = 0
        self._command: TrainerCommand | None = None

    @property
    def phase(self) -> RidePhase:
        """Return the current phase."""
        return self._phase

    @property
    def plan(self) -> Plan | None:
        """Return the plan being ridden, if any."""
        return None if self._course is None else self._course.plan

    @property
    def free(self) -> bool:
        """Return whether this is a free ride without a plan."""
        return self._course is not None and self._course.free

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

    @property
    def command(self) -> TrainerCommand | None:
        """Return the command last sent to the trainer."""
        return self._command

    @property
    def mode(self) -> Mode:
        """Return the mode of the command last sent (APP-415)."""
        command = self._command
        return Mode.ERG if command is None else _mode_of(command)

    @property
    def shown_mode(self) -> Mode:
        """Return the mode to show; while paused, the one to resume in."""
        command = self._shown_command()
        return Mode.ERG if command is None else _mode_of(command)

    @property
    def resistance_pct(self) -> int | None:
        """Return the level to show in percent of the range, if any.

        While paused, it is the level the ride resumes at.
        """
        course, command = self._course, self._shown_command()
        if not isinstance(command, Resistance) or course is None:
            return None
        levels = course.resistance
        if levels is None or levels.maximum == levels.minimum:
            return 0
        share = (command.level_raw - levels.minimum) * 100
        return round_half_up(share / (levels.maximum - levels.minimum))

    @property
    def free_ride_target(self) -> int | None:
        """Return the ERG target of a free ride, if riding by power."""
        if self.free and self._free_mode == Mode.ERG:
            return self._free_power
        return None

    def ride_time(self, now: float) -> float:
        """Return the ride time in seconds at now."""
        if self._started_at is None:
            return 0.0
        paused = self._paused_total
        if self._paused_at is not None:
            paused += now - self._paused_at
        return max(0.0, now - self._started_at - paused)

    def plan_time(self, now: float) -> float:
        """Return the plan time at now: ride time plus time skipped."""
        return self.ride_time(now) + self._skipped

    def step_left(self, now: float) -> float | None:
        """Return the time left in the current step, if any."""
        plan = self.plan
        if plan is None or self.free or self._phase not in TIMED:
            return None
        return max(0.0, plan.steps[self._step].end - self.plan_time(now))

    def remaining(self, now: float) -> float | None:
        """Return the time left in the workout, if any."""
        plan = self.plan
        if plan is None or self.free or self._phase not in TIMED:
            return None
        return max(0.0, plan.duration - self.plan_time(now))

    def step_target(self, step: int | None = None) -> Target | None:
        """Return the target of a step; the current one by default."""
        course = self._course
        index = self._step if step is None else step
        if course is None or not 0 <= index < len(course.plan.steps):
            return None
        return self._target(index)

    def current_target(self, now: float) -> Target | None:
        """Return the current step's target at now."""
        if self._course is None or self._phase not in TIMED:
            return None
        if self._phase in (RidePhase.RUNNING, RidePhase.PAUSED):
            return self._target(self._step, self.plan_time(now))
        return self.step_target()

    def handle(self, event: RideEvent, now: float) -> list[RideAction]:
        """Handle an event and return the actions to carry out."""
        match event:
            case Start():
                return self._on_start(event, now)
            case CancelStart():
                return self._on_cancel(now)
            case PowerSeen(power=power):
                return self._on_power(power, now)
            case Pause():
                return self._on_pause(now)
            case Resume():
                return self._on_resume(now)
            case Skip():
                return self._on_skip(now)
            case Finish():
                return self._on_end(RidePhase.FINISHED, "finish", now)
            case Discard():
                return self._on_end(RidePhase.DISCARDED, "discard", now)
            case IntensityStep(step=step):
                return self._on_intensity(step, now)
            case SwitchMode():
                return self._on_switch(event, now)
            case ResistanceStep(step=step):
                return self._on_resistance(step, now)
            case FreeRidePowerStep(step=step):
                return self._on_free_power(step, now)
            case TrainerLink(up=up):
                return self._on_link("trainer", up, now)
            case HrmLink(up=up):
                return self._on_link("hrm", up, now)
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
        for extra in (self._lead_due(), self._ramp_next):
            if extra is not None:
                due = min(due, extra)
        return started + self._paused_total + due - self._skipped

    def _shown_command(self) -> TrainerCommand | None:
        if self._phase == RidePhase.PAUSED and self._course is not None:
            return self._target(self._step).command
        return self._command

    def _t(self, now: float) -> float | None:
        if self._started_at is None:
            return None
        return round(self.ride_time(now), 3)

    def _mode_at(self, index: int) -> Mode:
        course = self._course
        assert course is not None
        if course.free:
            return self._free_mode
        if course.plan.steps[index].kind != StepKind.ERG:
            return Mode.RESISTANCE
        return self._block_modes.get(course.plan.steps[index].block,
                                     Mode.ERG)

    def _key(self, index: int) -> int:
        course = self._course
        assert course is not None
        power = course.plan.steps[index].power
        return -1 if power is None else round_half_up(power)

    def _level(self, pct: int) -> Target:
        course = self._course
        assert course is not None
        if course.resistance is None:
            return Target(Erg(course.power.minimum), None)
        return Target(Resistance(level_raw(pct, course.resistance)), None)

    def _target(self, index: int, at: float | None = None) -> Target:
        course = self._course
        assert course is not None
        mode = self._mode_at(index)
        if course.free:
            return (Target(Erg(self._free_power), None) if mode == Mode.ERG
                    else self._level(self._free_pct))
        if course.plan.steps[index].kind != StepKind.ERG:
            return self._level(self._free_pct)
        if mode == Mode.RESISTANCE:
            return self._level(self._levels.get(self._key(index),
                                                self._level_pct))
        return course.policy.target(index, self._intensity, at)

    def _lead_due(self) -> float | None:
        course = self._course
        if course is None or self._lead_sent:
            return None
        steps = course.plan.steps
        index = self._step
        if index + 1 >= len(steps):
            return None
        planned = steps[index]
        if self._target(index + 1).command == self._target(
                index, planned.end).command:
            return None
        return max(planned.end - course.lead_time, planned.start)

    def _ramp_after(self, after: float) -> float | None:
        course = self._course
        assert course is not None
        planned = course.plan.steps[self._step]
        if (not planned.ramp or self._lead_sent
                or self._mode_at(self._step) != Mode.ERG):
            return None
        last = planned.end - course.lead_time
        count = math.floor((after - planned.start) / RAMP_INTERVAL
                           + EPSILON) + 1
        tick = planned.start + count * RAMP_INTERVAL
        if tick < last - EPSILON:
            return tick
        if after < last - EPSILON and self._lead_due() is None:
            return max(last, after)
        return None

    def _active(self, at: float) -> Target:
        course = self._course
        assert course is not None
        if self._phase == RidePhase.WORKOUT_DONE:
            return self._level(self._free_pct)
        if self._phase == RidePhase.PAUSED:
            return self._lowest()
        lead = self._lead_due()
        if self._lead_sent or (lead is not None and at >= lead - EPSILON):
            return self._target(self._step + 1)
        planned = course.plan.steps[self._step]
        if planned.ramp and self._mode_at(self._step) == Mode.ERG:
            return self._target(self._step, min(at + course.lead_time,
                                                planned.end))
        return self._target(self._step, at)

    def _lowest(self) -> Target:
        course = self._course
        assert course is not None
        if course.resistance is None:
            return Target(Erg(course.power.minimum), None)
        return Target(Resistance(course.resistance.minimum), None)

    def _command_record(self, name: str, now: float,
                        **args: object) -> Journal:
        return Journal("command", self._t(now), {"name": name, "args": args})

    def _on_start(self, event: Start, now: float) -> list[RideAction]:
        if self._phase in ACTIVE:
            return [Refused(Problem.RIDE_RUNNING)]
        if not self._trainer_up:
            return [Refused(Problem.TRAINER_MISSING)]
        power = event.capabilities.power
        if power is None:
            return [Refused(Problem.ERG_UNAVAILABLE)]
        plan = make_plan(event.workout, event.ftp)
        course = _Course(
            plan, PlanPolicy(plan, power), power,
            event.capabilities.resistance, event.lead_time,
            event.workout.ref == FREE_RIDE_REF, tuple(event.block_modes))
        self._reset(course)
        self._intensity = event.intensity_pct
        self._phase = RidePhase.ARMED
        self._armed_at = now
        self._block_modes = {i: Mode(m) for i, m in
                             enumerate(event.block_modes)}
        self._free_pct = _clamp(event.free_ride_level_pct, 0, 100)
        self._level_pct = self._free_pct
        armed = Journal("armed", None, {
            "workout_ref": event.workout.ref, "plan_id": plan.plan_id,
            "ftp": event.ftp, "lead_time": event.lead_time,
            "block_modes": [str(m) for m in event.block_modes]})
        return [Journal("command", None, {"name": "start", "args": {}}), armed,
                *self._send(self._target(0), now)]

    def _on_cancel(self, now: float) -> list[RideAction]:
        if self._phase != RidePhase.ARMED:
            return [Refused(Problem.NOT_ARMED)]
        return [Journal("command", None,
                        {"name": "cancel_start", "args": {}}),
                *self._end(RidePhase.CANCELLED, "rider", now)]

    def _on_power(self, power: int, now: float) -> list[RideAction]:
        if self._phase != RidePhase.ARMED or power < FIRST_POWER_MIN:
            return []
        self._phase = RidePhase.RUNNING
        self._started_at = now
        self._ramp_next = self._ramp_after(0.0)
        return [Journal("ride_started", 0.0, {"power": power}),
                self._step_started("schedule", now)]

    def _on_pause(self, now: float) -> list[RideAction]:
        if self._phase != RidePhase.RUNNING:
            return [Refused(Problem.NOT_RIDING)]
        record = self._command_record("pause", now)
        self._phase = RidePhase.PAUSED
        self._paused_at = now
        return [record, Journal("paused", self._t(now)),
                *self._send(self._lowest(), now)]

    def _on_resume(self, now: float) -> list[RideAction]:
        if self._phase != RidePhase.PAUSED or self._paused_at is None:
            return [Refused(Problem.NOT_RIDING)]
        self._paused_total += now - self._paused_at
        self._paused_at = None
        self._phase = RidePhase.RUNNING
        return [self._command_record("resume", now),
                Journal("resumed", self._t(now)),
                *self._send(self._active(self.plan_time(now)), now)]

    def _on_skip(self, now: float) -> list[RideAction]:
        course = self._course
        if self._phase != RidePhase.RUNNING or course is None or course.free:
            return [Refused(Problem.NOT_RIDING)]
        record = self._command_record("skip", now)
        planned = course.plan.steps[self._step]
        self._skipped += max(0.0, planned.end - self.plan_time(now))
        actions: list[RideAction] = [record, *self._advance(now, "skip")]
        if self._phase == RidePhase.RUNNING:
            actions += self._send(self._active(self.plan_time(now)), now)
        return actions

    def _on_end(self, phase: RidePhase, name: str,
                now: float) -> list[RideAction]:
        if self._phase not in RIDING:
            return [Refused(Problem.NOT_RIDING)]
        return [self._command_record(name, now),
                *self._end(phase, "rider", now)]

    def _on_intensity(self, step: int, now: float) -> list[RideAction]:
        if self._phase != RidePhase.RUNNING or self.free:
            return [Refused(Problem.NOT_RIDING)]
        record = self._command_record("intensity", now, step=step)
        self._intensity = _clamp(
            self._intensity + INTENSITY_STEP_PCT * (1 if step > 0 else -1),
            INTENSITY_MIN_PCT, INTENSITY_MAX_PCT)
        actions: list[RideAction] = [record]
        active = self._active(self.plan_time(now))
        if isinstance(active.command, Erg):
            actions += self._send(active, now)
        return actions

    def _on_switch(self, event: SwitchMode, now: float) -> list[RideAction]:
        course = self._course
        if self._phase != RidePhase.RUNNING or course is None:
            return [Refused(Problem.NOT_RIDING)]
        mode = Mode(event.mode)
        if mode == Mode.RESISTANCE and course.resistance is None:
            return [Refused(Problem.INVALID_STATE)]
        planned = course.plan.steps[self._step]
        if course.free:
            if mode == Mode.ERG:
                power = (course.power.minimum if event.power is None
                         else round_half_up(event.power, FREE_RIDE_POWER_STEP))
                self._free_power = _clamp(power, course.power.minimum,
                                          course.power.maximum)
            self._free_mode = mode
        elif planned.kind != StepKind.ERG:
            return [Refused(Problem.INVALID_STATE)]
        else:
            self._block_modes[planned.block] = mode
        pt = self.plan_time(now)
        self._ramp_next = self._ramp_after(pt)
        return [self._command_record("switch_mode", now, mode=str(mode),
                                     power=event.power),
                *self._send(self._active(pt), now)]

    def _on_resistance(self, step: int, now: float) -> list[RideAction]:
        course = self._course
        if course is None or not isinstance(self._command, Resistance) or (
                self._phase not in (RidePhase.RUNNING,
                                    RidePhase.WORKOUT_DONE)):
            return [Refused(Problem.INVALID_STATE)]
        actions: list[RideAction] = [
            self._command_record("resistance", now, step=step)]
        delta = LEVEL_STEP_PCT * (1 if step > 0 else -1)
        free_level = (self._phase == RidePhase.WORKOUT_DONE or course.free
                      or course.plan.steps[self._step].kind != StepKind.ERG)
        if free_level:
            self._free_pct = _clamp(self._free_pct + delta, 0, 100)
            actions.append(FreeRideLevel(self._free_pct))
        else:
            self._level_pct = _clamp(
                self._levels.get(self._key(self._step), self._level_pct)
                + delta, 0, 100)
            self._levels[self._key(self._step)] = self._level_pct
        return actions + self._send(self._active(self.plan_time(now)), now)

    def _on_free_power(self, step: int, now: float) -> list[RideAction]:
        course = self._course
        if (self._phase != RidePhase.RUNNING or course is None
                or self.free_ride_target is None):
            return [Refused(Problem.INVALID_STATE)]
        self._free_power = _clamp(
            self._free_power + FREE_RIDE_POWER_STEP * (1 if step > 0 else -1),
            course.power.minimum, course.power.maximum)
        return [self._command_record("free_ride_power", now, step=step),
                *self._send(self._target(0), now)]

    def _on_tick(self, now: float) -> list[RideAction]:
        if self._phase == RidePhase.ARMED:
            if now >= self._armed_at + ARMED_TIMEOUT - EPSILON:
                return self._end(RidePhase.CANCELLED, "timeout", now)
            return []
        actions: list[RideAction] = []
        course = self._course
        while self._phase == RidePhase.RUNNING and course is not None:
            pt = self.plan_time(now) + EPSILON
            lead, ramp = self._lead_due(), self._ramp_next
            if lead is not None and pt >= lead:
                actions += self._send(self._target(self._step + 1), now)
                self._lead_sent = True
                self._ramp_next = None
            elif ramp is not None and pt >= ramp:
                self._ramp_next = self._ramp_after(ramp)
                actions += self._send(self._target(
                    self._step, ramp + course.lead_time), now)
            elif pt >= course.plan.steps[self._step].end:
                actions += self._advance(now, "schedule")
            else:
                break
        return actions

    def _advance(self, now: float, cause: str) -> list[RideAction]:
        course = self._course
        assert course is not None
        self._step += 1
        self._lead_sent = False
        if self._step == len(course.plan.steps):
            self._step -= 1
            self._phase = RidePhase.WORKOUT_DONE
            self._ramp_next = None
            done: list[RideAction] = [Journal("workout_done", self._t(now))]
            if course.resistance is None:
                return done
            return done + self._send(self._level(self._free_pct), now)
        planned = course.plan.steps[self._step]
        if self._mode_at(self._step) == Mode.RESISTANCE and (
                planned.kind == StepKind.ERG):
            self._level_pct = self._levels.get(self._key(self._step),
                                               self._level_pct)
        self._ramp_next = self._ramp_after(planned.start)
        return [self._step_started(cause, now)]

    def _step_started(self, cause: str, now: float) -> Journal:
        course = self._course
        assert course is not None
        planned = course.plan.steps[self._step]
        target = self._target(self._step)
        return Journal("step_started", self._t(now), {
            "index": self._step, "cause": cause,
            "scheduled": round(planned.start - self._skipped, 3),
            "kind": planned.kind, "mode": self._mode_at(self._step),
            "target": target.power})

    def _send(self, target: Target, now: float) -> list[RideAction]:
        t_ride = self._t(now)
        command = target.command
        self._command = command
        detail: dict[str, object] = (
            {"mode": Mode.ERG, "power": command.power}
            if isinstance(command, Erg)
            else {"mode": Mode.RESISTANCE, "level_raw": command.level_raw})
        actions: list[RideAction] = [
            SetTrainer(command),
            Journal("trainer_command", t_ride, {
                **detail, "due_mono_ms": round(now * 1000, 1)}),
        ]
        if target.limited:
            actions.append(Journal("target_limited", t_ride, {
                "requested_power": target.requested_power,
                "sent_power": target.power}))
        return actions

    def _on_link(self, device: str, up: bool,
                 now: float) -> list[RideAction]:
        before = self._trainer_up if device == "trainer" else self._hrm_up
        if device == "trainer":
            self._trainer_up = up
        else:
            self._hrm_up = up
        if self._phase not in RIDING or before == up:
            return []
        event = "dropout_end" if up else "dropout_start"
        actions: list[RideAction] = [
            Journal(event, self._t(now), {"device": device})]
        if device == "trainer" and up:
            actions += self._send(self._active(self.plan_time(now)), now)
        return actions

    def _end(self, phase: RidePhase, cause: str,
             now: float) -> list[RideAction]:
        t_ride = self._t(now)
        lowest = [] if self._course is None or (
            self._course.resistance is None) else self._send(
                self._lowest(), now)
        self._phase = phase
        if self._paused_at is not None:
            self._paused_total += now - self._paused_at
        self._paused_at = None
        self._lead_sent = False
        self._ramp_next = None
        return [Journal(phase.value, t_ride, {"cause": cause}), *lowest,
                Ended(phase)]
