"""Build the view state sent to the display.

The domain view state the Pi sends to the display (ICD IF-06, 4.6.3;
AD-18). Values only, no formatting.

Home with planned, library and built-in workouts, Pre-ride with the
routes to choose from, the ride screen while armed, during steps and
after the last one (with the live ride along a route, and the route's
map message), the Summary, the ride history, Calibration and Settings,
and the warnings they carry.
"""

import math
from collections import deque
from collections.abc import Sequence
from fractions import Fraction
from typing import Any, Final

from wow.core.devices import FoundDevice, LinkState
from wow.core.metrics import Metrics
from wow.core.numbers import DEFAULT_ZONES_PCT, exact, round_half_up, zone_of
from wow.core.plan import Plan
from wow.core.ride import Ride, RidePhase
from wow.core.route import Route
from wow.core.settings import DeviceRef, Settings
from wow.core.workout import StepKind, Workout
from wow.core.vocab import Mode, Problem, Screen, WarningKind

AVERAGE_WINDOW: Final[float] = 3.0
DATA_DROPOUT: Final[float] = 3.0
CERT_WARN_DAYS: Final[int] = 30
MAP_POINTS: Final[int] = 400
MAP_SIZE: Final[float] = 1000.0
KMH_PER_MPS: Final[float] = 3.6

Json = dict[str, Any]


class PowerAverage:
    """Mean of the values received in the last 3 s (APP-402)."""

    def __init__(self, window: float = AVERAGE_WINDOW) -> None:
        self._window = window
        self._values: deque[tuple[float, int]] = deque()

    def add(self, mono: float, power: int | None) -> None:
        """Add a reading taken at mono; older ones leave the window."""
        if power is not None:
            self._values.append((mono, power))
        self._forget(mono)

    def value(self, now: float) -> int | None:
        """Return the mean at now, or None without readings."""
        self._forget(now)
        if not self._values:
            return None
        total = sum(power for _, power in self._values)
        return round_half_up(total / len(self._values))

    def _forget(self, now: float) -> None:
        while self._values and self._values[0][0] <= now - self._window:
            self._values.popleft()


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
                 ref: str, name: str,
                 zones_pct: Sequence[int] = DEFAULT_ZONES_PCT) -> Json:
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
            "zone": _zone(start, plan.ftp, zones_pct) or 0})
    peaks = [max(s["start_power"], s["end_power"]) for s in sketch]
    return {
        "ref": ref, "source": source, "name": name,
        "duration": _ms(plan.duration), "rideable": True,
        "max_power": max(peaks), "sketch": sketch,
    }


def home_screen(builtin: Sequence[Json], today: Sequence[Json] = (),
                library: Sequence[Json] = (),
                recovery: Json | None = None) -> Json:
    """Return the Home screen."""
    return {"name": Screen.HOME, "today": list(today),
            "library": list(library), "builtin": list(builtin),
            "recovery": recovery}


def recovery_offer(ride_id: str, started_utc: str | None,
                   outage: float | None) -> Json:
    """Return the Home offer of a ride the app stopped in (APP-809)."""
    return {"ride_id": ride_id, "started_utc": started_utc,
            "outage": None if outage is None else _ms(outage),
            "can_continue": outage is not None}


def route_option(file: str, name: str, length_m: float,
                 ascent_m: float) -> Json:
    """Return a route the rider can choose (APP-901)."""
    return {"file": file, "name": name,
            "length_m": round_half_up(exact(length_m)),
            "ascent_m": round_half_up(exact(ascent_m))}


def pre_ride_screen(plan: Plan, trainer: LinkState,
                    block_modes: Sequence[Mode] = (),
                    free: bool = False, routes: Sequence[Json] = (),
                    route: str | None = None) -> Json:
    """Return the Pre-ride screen; route is the chosen route's file."""
    ready = trainer == LinkState.CONNECTED
    modes = list(block_modes) or [Mode.ERG] * len(plan.workout.blocks)
    return {
        "name": Screen.PRE_RIDE, "title": plan.workout.name,
        "free_ride": free, "ftp": plan.ftp,
        "duration": None if free else _ms(plan.duration),
        "plan_id": None if free else plan.plan_id,
        "block_modes": [] if free else modes,
        "routes": list(routes), "route": route,
        "can_start": ready,
        "blocked": None if ready else Problem.TRAINER_MISSING,
    }


def plan_message(plan: Plan,
                 zones_pct: Sequence[int] = DEFAULT_ZONES_PCT,
                 intensity_pct: int = 100) -> Json:
    """Return the plan message of a ride; segments at the intensity."""
    def scaled(power: Fraction | None) -> int | None:
        return None if power is None else round_half_up(
            exact(power) * intensity_pct / 100)

    segments = []
    for step in plan.steps:
        start, end = scaled(step.power), scaled(step.end_power)
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
    plan_id = (plan.plan_id if intensity_pct == 100
               else f"{plan.plan_id}@{intensity_pct}%")
    return {"type": "plan", "plan_id": plan_id, "segments": segments,
            "blocks": blocks}


