"""Build the view state sent to the display.

The domain view state the Pi sends to the display (ICD IF-06, 4.6.3;
AD-18). Values only, no formatting.

Home with planned, library and built-in workouts, Pre-ride, the ride
screen while armed, during steps and after the last one, and the
Summary.
"""

from collections import deque
from collections.abc import Sequence
from fractions import Fraction
from typing import Any, Final

from wow.core.devices import LinkState
from wow.core.metrics import Metrics
from wow.core.numbers import DEFAULT_ZONES_PCT, exact, round_half_up, zone_of
from wow.core.plan import Plan
from wow.core.ride import Ride, RidePhase
from wow.core.workout import StepKind, Workout
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


def _watts(power: Fraction | None) -> int | None:
    return None if power is None else round_half_up(power)


def _ms(value: float) -> float:
    return round(value, 3)


def _zone(power: int | None, ftp: int, zones_pct: Sequence[int]
          ) -> int | None:
    return None if power is None else zone_of(power, ftp, zones_pct)


def _mode(kind: StepKind) -> Mode:
    return Mode.ERG if kind == StepKind.ERG else Mode.RESISTANCE


def workout_card(workout: Workout | None, plan: Plan | None, source: str,
                 ref: str, name: str) -> Json:
    """Return the Home card of a workout; None for one not rideable."""
    if workout is None or plan is None:
        return {"ref": ref, "source": source, "name": name,
                "duration": None, "rideable": False, "max_power": None,
                "sketch": None}
    sketch = []
    for step in plan.steps:
        start, end = _watts(step.power), _watts(step.end_power)
        sketch.append({
            "duration": _ms(step.duration), "start_power": start or 0,
            "end_power": end if end is not None else start or 0,
            "zone": _zone(start, plan.ftp, DEFAULT_ZONES_PCT) or 0})
    peaks = [max(s["start_power"], s["end_power"]) for s in sketch]
    return {
        "ref": ref, "source": source, "name": name,
        "duration": _ms(plan.duration), "rideable": True,
        "max_power": max(peaks), "sketch": sketch,
    }


def home_screen(builtin: Sequence[Json], today: Sequence[Json] = (),
                library: Sequence[Json] = ()) -> Json:
    """Return the Home screen."""
    return {"name": Screen.HOME, "today": list(today),
            "library": list(library), "builtin": list(builtin),
            "recovery": None}


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
        start, end = _watts(step.power), _watts(step.end_power)
        segments.append({
            "start": _ms(step.start), "end": _ms(step.end),
            "block": step.block, "step": step.index,
            "mode": _mode(step.kind), "kind": step.kind,
            "start_power": start,
            "end_power": end if end is not None else start,
            "zone": _zone(start, plan.ftp, zones_pct), "text": step.text})
    blocks = []
    for index, block in enumerate(plan.workout.blocks):
        steps = []
        for item in block.steps:
            start = _watts(None if item.target is None
                           else item.target.watts(plan.ftp))
            end = _watts(None if item.end is None
                         else item.end.watts(plan.ftp))
            kind = (item.kind if item.target is not None or
                    item.kind != StepKind.ERG else StepKind.UNSUPPORTED)
            steps.append({
                "duration": _ms(item.duration), "kind": kind,
                "start_power": start,
                "end_power": end if end is not None else start,
                "zone": _zone(start, plan.ftp, zones_pct)})
        blocks.append({
            "index": index, "label": block.label or "",
            "repeats": block.repeats, "duration": _ms(block.duration),
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
    target = ride.current_target(now)
    if plan is None or target is None:
        return screen
    step = plan.steps[ride.step]
    screen.update({
        "mode": _mode(step.kind),
        "remaining": _ms(max(0.0, plan.duration - elapsed)),
        "step": {"index": step.index, "count": len(plan.steps),
                 "left": _ms(max(0.0, step.end - elapsed)),
                 "text": step.text},
        "target": target.power,
        "target_zone": _zone(target.power, plan.ftp, DEFAULT_ZONES_PCT),
        Problem.TARGET_LIMITED: target.limited,
    })
    following = ride.step_target(ride.step + 1)
    if following is not None:
        kind = plan.steps[ride.step + 1].kind
        screen["next"] = {
            "kind": (StepKind.ERG if kind == StepKind.ERG
                     else StepKind.FREE_RIDE),
            "target": following.power,
            "zone": _zone(following.power, plan.ftp, DEFAULT_ZONES_PCT),
            "duration": _ms(plan.steps[ride.step + 1].duration)}
    return screen


def summary_screen(ride_id: str, title: str, start_utc: str,
                   metrics: Metrics, upload: str) -> Json:
    """Return the Summary screen of a finished ride."""
    return {"name": Screen.SUMMARY, "ride_id": ride_id, "title": title,
            "start_utc": start_utc, "metrics": metrics_view(metrics),
            "upload": upload}


def metrics_view(metrics: Metrics) -> Json:
    """Return the metrics as the display shows them."""
    def whole(value: float | None) -> int | None:
        return None if value is None else round_half_up(exact(value))

    def fine(value: float | None) -> float | None:
        return None if value is None else round(value, 3)

    return {
        "duration": metrics.duration,
        "avg_power": whole(metrics.avg_power),
        "max_power": metrics.max_power, "np": whole(metrics.np),
        "intensity_factor": fine(metrics.intensity_factor),
        "tss": fine(metrics.tss), "work_kj": fine(metrics.work_kj),
        "time_in_zone": list(metrics.time_in_zone),
        "avg_hr_bpm": whole(metrics.avg_hr_bpm),
        "max_hr_bpm": metrics.max_hr_bpm,
    }


def ride_warnings(ride: Ride, trainer_warnings: Sequence[str]) -> list[Json]:
    """Return the warnings to show during the ride."""
    warnings: list[Json] = [{"kind": k} for k in sorted(trainer_warnings)]
    target = ride.step_target()
    if ride.phase == RidePhase.RUNNING and target and target.limited:
        warnings.append({"kind": Problem.TARGET_LIMITED,
                         "requested_power": target.requested_power,
                         "sent_power": target.power})
    return warnings


def view_state(screen: Json, trainer: LinkState, hrm: LinkState,
               battery_pct: int | None, warnings: Sequence[Json],
               data_mono_ms: float | None) -> Json:
    """Return the complete view state."""
    return {"data_mono_ms": data_mono_ms,
            "links": {"trainer": trainer, "hrm": hrm},
            "hrm_battery_pct": battery_pct, "warnings": list(warnings),
            "screen": screen}
