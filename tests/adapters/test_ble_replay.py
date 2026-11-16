"""Replay of Bluetooth logs (L3)."""

import json
from pathlib import Path
from typing import Any

import pytest

from tests.support.app_rig import ERG_CHECK, app_config, read_jsonl
from tests.support.timeline import TESTDATA
from wow.adapters.ble_replay import ReplayConnector
from wow.adapters.clock_stepped import DEFAULT_START, SteppedClock
from wow.app.main import App
from wow.core import ftms_codec, hr_codec, uuids
from wow.core.ftms_codec import Dropped

FINISH_AT = 200.0
TIMES = (DEFAULT_START + 30.0, DEFAULT_START + 100.0, DEFAULT_START + 190.0)


async def ride(tmp: Path, replay: ReplayConnector | None = None,
               clock: SteppedClock | None = None
               ) -> tuple[App, list[dict[str, Any]]]:
    clock = clock or SteppedClock()
    app = App(app_config(tmp), clock, replay=replay)
    app.recorder.start()
    views = []
    assert app.console.command("open_workout", {"ref": ERG_CHECK}) is None
    await clock.run_until(DEFAULT_START + 15.0)
    assert app.console.command("start", {}) is None
    for at in TIMES:
        await clock.run_until(at)
        views.append(app.console.view())
    await clock.run_until(DEFAULT_START + FINISH_AT)
    assert app.console.command("finish", {}) is None
    await clock.advance(5.0)
    await clock.drive(app.devices.close(), limit=60.0)
    await clock.drive(app.rides.close(), limit=60.0)
    if app.scheduler is not None:
        await app.scheduler.close()
    app.recorder.stop()
    return app, views


def logged(app: App) -> list[dict[str, Any]]:
    data = app.config.data
    (ride_dir,) = sorted((data / "rides").iterdir())
    lines = read_jsonl(data / "logs" / "ble-system.jsonl") + read_jsonl(
        ride_dir / "ble.jsonl")
    return sorted(lines, key=lambda r: float(r["mono_ms"]))


def journal(app: App) -> list[tuple[Any, ...]]:
    (ride_dir,) = sorted((app.config.data / "rides").iterdir())
    return [(e["type"], e["t_ride"], e["mono_ms"],
             json.dumps({k: v for k, v in e.items()
                         if k not in ("utc", "boot_id", "mono_ms")}))
            for e in read_jsonl(ride_dir / "events.jsonl")]


def writes(lines: list[dict[str, Any]]) -> list[tuple[float, str]]:
    return [(r["mono_ms"], r["hex"]) for r in lines if r["op"] == "write"]


@pytest.mark.case("T-LOG-02")
@pytest.mark.req("APP-820")
@pytest.mark.asyncio
async def test_a_replayed_ride_matches_the_recorded_one(
        tmp_path: Path) -> None:
    first, first_views = await ride(tmp_path / "first")
    records = logged(first)
    clock = SteppedClock()
    replay = ReplayConnector(clock, records)
    second, second_views = await ride(tmp_path / "second", replay, clock)
    assert replay.mismatches == []
    assert journal(second) == journal(first)
    assert writes(logged(second)) == writes(records)
    for a, b in zip(first_views, second_views):
        assert {**a, "data_mono_ms": None} == {**b, "data_mono_ms": None}


@pytest.mark.case("T-LOG-03")
@pytest.mark.req("APP-820")
@pytest.mark.asyncio
async def test_an_altered_write_fails_the_replay(tmp_path: Path) -> None:
    first, _ = await ride(tmp_path / "first")
    records = logged(first)
    target = next(r for r in records if r["op"] == "write"
                  and r["hex"].startswith("05")
                  and r["mono_ms"] > (DEFAULT_START + 100.0) * 1000)
    target["hex"] = "05ff00"
    clock = SteppedClock()
    replay = ReplayConnector(clock, records)
    await ride(tmp_path / "second", replay, clock)
    (mismatch,) = replay.mismatches
    assert "05ff00" in mismatch and "log:" in mismatch and "app:" in mismatch


@pytest.mark.case("T-LOG-04")
@pytest.mark.req("APP-820", "APP-108")
@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["phase2-s1-contact", "phase2-s2-steps"])
async def test_phase2_logs_feed_every_record(name: str) -> None:
    records = read_jsonl(TESTDATA / "ble" / f"{name}.jsonl")
    first = float(records[0]["mono_ms"]) / 1000
    clock = SteppedClock(start=first - 1.0)
    replay = ReplayConnector(clock, records)
    got: dict[str, list[bytes]] = {}
    clients = []
    for address, chars in (
            ("94:05:BB:03:5D:9D", (uuids.INDOOR_BIKE_DATA,)),
            ("E0:E2:EF:63:14:BC", (uuids.HEART_RATE_MEASUREMENT,))):
        if not any(r["addr"] == address and r["op"] == "connected"
                   for r in records):
            continue
        client = await clock.drive(replay.connect(address, 1e9,
                                                  lambda _g: None))
        clients.append(client)
        for char in chars:
            await client.subscribe(char, got.setdefault(char, []).append)
    last = float(records[-1]["mono_ms"]) / 1000
    await clock.run_until(last + 1.0)
    expected = {c: [r for r in records if r["op"] == "notify"
                    and r["uuid"] == c] for c in got}
    assert {c: len(v) for c, v in got.items()} == {
        c: len(v) for c, v in expected.items()}
    bike = [ftms_codec.decode_indoor_bike_data(d) for d in got.get(
        uuids.INDOOR_BIKE_DATA, [])]
    heart = [hr_codec.decode_heart_rate(d) for d in got.get(
        uuids.HEART_RATE_MEASUREMENT, [])]
    assert not [x for x in bike + heart if isinstance(x, Dropped)]
    for client in clients:
        await client.close()
