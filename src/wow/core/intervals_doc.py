"""Parse workout documents into workouts.

Turns an intervals.icu `workout_doc`, or a built-in workout file in the
same structure, into a Workout (ICD IF-13; 3A, core/intervals_doc;
APP-204 to APP-206, APP-209, APP-211). Ranges ride at their midpoint,
zones at the middle of the workout's `zoneTimes`, ramps keep both ends;
any other target is marked unsupported.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

from wow.core.workout import Block, PowerTarget, PowerUnit, Step, StepKind
from wow.core.workout import Workout

NO_UPPER_BOUND: Final[float] = 999.0
REPEAT_MARK: Final[re.Pattern[str]] = re.compile(r"\s*\b\d+\s*x\s*$")

Doc = Mapping[str, Any]


class WorkoutError(ValueError):
    """The workout document cannot be used."""


def parse_builtin(form: Doc) -> Workout:
    """Parse a built-in workout file."""
    if form.get("schema") != 1:
        raise WorkoutError(f"unknown schema {form.get('schema')!r}")
    return parse_workout(f"builtin:{form['id']}", form["name"],
                         form.get("description"), form["workout_doc"])


def parse_workout(
    ref: str, name: str, description: str | None, doc: Doc
) -> Workout:
    """Parse an intervals.icu workout document."""
    items = doc.get("steps")
    if not isinstance(items, Sequence) or not items:
        raise WorkoutError(f"{name}: no steps")
    zones = _zone_bounds(doc.get("zoneTimes"))
    return Workout(ref, name, description,
                   tuple(_block(name, item, zones) for item in items))


def block_label(text: object) -> str | None:
    """Return a repeat block's label without its repeat count."""
    if not isinstance(text, str):
        return None
    lines = [REPEAT_MARK.sub("", line).strip() for line in text.splitlines()]
    label = " – ".join(line for line in lines if line)
    return label or None


def _zone_bounds(zone_times: object) -> dict[int, tuple[float, float]]:
    if not isinstance(zone_times, Sequence):
        return {}
    zones = sorted((int(z["zone"]), float(z["max"])) for z in zone_times
                   if isinstance(z, Mapping) and not z.get("gap")
                   and isinstance(z.get("zone"), int)
                   and isinstance(z.get("max"), (int, float)))
    bounds, lower = {}, 0.0
    for zone, upper in zones:
        bounds[zone] = (lower, upper)
        lower = upper
    return bounds


def _block(name: str, item: Any, zones: Mapping[int, tuple[float, float]]
           ) -> Block:
    if not isinstance(item, Mapping):
        raise WorkoutError(f"{name}: step is not an object: {item!r}")
    if "reps" not in item:
        return Block(None, 1, (_step(name, item, zones),))
    repeats = item["reps"]
    inner = item.get("steps")
    if not isinstance(repeats, int) or repeats < 1 or not inner:
        raise WorkoutError(f"{name}: bad repeat block {dict(item)!r}")
    return Block(block_label(item.get("text")), repeats,
                 tuple(_step(name, step, zones) for step in inner))


def _step(name: str, item: Any,
          zones: Mapping[int, tuple[float, float]]) -> Step:
    if not isinstance(item, Mapping):
        raise WorkoutError(f"{name}: step is not an object: {item!r}")
    duration = item.get("duration")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise WorkoutError(f"{name}: step without a duration: {dict(item)!r}")
    text = _cue(item)
    if item.get("freeride"):
        return Step(float(duration), None, text, kind=StepKind.FREE_RIDE)
    power = item.get("power")
    targets = _targets(power, zones) if isinstance(power, Mapping) else None
    if targets is None:
        return Step(float(duration), None, text, kind=StepKind.UNSUPPORTED)
    start, end = targets
    if item.get("ramp") and end is not None:
        return Step(float(duration), start, text, end=end)
    if end is not None:
        start = _midpoint(start, end)
    return Step(float(duration), start, text)


def _cue(item: Mapping[str, Any]) -> str | None:
    text = item.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    if item.get("warmup"):
        return "Warm-up"
    if item.get("cooldown"):
        return "Cool-down"
    return None


def _targets(power: Mapping[str, Any],
             zones: Mapping[int, tuple[float, float]]
             ) -> tuple[PowerTarget, PowerTarget | None] | None:
    units = power.get("units")
    if units == "power_zone":
        return _zone_target(power.get("value"), zones)
    if units not in set(PowerUnit):
        return None
    unit = PowerUnit(units)
    value, start, end = (_number(power.get(k))
                         for k in ("value", "start", "end"))
    if value is not None:
        return PowerTarget(value, unit), None
    if start is not None and end is not None:
        return PowerTarget(start, unit), PowerTarget(end, unit)
    return None


def _zone_target(zone: object, zones: Mapping[int, tuple[float, float]]
                 ) -> tuple[PowerTarget, None] | None:
    if not isinstance(zone, int) or zone not in zones:
        return None
    lower, upper = zones[zone]
    if upper >= NO_UPPER_BOUND:
        return None
    return PowerTarget((lower + upper) / 2, PowerUnit.PERCENT_FTP), None


def _midpoint(start: PowerTarget, end: PowerTarget) -> PowerTarget:
    return PowerTarget((start.value + end.value) / 2, start.units)


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None
