"""The app shell on the stepped clock: console, ride controller, recorder
and the simulated D100 from Home to Finish (L3)."""

from pathlib import Path

import pytest

from tests.support.app_rig import (
    ERG_CHECK, app_config, read_jsonl, ride_dirs, ride_erg_check,
)
from wow.adapters.clock_stepped import SteppedClock
from wow.app.main import App
from wow.core import uuids


@pytest.mark.case("S-SHL-01")
@pytest.mark.asyncio
async def test_a_short_ride_from_home_to_finish(tmp_path: Path) -> None:
    app, ride = await ride_erg_check(tmp_path)
    events = read_jsonl(ride / "events.jsonl")
    kinds = [e["type"] for e in events]
    assert kinds[:3] == ["command", "armed", "trainer_command"]
    assert kinds.count("step_started") == 6
    assert "workout_done" in kinds and kinds[-2:] == ["finished",
                                                      "trainer_command"]
    started = next(e for e in events if e["type"] == "ride_started")
    armed = next(e for e in events if e["type"] == "armed")
    assert started["mono_ms"] - armed["mono_ms"] >= 3000.0
    assert {e["boot_id"] for e in events} == {app.recorder.boot_id}
    assert app.console.screen == "home"


@pytest.mark.case("S-SHL-01")
@pytest.mark.asyncio
async def test_the_ride_log_holds_the_rides_writes(tmp_path: Path) -> None:
    app, ride = await ride_erg_check(tmp_path)
    writes = [r["hex"] for r in read_jsonl(ride / "ble.jsonl")
              if r["op"] == "write"
              and r["uuid"] == uuids.FITNESS_MACHINE_CONTROL_POINT]
    assert writes[0] == "057800"
    assert writes[-1] == "0400"
    system = read_jsonl(app.config.data / "logs" / "ble-system.jsonl")
    assert [r["hex"] for r in system if r["op"] == "write"][:2] == [
        "00", "07"]


@pytest.mark.case("T-RID-04")
@pytest.mark.req("APP-117")
@pytest.mark.asyncio
async def test_start_without_the_trainer_makes_no_ride_directory(
        tmp_path: Path) -> None:
    clock = SteppedClock()
    app = App(app_config(tmp_path), clock)
    app.recorder.start()
    try:
        assert app.console.command("open_workout", {"ref": ERG_CHECK}) is None
        assert app.console.view()["screen"]["blocked"] == "trainer_missing"
        assert app.console.command("start", {}) == "invalid_state"
        assert app.console.screen == "pre_ride"
    finally:
        await clock.drive(app.devices.close(), limit=60.0)
        if app.scheduler is not None:
            await app.scheduler.close()
        app.recorder.stop()
    assert ride_dirs(app.config) == []


@pytest.mark.case("S-SHL-02")
@pytest.mark.asyncio
async def test_console_routes_commands_by_screen(tmp_path: Path) -> None:
    clock = SteppedClock()
    app = App(app_config(tmp_path), clock)
    console = app.console
    app.recorder.start()
    try:
        assert console.command("warp", {}) == "bad_request"
        assert console.command("start", {}) == "invalid_state"
        assert console.command("open_workout", {"ref": "nope"}) == (
            "bad_request")
        assert console.plan() is None
        assert console.command("open_workout", {"ref": ERG_CHECK}) is None
        assert console.plan() is not None
        assert console.command("back", {}) is None
        assert console.screen == "home" and console.plan() is None
        assert console.command("open_workout", {"ref": ERG_CHECK}) is None
        await clock.advance(15.0)
        assert console.command("start", {}) is None
        view = console.view()
        assert view["screen"]["waiting_for_power"] is True
        assert console.command("finish", {}) == "invalid_state"
        assert console.command("cancel_start", {}) is None
        assert console.screen == "pre_ride"
        assert console.command("cancel_start", {}) == "invalid_state"
    finally:
        await clock.advance(5.0)
        await clock.drive(app.devices.close(), limit=60.0)
        await clock.drive(app.rides.close(), limit=60.0)
        if app.scheduler is not None:
            await app.scheduler.close()
        app.recorder.stop()
    (ride,) = ride_dirs(app.config)
    kinds = [e["type"] for e in read_jsonl(ride / "events.jsonl")]
    assert kinds[-3:] == ["command", "cancelled", "trainer_command"]


@pytest.mark.case("S-SHL-02")
@pytest.mark.asyncio
async def test_ride_view_carries_power_and_heart_rate(tmp_path: Path) -> None:
    clock = SteppedClock()
    app = App(app_config(tmp_path), clock)
    app.recorder.start()
    try:
        app.console.command("open_workout", {"ref": ERG_CHECK})
        await clock.advance(15.0)
        app.console.command("start", {})
        await clock.advance(30.0)
        view = app.console.view()
        screen = view["screen"]
        assert screen["waiting_for_power"] is False
        assert screen["target"] == 120 and screen["power"] is not None
        assert abs(screen["power"] - 120) <= 3
        assert screen["hr_bpm"] is not None
        assert view["data_mono_ms"] is not None
        assert view["links"] == {"trainer": "connected", "hrm": "connected"}
    finally:
        app.console.command("finish", {})
        await clock.advance(5.0)
        await clock.drive(app.devices.close(), limit=60.0)
        await clock.drive(app.rides.close(), limit=60.0)
        if app.scheduler is not None:
            await app.scheduler.close()
        app.recorder.stop()
