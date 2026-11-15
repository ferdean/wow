"""Settings and the intervals.icu account in the app (L3; T-SET-01,
T-SET-06 to T-SET-08, T-MET-08)."""

import asyncio
import base64
import json
import logging
import os
import stat
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from aiohttp import web

from tests.support.app_rig import ERG_CHECK, AppSession, read_jsonl
from tests.support.timeline import load_json
from wow.adapters.ble_sim import D100_ADDRESS, HRM_ADDRESS
from wow.adapters.intervals_icu import IntervalsIcu
from wow.app import config
from wow.app.config import Secrets, load_settings, save_settings
from wow.core.settings import DeviceRef, Settings
from wow.core.workout import Block, PowerTarget, PowerUnit, Step, Workout

MARKER = "MARKER-key-7f3a9c"
ATHLETE = "i777"
SWEET = Workout("test:sweet", "Sweet spot", None, (Block(None, 1, (
    Step(300.0, PowerTarget(80, PowerUnit.PERCENT_FTP), None),)),))


@pytest.mark.case("T-SET-01")
@pytest.mark.req("APP-708")
@pytest.mark.asyncio
async def test_without_a_settings_file_table_s_applies(
        tmp_path: Path) -> None:
    session = AppSession(tmp_path)
    settings = session.app.settings.settings
    assert settings == Settings()
    assert (settings.ftp, settings.zones_pct, settings.lead_time,
            settings.battery_warn_pct, settings.free_ride_level_pct,
            settings.upload_on, settings.trainer, settings.hrm) == (
        250, (55, 75, 90, 105, 120), 1.0, 20, 0, True, None, None)
    assert session.command("open_settings") is None
    screen = session.app.console.view()["screen"]
    assert (screen["name"], screen["ftp"], screen["zones_pct"],
            screen["lead_time"], screen["battery_warn_pct"],
            screen["upload_on"], screen["intervals_account_set"],
            screen["trainer"], screen["hrm"], screen["scan"]) == (
        "settings", 250, [55, 75, 90, 105, 120], 1.0, 20, True, False,
        None, None, None)
    assert screen["cert_valid_until"] == "2036-11-09T06:27:56.000Z"
    await session.close()


async def choose(session: AppSession, kind: str, address: str) -> None:
    assert session.command("device_scan", kind=kind) is None
    await session.clock.advance(6.0)
    assert session.command("device_choose", kind=kind,
                           address=address) is None
    await session.clock.advance(1.0)


@pytest.mark.case("T-SET-06")
@pytest.mark.req("APP-707")
@pytest.mark.asyncio
async def test_every_setting_survives_a_restart(tmp_path: Path) -> None:
    first = AppSession(tmp_path)
    assert first.command("open_settings") is None
    for key, value in (("ftp", 281), ("zones_pct", [56, 76, 91, 106, 121]),
                       ("lead_time", 2.5), ("battery_warn_pct", 35),
                       ("upload_on", False)):
        assert first.command("settings_set", key=key, value=value) is None
    assert first.command("settings_set", key="ftp", value=501) == (
        "invalid_value")
    first.app.settings.keep_free_ride_level(45)
    await choose(first, "trainer", D100_ADDRESS)
    await choose(first, "hrm", HRM_ADDRESS)
    wanted = first.app.settings.settings
    await first.close()
    second = AppSession(tmp_path)
    assert second.app.settings.settings == wanted == Settings(
        281, (56, 76, 91, 106, 121), 2.5, 35, 45, False,
        DeviceRef(D100_ADDRESS, "VANRYSEL-HT-9d5d"),
        DeviceRef(HRM_ADDRESS, "HRM200:739158"))
    await second.close()


@pytest.mark.case("T-SET-06")
@pytest.mark.req("APP-707")
def test_a_stop_before_the_rename_leaves_the_old_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = Settings(ftp=240)
    save_settings(tmp_path, old)
    before = (tmp_path / "settings.json").read_bytes()

    def stop(*_args: Any) -> None:
        raise SystemExit("process stopped")

    monkeypatch.setattr(os, "replace", stop)
    with pytest.raises(SystemExit):
        save_settings(tmp_path, Settings(ftp=310))
    monkeypatch.undo()
    assert (tmp_path / "settings.json").read_bytes() == before
    assert json.loads((tmp_path / ".settings.json.tmp").read_text())[
        "ftp"] == 310
    assert load_settings(tmp_path) == old
    save_settings(tmp_path, Settings(ftp=310))
    assert load_settings(tmp_path).ftp == 310
    (tmp_path / "settings.json").write_text('{"ftp": 3')
    assert load_settings(tmp_path) == Settings()
    (tmp_path / "settings.json").write_text('[1]')
    assert load_settings(tmp_path) == Settings()


@pytest.mark.case("T-SET-07")
@pytest.mark.req("APP-706", "APP-817")
@pytest.mark.posix
@pytest.mark.asyncio
async def test_the_account_is_kept_readable_by_the_app_only(
        tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "secrets.json").write_text("{}")
    (data / "secrets.json").chmod(0o644)
    session = AppSession(tmp_path)
    assert session.command("open_settings") is None
    assert session.command("intervals_account_set", athlete_id=ATHLETE,
                           api_key="bad key") == "invalid_value"
    assert session.command("intervals_account_set", athlete_id=ATHLETE,
                           api_key=MARKER) is None
    session.app.recorder.flush()
    path = data / "secrets.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text()) == {
        "schema": 1, "intervals_athlete_id": ATHLETE,
        "intervals_api_key": MARKER}
    view = json.dumps(session.app.console.view())
    assert '"intervals_account_set": true' in view
    assert MARKER not in view and ATHLETE not in view
    assert config.load_secrets(data) == Secrets(ATHLETE, MARKER)
    assert MARKER not in repr(config.load_secrets(data))
    await session.close()


