"""Ride controls through the console on the simulated devices (L3)."""

import json
from pathlib import Path
from typing import Any

import pytest
from garmin_fit_sdk import Decoder, Stream

from tests.support.app_rig import (
    AppSession, RecordedProvider, app_config, read_jsonl, ride_dirs,
)
from tests.support.timeline import TESTDATA, load_json
from wow.adapters.clock_stepped import SteppedClock
from wow.app.config import load_settings
from wow.app.main import App
from wow.core.metrics import ride_metrics

TEST_WORKOUT = "library:2"
THIRTY_THIRTY = "builtin:intervals-30-30"
RAMP_TEST = "builtin:ramp-test"
WRITES = TESTDATA / "timelines" / "e2e" / "T-E2E-01.writes.json"


def provider() -> RecordedProvider:
    return RecordedProvider(load_json("intervals/events.json"),
                            load_json("intervals/workouts.json"))


def writes(ride: Path) -> list[list[Any]]:
    events = read_jsonl(ride / "events.jsonl")
    started = next(e["mono_ms"] for e in events
                   if e["type"] == "ride_started")
    return [[round((r["mono_ms"] - started) / 1000, 1), r["hex"]]
            for r in read_jsonl(ride / "ble.jsonl")
            if r["op"] == "write" and r["dev"] == "trainer"]


def journal(ride: Path, kind: str) -> list[dict[str, Any]]:
    return [e for e in read_jsonl(ride / "events.jsonl") if e["type"] == kind]


@pytest.mark.case("T-WKO-10")
@pytest.mark.req("APP-207")
@pytest.mark.asyncio
async def test_a_block_set_to_resistance_on_pre_ride(tmp_path: Path) -> None:
    session = AppSession(tmp_path, provider())
    await session.clock.drive(session.app.catalog.refresh(), limit=60.0)
    assert session.command("open_workout", ref="library:1") is None
    assert session.command("set_block_mode", block=2,
                           mode="resistance") is None
    assert session.command("set_block_mode", block=99, mode="erg") == (
        "bad_request")
    modes = session.app.console.view()["screen"]["block_modes"]
    assert modes[2] == "resistance"
    assert [m for i, m in enumerate(modes) if i != 2] == ["erg"] * (
        len(modes) - 1)
    await session.clock.advance(15.0)
    assert session.command("start") is None
    assert session.command("set_block_mode", block=1,
                           mode="resistance") == "invalid_state"
    await session.until(1500.0)
    assert session.command("finish") is None
    ride = await session.close()
    assert journal(ride, "armed")[0]["block_modes"][2] == "resistance"
    block_two = [s for s in journal(ride, "step_started")
                 if s["kind"] == "erg" and s["mode"] == "resistance"]
    assert block_two and all(s["target"] is None for s in block_two)


@pytest.mark.case("T-TGT-06")
@pytest.mark.req("APP-705")
@pytest.mark.asyncio
async def test_the_free_ride_level_survives_a_restart(tmp_path: Path) -> None:
    session = AppSession(tmp_path)
    await session.begin(None)
    await session.until(10.0)
    for _ in range(7):
        assert session.command("resistance", step=1) is None
    assert session.command("finish") is None
    await session.close()
    assert load_settings(session.app.config.data).free_ride_level_pct == 35
    again = AppSession(tmp_path)
    await again.begin(None)
    await again.until(5.0)
    assert again.app.console.view()["screen"]["resistance_pct"] == 35
    assert again.command("finish") is None
    await again.close()


@pytest.mark.case("T-REC-05")
@pytest.mark.req("APP-316")
@pytest.mark.asyncio
async def test_discard_and_cancel_write_no_fit(tmp_path: Path) -> None:
    session = AppSession(tmp_path)
    await session.begin(THIRTY_THIRTY)
    await session.until(30.0)
    assert session.command("discard") is None
    assert session.app.console.screen == "home"
    await session.clock.advance(5.0)
    assert session.command("open_workout", ref=THIRTY_THIRTY) is None
    await session.clock.advance(5.0)
    assert session.app.d100 is not None
    session.app.d100.pedal_after = 1e9
    session.app.d100.rider_speed_kmh = 0.0
    assert session.command("start") is None
    await session.clock.advance(1.0)
    assert session.command("cancel_start") is None
    await session.close()
    discarded, cancelled = ride_dirs(session.app.config)
    for ride, state in ((discarded, "discarded"), (cancelled, "cancelled")):
        meta = json.loads((ride / "meta.json").read_text())
        assert meta["state"] == state and not (ride / "ride.fit").exists()
        assert (ride / "events.jsonl").exists()
        assert (ride / "ble.jsonl").exists()


@pytest.mark.case("T-E2E-01")
@pytest.mark.req("APP-204", "APP-301", "APP-302", "APP-304", "APP-305",
                 "APP-306", "APP-314", "APP-315")