def ride_screen(ride: Ride, now: float, power: int | None,
                hr_bpm: int | None,
                zones_pct: Sequence[int] = DEFAULT_ZONES_PCT,
                cadence_rpm: int | None = None,
                route: Json | None = None) -> Json:
    """Return the ride screen at now.

    Cadence comes only with a source, the live ride along the route
    only on a route.
    """
    plan = ride.plan
    remaining = ride.remaining(now)
    screen: Json = {
        "name": Screen.RIDE,
        "waiting_for_power": ride.phase == RidePhase.ARMED,
        "mode": ride.shown_mode, "paused": ride.phase == RidePhase.PAUSED,
        "workout_done": ride.phase == RidePhase.WORKOUT_DONE,
        "elapsed": _ms(ride.ride_time(now)),
        "remaining": None if remaining is None else _ms(remaining),
        "step": None, "target": None, "target_zone": None,
        Problem.TARGET_LIMITED: False, "power": power, "hr_bpm": hr_bpm,
        "next": None, "intensity_pct": ride.intensity_pct,
        "resistance_pct": ride.resistance_pct,
        "free_ride_target": ride.free_ride_target,
        "resistance_blocks": list(ride.resistance_blocks),
        "cadence_rpm": cadence_rpm, "route": route,
    }
    if plan is None:
        return screen
    if ride.free:
        target_power = ride.free_ride_target
        screen.update({"target": target_power, "target_zone": _zone(
            target_power, plan.ftp, zones_pct)})
        return screen
    target = ride.current_target(now)
    left = ride.step_left(now)
    if target is None or left is None:
        return screen
    step = plan.steps[ride.step]
    screen.update({
        "step": {"index": step.index, "count": len(plan.steps),
                 "left": _ms(left), "text": step.text},
        "target": target.power,
        "target_zone": _zone(target.power, plan.ftp, zones_pct),
        Problem.TARGET_LIMITED: target.limited,
    })
    following = ride.step_target(ride.step + 1)
    if following is not None:
        planned = plan.steps[ride.step + 1]
        screen["next"] = {
            "kind": (StepKind.ERG if planned.kind == StepKind.ERG
                     else StepKind.FREE_RIDE),
            "target": following.power,
            "zone": _zone(following.power, plan.ftp, zones_pct),
            "duration": _ms(planned.duration)}
    return screen


def ridden_route(name: str, distance_m: float | None,
                 ascent_m: float | None) -> Json:
    """Return a ride's route; no distance while it is being worked out."""
    def whole(value: float | None) -> int | None:
        return None if value is None else round_half_up(exact(value))

    return {"name": name, "distance_m": whole(distance_m),
            "ascent_m": whole(ascent_m)}


def route_map(route_id: str, name: str, route: Route) -> Json:
    """Return the route message: its shape and its elevation (APP-909).

    Each point is [distance m, x, y, elevation m]; x and y are a flat
    projection with north up, scaled so the larger side is 1000.
    """
    step = max(1, math.ceil(len(route.stations) / MAP_POINTS))
    picks = list(range(0, len(route.stations), step))
    if picks[-1] != len(route.stations) - 1:
        picks.append(len(route.stations) - 1)
    across = math.cos(math.radians(sum(route.lat) / len(route.lat)))
    xs = [route.lon[i] * across for i in picks]
    ys = [-route.lat[i] for i in picks]
    left, top = min(xs), min(ys)
    scale = MAP_SIZE / max(max(xs) - left, max(ys) - top, 1e-12)
    points = [[round(route.stations[i], 1), round((x - left) * scale, 1),
               round((y - top) * scale, 1), round(route.ele[i], 1)]
              for i, x, y in zip(picks, xs, ys)]
    return {"type": "route", "route_id": route_id, "name": name,
            "length_m": round(route.length_m, 1),
            "width": round((max(xs) - left) * scale, 1),
            "height": round((max(ys) - top) * scale, 1),
            "ele_min": round(min(route.ele), 1),
            "ele_max": round(max(route.ele), 1), "points": points}


def route_live(route_id: str, route: Route, distance_m: float,
               speed_mps: float, paused: bool) -> Json:
    """Return the ride along the route at this second (APP-909)."""
    at = distance_m % route.length_m
    return {"route_id": route_id,
            "speed_kmh": 0.0 if paused else round(speed_mps * KMH_PER_MPS, 1),
            "grade_pct": round(route.grade_at(at) * 100, 1),
            "altitude_m": round_half_up(exact(route.ele_at(at))),
            "distance_m": round_half_up(exact(distance_m)),
            "at_m": round(at, 1)}