@pytest_asyncio.fixture
async def icu() -> AsyncIterator[tuple[str, list[str], list[int]]]:
    seen: list[str] = []
    answers = [500, 201]

    async def events(request: web.Request) -> web.Response:
        seen.append(request.headers["Authorization"])
        return web.json_response(load_json("intervals/events.json"))

    async def workouts(request: web.Request) -> web.Response:
        seen.append(request.headers["Authorization"])
        return web.json_response(load_json("intervals/workouts.json"))

    async def activities(request: web.Request) -> web.Response:
        seen.append(request.headers["Authorization"])
        await request.post()
        status = answers.pop(0) if len(answers) > 1 else answers[0]
        return web.json_response({"id": "a1"}, status=status)

    app = web.Application()
    app.router.add_get("/api/v1/athlete/{id}/events", events)
    app.router.add_get("/api/v1/athlete/{id}/workouts", workouts)
    app.router.add_post("/api/v1/athlete/{id}/activities", activities)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    yield f"http://127.0.0.1:{runner.addresses[0][1]}/api/v1", seen, answers
    await runner.cleanup()


async def real_wait(session: AppSession, until: Any) -> None:
    for _ in range(200):
        if until():
            return
        await asyncio.sleep(0.02)
        await session.clock.advance(0.0)
    raise AssertionError("timed out")


@pytest.mark.case("T-SET-08")
@pytest.mark.req("APP-817")
@pytest.mark.asyncio
async def test_the_key_appears_nowhere(
        tmp_path: Path, icu: tuple[str, list[str], list[int]],
        caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    base, seen, _ = icu
    session = AppSession(tmp_path, account=lambda s: IntervalsIcu(
        s.athlete_id, s.api_key, base))
    app = session.app
    worker = asyncio.get_running_loop().create_task(app.uploads.run())
    outputs: list[Any] = []

    def command(name: str, **args: Any) -> None:
        outputs.append(session.command(name, **args))
        outputs.append(app.console.view())
        outputs.append(app.console.plan())

    command("open_settings")
    command("intervals_account_set", athlete_id=ATHLETE, api_key=MARKER)
    command("settings_set", key="battery_warn_pct", value=25)
    await real_wait(session, lambda: len(seen) >= 2)
    command("back")
    command("open_workout", ref=ERG_CHECK)
    await session.clock.advance(15.0)
    command("start")
    for _ in range(40):
        await session.clock.advance(1.0)
        outputs.append(app.console.view())
    command("finish")
    app.recorder.flush()
    await session.clock.advance(5.0)
    await real_wait(session, lambda: len(seen) >= 3)
    await session.clock.advance(901.0)
    await real_wait(session, lambda: len(seen) >= 4)
    ride = await session.close()
    worker.cancel()
    await asyncio.gather(worker, return_exceptions=True)
    assert json.loads((ride / "meta.json").read_text())["upload"] == "done"
    header = "Basic " + base64.b64encode(
        f"API_KEY:{MARKER}".encode()).decode()
    assert set(seen) == {header}
    forms = (MARKER, header, header.split()[1])
    text = json.dumps(outputs) + caplog.text
    files = [p for p in app.config.data.rglob("*")
             if p.is_file() and p.name != "secrets.json"]
    assert {p.name for p in files} >= {
        "events.jsonl", "ble.jsonl", "samples.jsonl", "ride.fit",
        "meta.json", "settings.json", "ble-system.jsonl", "intervals.json"}
    for form in forms:
        assert form not in text
        for path in files:
            assert form.encode() not in path.read_bytes(), path
    assert read_jsonl(ride / "events.jsonl")


@pytest.mark.case("T-MET-08")
@pytest.mark.req("APP-701")
@pytest.mark.asyncio
async def test_a_new_ftp_waits_for_the_next_ride(tmp_path: Path) -> None:
    session = AppSession(tmp_path, workouts=[SWEET])
    await session.begin(SWEET.ref)
    await session.until(60.0)
    assert session.command("settings_set", key="ftp", value=300) == (
        "invalid_state")
    assert session.app.settings.set("ftp", 300) is None
    await session.until(200.0)
    assert session.command("finish") is None
    session.app.recorder.flush()
    ride = await session.close()
    meta = json.loads((ride / "meta.json").read_text())
    metrics = meta["metrics"]
    assert meta["ftp"] == 250
    assert metrics["intensity_factor"] == pytest.approx(
        metrics["np"] / 250, abs=1e-6)
    powers = {e["power"] for e in read_jsonl(ride / "events.jsonl")
              if e["type"] == "trainer_command" and e["mode"] == "erg"}
    assert powers == {200}
    assert session.app.settings.settings.ftp == 300
    assert session.command("back") is None
    assert session.command("open_workout", ref=SWEET.ref) is None
    assert session.app.console.view()["screen"]["ftp"] == 300