@pytest.mark.asyncio
async def test_uc01_a_planned_workout_from_start_to_summary(
        tmp_path: Path) -> None:
    session = AppSession(tmp_path, provider())
    await session.begin(TEST_WORKOUT)
    await session.until(960.0)
    assert session.app.console.view()["screen"]["workout_done"] is True
    assert session.command("finish") is None
    summary = session.app.rides.summary
    ride = await session.close()
    actual = writes(ride)
    if not WRITES.exists():
        WRITES.parent.mkdir(parents=True, exist_ok=True)
        WRITES.write_text(json.dumps(actual) + "\n")
    assert actual == json.loads(WRITES.read_text())
    samples = read_jsonl(ride / "samples.jsonl")
    expected = ride_metrics([s["power"] for s in samples],
                            [s["hr_bpm"] for s in samples], 250)
    assert summary is not None and summary.metrics == expected
    data = bytearray((ride / "ride.fit").read_bytes())
    messages, errors = Decoder(Stream.from_byte_array(data)).read()
    assert errors == []
    session_mesg = messages["session_mesgs"][0]
    assert session_mesg["total_timer_time"] == len(samples)
    assert session.app.console.screen == "summary"


@pytest.mark.case("T-E2E-02")
@pytest.mark.req("APP-307", "APP-308", "APP-309", "APP-311", "APP-312",
                 "APP-313")
@pytest.mark.asyncio
async def test_uc02_every_control_of_a_thirty_thirty(tmp_path: Path) -> None:
    session = AppSession(tmp_path)
    await session.begin(THIRTY_THIRTY)
    actions: list[tuple[float | None, str, dict[str, Any]]] = [
        (300.0, "pause", {}), (None, "resume", {}),
        (330.0, "skip", {}), (340.0, "intensity", {"step": 1}),
        (365.0, "switch_mode", {"mode": "resistance"}),
        (370.0, "resistance", {"step": 1}),
        (380.0, "resistance", {"step": 1}),
        (400.0, "switch_mode", {"mode": "erg"})]
    for at, name, args in actions:
        if at is None:
            await session.clock.advance(60.0)
        else:
            await session.until(at)
        assert session.command(name, **args) is None, name
    await session.until(420.0)
    assert session.command("finish") is None
    ride = await session.close()
    records = journal(ride, "command")[1:]
    assert [c["name"] for c in records] == [n for _, n, _ in actions] + [
        "finish"]
    assert all(c["args"].items() >= a.items()
               for c, (_, _, a) in zip(records, actions))
    commands = [(round(c["t_ride"]), c.get("power"), c.get("level_raw"))
                for c in journal(ride, "trainer_command")
                if c["t_ride"] is not None and c["t_ride"] >= 299.5]
    assert commands[0] == (300, None, 0)
    assert commands[1][0] == 300 and commands[1][1] is not None
    assert (365, None, 0) in commands and (370, None, 5) in commands
    assert (380, None, 10) in commands
    assert journal(ride, "paused")[0]["t_ride"] == pytest.approx(300.0)
    assert [s["cause"] for s in journal(ride, "step_started")].count(
        "skip") == 1


@pytest.mark.case("T-E2E-05")
@pytest.mark.req("APP-211", "APP-307")
@pytest.mark.asyncio
async def test_ramp_test_ends_by_resistance_at_step_nine(
        tmp_path: Path) -> None:
    session = AppSession(tmp_path)
    await session.begin(RAMP_TEST)
    await session.until(900.0 + 8 * 60 + 10)
    assert session.app.console.view()["screen"]["step"]["index"] == 11
    assert session.command("switch_mode", mode="resistance") is None
    await session.until(900.0 + 1500.0 + 310.0)
    assert session.app.console.view()["screen"]["workout_done"] is True
    assert session.command("finish") is None
    ride = await session.close()
    after = [c for c in journal(ride, "trainer_command")
             if c["t_ride"] is not None and c["t_ride"] > 900 + 490]
    assert all(c["mode"] == "resistance" for c in after)
    modes = {s["index"]: s["mode"] for s in journal(ride, "step_started")}
    assert {modes[i] for i in range(12, 28)} == {"resistance"}
    assert modes[28] == "resistance"
    assert journal(ride, "workout_done")


@pytest.mark.case("S-SHL-03")
@pytest.mark.asyncio
async def test_the_ride_screen_follows_pause_and_free_ride(
        tmp_path: Path) -> None:
    clock = SteppedClock()
    app = App(app_config(tmp_path), clock)
    app.recorder.start()
    assert app.console.command("open_free_ride", {}) is None
    screen = app.console.view()["screen"]
    assert (screen["free_ride"], screen["duration"]) == (True, None)
    await clock.advance(15.0)
    assert app.console.command("start", {}) is None
    await clock.advance(10.0)
    assert app.console.command("switch_mode", {"mode": "erg"}) is None
    view = app.console.view()["screen"]
    assert view["mode"] == "erg" and view["free_ride_target"] is not None
    assert app.console.command("pause", {}) is None
    assert app.console.view()["screen"]["paused"] is True
    assert app.console.command("intensity", {"step": 2}) == "bad_request"
    assert app.console.command("resume", {}) is None
    assert app.console.command("finish", {}) is None
    await clock.advance(5.0)
    await clock.drive(app.devices.close(), limit=60.0)
    await clock.drive(app.rides.close(), limit=60.0)
    app.recorder.stop()
