"""Parse workout documents into workouts.

Turns an intervals.icu `workout_doc`, or a built-in workout file in the
same structure, into a Workout (ICD IF-13; 3A, core/intervals_doc).

Slice SL-02 reads steps with one power value in `w` or `%ftp`, and repeat
blocks; anything else is refused by name until SL-04 adds it (A-55).
"""

from collections.abc import Mapping, Sequence
from typing import Any

from wow.core.workout import Block, PowerTarget, PowerUnit, Step, Workout


class WorkoutError(ValueError):
    """The workout document cannot be used."""

    pass


def parse_builtin(form: Mapping[str, Any]) -> Workout:
    """Parse a built-in workout file."""
    if form.get("schema") != 1:
        raise WorkoutError(f"unknown schema {form.get('schema')!r}")
    return parse_workout(f"builtin:{form['id']}", form["name"],
                         form.get("description"), form["workout_doc"])


def parse_workout(
    ref: str, name: str, description: str | None, doc: Mapping[str, Any]
) -> Workout:
    """Parse an intervals.icu workout document."""
    items = doc.get("steps")
    if not isinstance(items, Sequence) or not items:
        raise WorkoutError(f"{name}: no steps")
    return Workout(ref, name, description,
                   tuple(_block(name, item) for item in items))


def _block(name: str, item: Mapping[str, Any]) -> Block:
    if "reps" not in item:
        return Block(None, 1, (_step(name, item),))
    repeats = item["reps"]
    inner = item.get("steps")
    if not isinstance(repeats, int) or repeats < 1 or not inner:
        raise WorkoutError(f"{name}: bad repeat block {dict(item)!r}")
    return Block(item.get("text"), repeats,
                 tuple(_step(name, step) for step in inner))


def _step(name: str, item: Mapping[str, Any]) -> Step:
    if not isinstance(item, Mapping):
        raise WorkoutError(f"{name}: step is not an object: {item!r}")
    duration = item.get("duration")
    power = item.get("power")
    plain = (isinstance(power, Mapping)
             and power.get("units") in set(PowerUnit)
             and isinstance(power.get("value"), (int, float))
             and not item.get("ramp") and not item.get("freeride"))
    if not plain or not isinstance(power, Mapping):
        raise WorkoutError(f"{name}: step not supported before SL-04: "
                           f"{dict(item)!r}")
    if not isinstance(duration, (int, float)) or duration <= 0:
        raise WorkoutError(f"{name}: step without a duration: {dict(item)!r}")
    return Step(float(duration), PowerTarget(float(power["value"]),
                                             PowerUnit(power["units"])),
                item.get("text"))
