"""Replay a kept ride through the whole app (L4, T-LOG-05).

The app runs on a stepped clock set to the ride's own monotonic times,
with `ReplayConnector` in place of Bluetooth, the ride's settings and
workout, and the rider's commands from the journal at their times. The
replay connector compares every write with the recorded one.
"""

import json
from pathlib import Path
from typing import Any

from tests.support.app_rig import app_config, read_jsonl
from wow.adapters.ble_replay import ReplayConnector
from wow.adapters.clock_stepped import SteppedClock
from wow.app.main import App
from wow.core.intervals_doc import parse_workout
from wow.core.workout import Workout

LEAD_IN = 5.0
COMMANDS = ("pause", "resume", "skip", "intensity", "resistance",
            "switch_mode", "free_ride_power", "finish", "discard",
            "cancel_start")


def kept_workout(case: Path, ref: str) -> Workout | None:
    path = case / "workout.json"
    if not path.exists():
        return None
    form = json.loads(path.read_text(encoding="utf-8"))
    return parse_workout(ref, str(form["name"]), None, form["workout_doc"])


def settings_of(armed: dict[str, Any],
                lines: list[dict[str, Any]]) -> dict[str, Any]:
    def device(role: str) -> dict[str, Any] | None:
        addresses = [r["addr"] for r in lines
                     if r.get("dev") == role and r.get("op") == "connected"]
        return {"address": addresses[0].upper(), "name": None} if (
            addresses) else None

    return {"schema": 1, "ftp": armed["ftp"], "lead_time": armed["lead_time"],
            "free_ride_level_pct": armed.get("free_ride_level_pct", 0),
            "trainer": device("trainer"), "hrm": device("hrm")}


async def replay(case: Path, tmp: Path) -> tuple[list[str], App]:
    """Replay a kept ride; return the write mismatches and the app.

    The release at shutdown comes after the ride's log ends, so it is
    left out of the comparison.
    """
    events = read_jsonl(case / "events.jsonl")
    lines = read_jsonl(case / "ble.jsonl")
    (armed,) = [e for e in events if e["type"] == "armed"]
    first = min(float(r["mono_ms"]) for r in lines) / 1000
    config = app_config(tmp)
    config.data.mkdir(parents=True, exist_ok=True)
    (config.data / "settings.json").write_text(
        json.dumps(settings_of(armed, lines)), encoding="utf-8")
    clock = SteppedClock(start=first - LEAD_IN)
    connector = ReplayConnector(clock, lines)
    ref = str(armed["workout_ref"])
    workout = kept_workout(case, ref)
    app = App(config, clock, replay=connector,
              workouts=[] if workout is None else [workout])
    app.recorder.start()
    try:
        opened = (app.console.command("open_free_ride", {}) if workout is None
                  else app.console.command("open_workout", {"ref": ref}))
        assert opened is None, opened
        for block, mode in enumerate(armed.get("block_modes", [])):
            if mode != "erg":
                app.console.command("set_block_mode",
                                    {"block": block, "mode": mode})
        await clock.run_until(float(armed["mono_ms"]) / 1000)
        assert app.console.command("start", {}) is None
        for event in events:
            name = event.get("name")
            if event["type"] != "command" or name not in COMMANDS:
                continue
            await clock.run_until(float(event["mono_ms"]) / 1000)
            app.console.command(str(name), event.get("args") or {})
        await clock.advance(5.0)
        found = list(connector.mismatches)
        await clock.drive(app.devices.close(), limit=60.0)
        await clock.drive(app.rides.close(), limit=60.0)
    finally:
        app.recorder.stop()
    return found, app
