"""Recording from Home to Finish on the stepped clock: journal, samples,
`workout.json`, `meta.json`, `ride.fit` and the Summary (L3)."""

import json
from datetime import UTC, datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from garmin_fit_sdk import Decoder, Stream

from tests.support.app_rig import (
    RecordedProvider, app_config, read_jsonl, ride_dirs, ride_ref,
)
from tests.support.timeline import load_json
from wow.adapters.ble_sim import HRM_ADDRESS
from wow.adapters.clock_stepped import SteppedClock
from wow.app.main import App
from wow.core.workout import Block, PowerTarget, PowerUnit, Step, Workout

THIRTY_THIRTY = "builtin:intervals-30-30"
ZURICH = timezone(timedelta(hours=1))


def fit_messages(ride: Path) -> Any:
    data = bytearray((ride / "ride.fit").read_bytes())
    messages, errors = Decoder(Stream.from_byte_array(data)).read()
    assert errors == []
    return messages


@pytest.mark.case("T-FIT-01")
@pytest.mark.req("APP-601")
@pytest.mark.asyncio
async def test_a_simulated_twenty_minute_ride_decodes(tmp_path: Path) -> None:
    _, ride = await ride_ref(tmp_path, THIRTY_THIRTY, 1200.0)
    messages = fit_messages(ride)
    samples = read_jsonl(ride / "samples.jsonl")
    assert messages["file_id_mesgs"][0]["type"] == "activity"
    session = messages["session_mesgs"][0]
    assert (session["sport"], session["sub_sport"]) == (
        "cycling", "indoor_cycling")
    records = messages["record_mesgs"]
    assert len(records) == len(samples) >= 1190
    assert samples[0]["power"] >= 1
    assert all("power" in r and "heart_rate" in r for r in records[5:])
    erg = [(r, s) for r, s in zip(records, samples) if s["target"]]
    assert len(erg) >= 19 * 60 - 5
    assert all(r["developer_fields"] == {0: s["target"]} for r, s in erg)
    described = messages["field_description_mesgs"][0]
    assert described["field_name"] == "target_power"


@pytest.mark.case("T-REC-01")
@pytest.mark.req("APP-814")
@pytest.mark.asyncio
async def test_every_ride_event_type_so_far_is_journaled(
        tmp_path: Path) -> None:
    clock = SteppedClock()
    too_hard = Workout("test:hard", "Too hard", None, (
        Block(None, 1, (
            Step(60.0, PowerTarget(650, PowerUnit.WATTS), None),
            Step(60.0, PowerTarget(150, PowerUnit.WATTS), None))),))
    app = App(app_config(tmp_path), clock, workouts=[too_hard])
    app.recorder.start()
    try:
        assert app.console.command("open_workout",
                                   {"ref": "test:hard"}) is None
        await clock.advance(15.0)
        assert app.console.command("start", {}) is None
        await clock.advance(30.0)
        assert app.sim is not None
        app.sim.lose_link(HRM_ADDRESS)
        await clock.advance(150.0)
        assert app.console.command("finish", {}) is None
        await clock.advance(5.0)
        await clock.drive(app.devices.close(), limit=60.0)
        await clock.drive(app.rides.close(), limit=60.0)
    finally:
        app.recorder.stop()
    (ride,) = ride_dirs(app.config)
    events = read_jsonl(ride / "events.jsonl")
    kinds = {e["type"] for e in events}
    assert kinds >= {"command", "armed", "trainer_command", "target_limited",
                     "ride_started", "step_started", "dropout_start",
                     "workout_done", "finished"}
    assert all(e["utc"].endswith("Z") and e["mono_ms"] > 0 for e in events)
    lost = next(e for e in events if e["type"] == "dropout_start")
    assert lost["device"] == "hrm" and lost["t_ride"] is not None


@pytest.mark.case("T-REC-02")
@pytest.mark.req("APP-208", "APP-815")
@pytest.mark.asyncio
async def test_workout_json_is_the_download_and_meta_names_the_ride(
        tmp_path: Path) -> None:
    events = load_json("intervals/events.json")
    provider = RecordedProvider(events, load_json("intervals/workouts.json"))
    clock = SteppedClock(utc_start=datetime(2026, 11, 16, 7, 0, tzinfo=UTC))
    app, ride = await ride_ref(tmp_path, "plan:155352328", 60.0, provider,
                               clock, ZURICH)
    planned = next(e for e in events if e["id"] == 155352328)
    assert json.loads((ride / "workout.json").read_bytes()) == planned
    meta = json.loads((ride / "meta.json").read_text(encoding="utf-8"))
    assert (meta["ftp"], meta["zones_pct"]) == (250, [55, 75, 90, 105, 120])
    assert meta["app_version"] and meta["source"] == "plan"
    assert meta["title"] == "Test workout" and meta["state"] == "finished"
    builtin_app, builtin_ride = await ride_ref(tmp_path / "b", THIRTY_THIRTY,
                                               30.0)
    original = resources.files("wow.builtin").joinpath(
        "intervals-30-30.json").read_bytes()
    assert (builtin_ride / "workout.json").read_bytes() == original
    assert builtin_app.recorder.boot_id == json.loads(
        (builtin_ride / "meta.json").read_text())["boot_id"]


@pytest.mark.case("T-REC-04")
@pytest.mark.req("APP-315")
@pytest.mark.asyncio
async def test_finish_writes_the_files_and_shows_the_summary(
        tmp_path: Path) -> None:
    app, ride = await ride_ref(tmp_path, THIRTY_THIRTY, 300.0)
    meta = json.loads((ride / "meta.json").read_text(encoding="utf-8"))
    assert (ride / "ride.fit").stat().st_size > 1000
    assert meta["state"] == "finished" and meta["upload"] == "pending"
    assert meta["files_mono_ms"] >= meta["finished_mono_ms"]
    assert meta["metrics"]["duration"] == len(read_jsonl(
        ride / "samples.jsonl"))
    assert app.console.screen == "summary"


@pytest.mark.case("T-VIEW-06")
@pytest.mark.req("APP-411")
@pytest.mark.asyncio
async def test_the_summary_shows_every_metric_and_the_upload_state(
        tmp_path: Path) -> None:
    app, ride = await ride_ref(tmp_path, THIRTY_THIRTY, 300.0)
    screen = app.console.view()["screen"]
    assert screen["name"] == "summary" and screen["ride_id"] == ride.name
    assert set(screen["metrics"]) == {
        "duration", "avg_power", "max_power", "np", "intensity_factor",
        "tss", "work_kj", "time_in_zone", "avg_hr_bpm", "max_hr_bpm"}
    assert screen["metrics"]["np"] is not None
    assert len(screen["metrics"]["time_in_zone"]) == 6
    assert screen["upload"] == "pending"
    assert screen["title"] == "30/30 and a surge"
