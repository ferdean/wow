"""Build the view state sent to the display.

The domain view state the Pi sends to the display (ICD IF-06, 4.6.3;
AD-18). Values only, no formatting.

Slice SL-02: Home with the built-in workouts, Pre-ride, and the ride
screen while armed, in ERG and after the last step.
"""

from collections import deque
from collections.abc import Sequence
from typing import Any, Final

from wow.core.devices import LinkState
from wow.core.numbers import DEFAULT_ZONES_PCT, round_half_up, zone_of
from wow.core.plan import Plan
from wow.core.ride import Ride, RidePhase
from wow.core.workout import Workout
from wow.core.vocab import Mode, Problem, Screen

AVERAGE_WINDOW: Final[float] = 3.0
DATA_DROPOUT: Final[float] = 3.0

Json = dict[str, Any]


class PowerAverage:
    """Mean of the values received in the last 3 s (APP-402)."""

    def __init__(self, window: float = AVERAGE_WINDOW) -> None:
        self._window = window
        self._values: deque[tuple[float, int]] = deque()

    def add(self, mono: float, power: int | None) -> None:
        """Add a reading taken at mono."""
        if power is not None:
            self._values.append((mono, power))

    def value(self, now: float) -> int | None:
        """Return the mean at now, or None without readings."""
        while self._values and self._values[0][0] <= now - self._window:
            self._values.popleft()
        if not self._values:
            return None
        total = sum(power for _, power in self._values)
        return round_half_up(total / len(self._values))


class Latest:
    """The newest value, while it is younger than the dropout time."""

    def __init__(self, dropout: float = DATA_DROPOUT) -> None:
        self._dropout = dropout
        self._value: int | None = None
        self._at: float | None = None

    def add(self, mono: float, value: int | None) -> None:
        """Add a value received at mono."""
        self._value, self._at = value, mono

    def value(self, now: float) -> int | None:
        """Return the value at now, or None once it is stale."""
        if self._at is None or now - self._at >= self._dropout:
            return None
        return self._value


def _watts(plan: Plan, step: int) -> int:
    return round_half_up(plan.steps[step].power)


def _ms(value: float) -> float:
    return round(value, 3)


def workout_card(workout: Workout, plan: Plan, source: str) -> Json:
    """Return the Home card of a workout."""
    powers = [_watts(plan, s.index) for s in plan.steps]
    return {
        "ref": workout.ref, "source": source, "name": workout.name,
        "duration": _ms(plan.duration), "rideable": True,
        "max_power": max(powers),
        "sketch": [{"duration": _ms(s.duration), "start_power": power,
                    "end_power": power, "zone": zone_of(power, plan.ftp)}
                   for s, power in zip(plan.steps, powers)],
    }


def home_screen(builtin: Sequence[Json]) -> Json:
    """Return the Home screen."""
    return {"name": Screen.HOME, "today": [], "library": [],
            "builtin": list(builtin), "recovery": None}


def pre_ride_screen(plan: Plan, trainer: LinkState) -> Json:
    """Return the Pre-ride screen."""
    ready = trainer == LinkState.CONNECTED
    return {
        "name": Screen.PRE_RIDE, "title": plan.workout.name,
        "free_ride": False,
        "ftp": plan.ftp, "duration": _ms(plan.duration),
        "plan_id": plan.plan_id,
        "block_modes": [Mode.ERG] * len(plan.workout.blocks),
        "can_start": ready,
        "blocked": None if ready else Problem.TRAINER_MISSING,
    }


def plan_message(plan: Plan,
                 zones_pct: Sequence[int] = DEFAULT_ZONES_PCT) -> Json:
    """Return the plan message of a ride."""
    segments = []
    for step in plan.steps:
        power = _watts(plan, step.index)
        segments.append({
            "start": _ms(step.start), "end": _ms(step.end),
            "block": step.block, "step": step.index, "mode": Mode.ERG,
            "kind": Mode.ERG, "start_power": power, "end_power": power,
            "zone": zone_of(power, plan.ftp, zones_pct), "text": step.text})
    blocks = []
    for index, block in enumerate(plan.workout.blocks):
        steps = [{"duration": _ms(step.duration), "kind": Mode.ERG,
                  "start_power": round_half_up(step.target.watts(plan.ftp)),
                  "end_power": round_half_up(step.target.watts(plan.ftp)),
                  "zone": zone_of(step.target.watts(plan.ftp), plan.ftp,
                                  zones_pct)}
                 for step in block.steps]
        blocks.append({
            "index": index, "label": block.label or "",
            "repeats": block.repeats,
            "duration": _ms(sum(s.duration for s in block.steps)
                            * block.repeats),
            "mode": Mode.ERG, "steps": steps})
    return {"type": "plan", "plan_id": plan.plan_id, "segments": segments,
            "blocks": blocks}


def ride_screen(ride: Ride, now: float, power: int | None,
                hr_bpm: int | None) -> Json:
    """Return the ride screen at now."""
    plan = ride.plan
    elapsed = ride.ride_time(now)
    screen: Json = {
        "name": Screen.RIDE,
        "waiting_for_power": ride.phase == RidePhase.ARMED,
        "mode": Mode.ERG, "paused": False,
        "workout_done": ride.phase == RidePhase.WORKOUT_DONE,
        "elapsed": _ms(elapsed), "remaining": None, "step": None,
        "target": None, "target_zone": None, Problem.TARGET_LIMITED: False,
        "power": power, "hr_bpm": hr_bpm, "next": None,
        "intensity_pct": ride.intensity_pct, "resistance_pct": None,
        "free_ride_target": None,
    }
    target = ride.step_target()
    if plan is None or target is None:
        return screen
    step = plan.steps[ride.step]
    screen.update({
        "remaining": _ms(max(0.0, plan.duration - elapsed)),
        "step": {"index": step.index, "count": len(plan.steps),
                 "left": _ms(max(0.0, step.end - elapsed)),
                 "text": step.text},
        "target": target.command.power,
        "target_zone": zone_of(target.command.power, plan.ftp),
        Problem.TARGET_LIMITED: target.limited,
    })
    following = ride.step_target(ride.step + 1)
    if following is not None:
        screen["next"] = {
            "kind": Mode.ERG, "target": following.command.power,
            "zone": zone_of(following.command.power, plan.ftp),
            "duration": _ms(plan.steps[ride.step + 1].duration)}
    return screen


def ride_warnings(ride: Ride, trainer_warnings: Sequence[str]) -> list[Json]:
    """Return the warnings to show during the ride."""
    warnings: list[Json] = [{"kind": k} for k in sorted(trainer_warnings)]
    target = ride.step_target()
    if ride.phase == RidePhase.RUNNING and target and target.limited:
        warnings.append({"kind": Problem.TARGET_LIMITED,
                         "requested_power": target.requested_power,
                         "sent_power": target.command.power})
    return warnings


def view_state(screen: Json, trainer: LinkState, hrm: LinkState,
               battery_pct: int | None, warnings: Sequence[Json],
               data_mono_ms: float | None) -> Json:
    """Return the complete view state."""
    return {"data_mono_ms": data_mono_ms,
            "links": {"trainer": trainer, "hrm": hrm},
            "hrm_battery_pct": battery_pct, "warnings": list(warnings),
            "screen": screen}
