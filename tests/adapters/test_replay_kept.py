"""Replays of kept rides (L4): T-LOG-05 over the real rides in
testdata/rides/, and the same path over a simulated ride (S-LOG-01).

Keep a real ride with tools/keep_ride.py, then on the Pi or laptop:

    uv run pytest -m pi tests/adapters/test_replay_kept.py
"""

import json
from pathlib import Path

import pytest

from tests.support.app_rig import AppSession, read_jsonl, ride_dirs
from tests.support.replay_ride import replay
from tests.support.timeline import TESTDATA
from tools import keep_ride
from wow.core.workout import Block, PowerTarget, PowerUnit, Step, Workout

KEPT = TESTDATA / "rides"
SHORT = Workout("test:replay", "Replay check", None, (
    Block("Efforts", 2, (
        Step(40.0, PowerTarget(220, PowerUnit.WATTS), None),
        Step(20.0, PowerTarget(140, PowerUnit.WATTS), None))),))


def kept_rides() -> list[Path]:
    return sorted(p.parent for p in KEPT.glob("*/events.jsonl"))


@pytest.mark.case("T-LOG-05")
@pytest.mark.req("APP-820")
@pytest.mark.pi
@pytest.mark.asyncio
@pytest.mark.parametrize("case", kept_rides() or [None],
                         ids=lambda c: "none-kept" if c is None else c.name)
async def test_each_kept_ride_replays_without_a_difference(
        case: Path | None, tmp_path: Path) -> None:
    if case is None:
        pytest.skip("no real ride kept yet: run tools/keep_ride.py")
    mismatches, _ = await replay(case, tmp_path)
    assert mismatches == []


@pytest.mark.case("S-LOG-01")
@pytest.mark.asyncio
async def test_a_kept_simulated_ride_replays_without_a_difference(
        tmp_path: Path) -> None:
    session = AppSession(tmp_path / "ride", workouts=[SHORT])
    await session.begin(SHORT.ref)
    await session.until(30.0)
    assert session.command("intensity", step=1) is None
    await session.until(50.0)
    assert session.command("switch_mode", mode="resistance") is None
    assert session.command("resistance", step=1) is None
    await session.until(70.0)
    assert session.command("pause") is None
    await session.clock.advance(20.0)
    assert session.command("resume") is None
    await session.until(130.0)
    assert session.command("finish") is None
    session.app.recorder.flush()
    ride = await session.close()
    (ride / "workout.json").write_text(json.dumps({
        "id": "test:replay", "name": SHORT.name, "athlete_id": "i999",
        "workout_doc": {"steps": [{"reps": 2, "text": "Efforts", "steps": [
            {"duration": 40, "power": {"units": "w", "value": 220}},
            {"duration": 20, "power": {"units": "w", "value": 140}}]}]}}))
    case = keep_ride.keep(ride, session.app.config.data / "logs" /
                          "ble-system.jsonl", tmp_path / "kept")
    assert "i999" not in (case / "workout.json").read_text()
    kept_lines = read_jsonl(case / "ble.jsonl")
    wanted = {"connected", "read", "write", "notify", "indicate"}
    assert {r["op"] for r in kept_lines} >= wanted
    mismatches, app = await replay(case, tmp_path / "replay")
    assert mismatches == []
    (again,) = ride_dirs(app.config)
    first = [(e["type"], e["t_ride"]) for e in read_jsonl(
        ride / "events.jsonl") if e["type"] != "command"]
    second = [(e["type"], e["t_ride"]) for e in read_jsonl(
        again / "events.jsonl") if e["type"] != "command"]
    assert second == first
    assert keep_ride.main([str(ride), "--out", str(tmp_path / "cli")]) == 0
    assert keep_ride.workout_form(ride, "free_ride") is None
    assert keep_ride.links_before([], []) == []