def summary_screen(ride_id: str, title: str, start_utc: str,
                   metrics: Metrics, upload: str, past: bool = False,
                   route: Json | None = None,
                   garmin_upload: str | None = None) -> Json:
    """Return the Summary of a ride just finished, or a past one.

    The Garmin Connect upload state is None while Garmin isn't set up
    and the ride was never sent there.
    """
    return {"name": Screen.SUMMARY, "ride_id": ride_id, "title": title,
            "start_utc": start_utc, "metrics": metrics_view(metrics),
            "upload": upload, "garmin_upload": garmin_upload, "past": past,
            "route": route}


def calibration_screen(phase: str, band_kmh: tuple[float, float] | None,
                       speed_kmh: float | None, elapsed: float,
                       last: tuple[str, bool] | None,
                       blocked: str | None) -> Json:
    """Return the Calibration screen (APP-502 to APP-505)."""
    return {"name": Screen.CALIBRATION, "phase": phase,
            "band_kmh": None if band_kmh is None else list(band_kmh),
            "speed_kmh": None if speed_kmh is None else round(speed_kmh, 1),
            "elapsed": _ms(elapsed),
            "last": None if last is None else {
                "utc": last[0], "ok": last[1]},
            "blocked": blocked}


def history_screen(rides: Sequence[Json], free_mb: int) -> Json:
    """Return the ride history (APP-611)."""
    return {"name": Screen.HISTORY, "rides": list(rides), "free_mb": free_mb}


def history_entry(ride_id: str, start_utc: str | None, title: str,
                  metrics: Metrics | None, upload: str,
                  garmin_upload: str | None = None) -> Json:
    """Return one past ride in the history."""
    return {"ride_id": ride_id, "start_utc": start_utc, "title": title,
            "duration": None if metrics is None else metrics.duration,
            "tss": None if metrics is None or metrics.tss is None
            else round(metrics.tss, 1), "upload": upload,
            "garmin_upload": garmin_upload}


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


def ride_warnings(ride: Ride, trainer_warnings: Sequence[str],
                  extra: Sequence[Json] = ()) -> list[Json]:
    """Return the warnings to show during the ride."""
    warnings: list[Json] = [{"kind": k} for k in sorted(trainer_warnings)]
    target = ride.step_target()
    if ride.phase == RidePhase.RUNNING and target and target.limited:
        warnings.append({"kind": Problem.TARGET_LIMITED,
                         "requested_power": target.requested_power,
                         "sent_power": target.power})
    return warnings + list(extra)


def battery_warning(battery_pct: int | None,
                    threshold_pct: int) -> list[Json]:
    """Return the strap's low-battery warning, if due (APP-112)."""
    if battery_pct is None or battery_pct > threshold_pct:
        return []
    return [{"kind": WarningKind.HRM_BATTERY_LOW,
             "battery_pct": battery_pct}]


def clock_warning(synchronised: bool) -> list[Json]:
    """Return the warning for a clock not synchronised (APP-824)."""
    return [] if synchronised else [{"kind": WarningKind.CLOCK_UNSYNCED}]


def certificate_warning(days_left: int | None) -> list[Json]:
    """Return the warning for a certificate ending soon (APP-830)."""
    if days_left is None or days_left > CERT_WARN_DAYS:
        return []
    return [{"kind": WarningKind.CERT_EXPIRING,
             "days_left": max(0, days_left)}]


def _device(ref: DeviceRef | None) -> Json | None:
    return None if ref is None else {"address": ref.address,
                                     "name": ref.name}


def settings_screen(settings: Settings, account_set: bool,
                    cert_valid_until: str | None,
                    scan: tuple[str, bool, Sequence[FoundDevice]] | None,
                    garmin_signed_in: bool = False) -> Json:
    """Return the Settings screen; scan is the kind, running and found."""
    return {
        "name": Screen.SETTINGS, "ftp": settings.ftp,
        "zones_pct": list(settings.zones_pct),
        "lead_time": settings.lead_time,
        "battery_warn_pct": settings.battery_warn_pct,
        "rider_kg": settings.rider_kg,
        "upload_on": settings.upload_on,
        "intervals_account_set": account_set,
        "garmin_upload_on": settings.garmin_upload_on,
        "garmin_signed_in": garmin_signed_in,
        "cert_valid_until": cert_valid_until,
        "trainer": _device(settings.trainer), "hrm": _device(settings.hrm),
        "scan": None if scan is None else {
            "kind": scan[0], "running": scan[1],
            "found": [{"address": f.address, "name": f.name,
                       "rssi_dbm": f.rssi_dbm, "kind": f.kind}
                      for f in scan[2]]},
    }


def view_state(screen: Json, trainer: LinkState, hrm: LinkState,
               battery_pct: int | None, warnings: Sequence[Json],
               data_mono_ms: float | None) -> Json:
    """Return the complete view state."""
    return {"data_mono_ms": data_mono_ms,
            "links": {"trainer": trainer, "hrm": hrm},
            "hrm_battery_pct": battery_pct, "warnings": list(warnings),
            "screen": screen}
