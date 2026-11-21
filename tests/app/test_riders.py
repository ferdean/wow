"""Riders who share the trainer (supporting S-RDR-03 to S-RDR-11)."""

import asyncio
import dataclasses
import json
import os
import stat
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from tests.app.test_garmin_cli import CONFIG, account, answers
from tests.adapters.test_garmin_connect import Factory
from tests.app.test_recovery import Restarted
from tests.app.test_uploads import FakeUploader
from tests.support.app_rig import (
    ERG_CHECK, AppSession, RecordedProvider, app_config,
)
from tests.support.timeline import load_json
from wow.adapters.ble_sim import D100_ADDRESS, HRM_ADDRESS
from wow.adapters.clock_stepped import SteppedClock
from wow.app.config import (
    GARMIN_TOKEN_FILE, Secrets, garmin_tokens, load_config, load_settings,
    save_secrets, save_settings,
)
from wow.app.garmin_cli import parse_args, run
from wow.app.main import App
from wow.app.riders import Riders, cache_of
from wow.app.workout_catalog import WorkoutCatalog
from wow.core.devices import DeviceKind
from wow.core.riders import Rider, RidersError
from wow.core.settings import DeviceRef, Settings
from wow.core.upload import Outcome
from wow.ports.workouts import ProviderError

FERRAN = Rider("ferran", "Ferran")
ANNA = Rider("anna", "Anna")
RIDERS = (FERRAN, ANNA)
STRAP = "AA:BB:CC:DD:EE:01"
TRAINER = DeviceRef(D100_ADDRESS, "D100")
RIDERS_TOML = '\n[riders]\nferran = "Ferran"\nanna = "Anna"\n'


def run_now(work: Any) -> None:
    work()


def old_files(data: Path) -> None:
    """What the data directory held before there were riders."""
    save_settings(data, Settings(ftp=262, lead_time=1.5, trainer=TRAINER,
                                 hrm=DeviceRef(HRM_ADDRESS, "HRM 200")))
    save_secrets(data, Secrets("i100", "key-ferran"))
    (data / "cache").mkdir()
    (data / "cache" / "intervals.json").write_text('{"schema": 1}')
    tokens = garmin_tokens(data)
    tokens.mkdir(mode=0o700)
    (tokens / GARMIN_TOKEN_FILE).write_text("{}")


def stamped_ride(rides: Path, ride_id: str, rider: str | None) -> None:
    ride_dir = rides / ride_id
    ride_dir.mkdir(parents=True)
    meta: dict[str, Any] = {"schema": 1, "ride_id": ride_id,
                            "state": "finished", "title": "ERG check",
                            "upload": "done", "metrics": None}
    if rider is not None:
        meta["rider"] = rider
    (ride_dir / "meta.json").write_text(json.dumps(meta))


def meta_of(ride_dir: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads((ride_dir / "meta.json").read_text())
    return value


class FakeAccount(FakeUploader):
    """An intervals.icu account with no workouts."""

    async def planned(self, oldest: date, newest: date) -> list[Any]:
        return []

    async def library(self) -> list[Any]:
        return []


class GatedProvider(RecordedProvider):
    """Answers once let go; fails instead if told to."""

    def __init__(self, fail: bool) -> None:
        super().__init__(load_json("intervals/events.json"),
                         load_json("intervals/workouts.json"))
        self.gate = asyncio.Event()
        self.fail = fail

    async def planned(self, oldest: date, newest: date) -> list[Any]:
        await self.gate.wait()
        if self.fail:
            raise ProviderError("offline")
        return self.events


@pytest.mark.case("S-RDR-03")
def test_wow_toml_names_the_riders(tmp_path: Path) -> None:
    path = tmp_path / "wow.toml"
    path.write_text(CONFIG.format(data=tmp_path) + RIDERS_TOML)
    assert load_config(path).riders == RIDERS
    path.write_text(CONFIG.format(data=tmp_path))
    assert load_config(path).riders == ()
    path.write_text(CONFIG.format(data=tmp_path) + '[riders]\nAnna = "A"\n')
    with pytest.raises(RidersError):
        load_config(path)


@pytest.mark.case("S-RDR-04")
def test_one_rider_keeps_the_data_directory(tmp_path: Path) -> None:
    riders = Riders(tmp_path, (), run_now)
    riders.prepare()
    assert not riders.configured and riders.home("rider") == tmp_path
    assert riders.owner({"rider": "anna"}) == riders.active.rider_id
    assert riders.stamp() is None
    assert not (tmp_path / "riders").exists()


@pytest.mark.case("S-RDR-04")
@pytest.mark.posix
def test_the_first_rider_gets_a_copy_of_the_old_files_once(
        tmp_path: Path) -> None:
    old_files(tmp_path)
    (tmp_path / "riders" / ".ferran.new").mkdir(parents=True)
    riders = Riders(tmp_path, RIDERS, run_now)
    riders.prepare()
    ferran, anna = riders.home("ferran"), riders.home("anna")
    assert ferran == tmp_path / "riders" / "ferran"
    assert load_settings(ferran).ftp == 262
    assert stat.S_IMODE(os.stat(ferran / "secrets.json").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(ferran / "garmin").st_mode) == 0o700
    assert (ferran / "garmin" / GARMIN_TOKEN_FILE).is_file()
    assert cache_of(ferran).read_text() == '{"schema": 1}'
    assert anna.is_dir() and not any(anna.iterdir())
    assert not (tmp_path / "riders" / ".ferran.new").exists()
    assert (tmp_path / "settings.json").exists()
    save_settings(tmp_path, Settings(ftp=300))
    Riders(tmp_path, RIDERS, run_now).prepare()
    assert load_settings(ferran).ftp == 262


@pytest.mark.case("S-RDR-04")
def test_the_rider_riding_now_and_the_owner_of_a_ride(tmp_path: Path) -> None:
    riders = Riders(tmp_path, RIDERS, run_now)
    assert riders.active == FERRAN and riders.stamp() == "ferran"
    riders.choose(ANNA)
    assert Riders(tmp_path, RIDERS, run_now).active == ANNA
    assert Riders(tmp_path, (FERRAN,), run_now).active == FERRAN
    (tmp_path / "rider.json").write_text("[1]")
    assert Riders(tmp_path, RIDERS, run_now).active == FERRAN
    (tmp_path / "rider.json").write_text("{")
    assert Riders(tmp_path, RIDERS, run_now).active == FERRAN
    assert riders.owner({"rider": "anna"}) == "anna"
    assert riders.owner({}) == "ferran"
    assert riders.owner({"rider": "bob"}) == "bob"
    assert riders.find("bob") is None and riders.find("anna") == ANNA


@pytest.mark.case("S-RDR-05")
@pytest.mark.asyncio
async def test_each_rider_has_their_own_settings(tmp_path: Path) -> None:
    old_files(tmp_path / "data")
    session = AppSession(tmp_path, riders=RIDERS)
    view = session.app.console.view()
    assert view["riders"] == {
        "active": "ferran", "ftp": 262,
        "list": [{"id": "ferran", "name": "Ferran"},
                 {"id": "anna", "name": "Anna"}]}
    assert session.command("rider_choose", rider="anna") is None
    her = session.app.settings.settings
    assert (her.ftp, her.lead_time, her.trainer, her.hrm) == (
        250, 1.5, TRAINER, None)
    assert session.app.console.view()["riders"]["ftp"] == 250
    assert session.command("open_settings") is None
    screen = session.app.console.view()["screen"]
    assert screen["intervals_account_set"] is False
    assert not screen["garmin_signed_in"]
    assert session.command("settings_set", key="ftp", value=205) is None
    assert session.command("rider_choose", rider="ferran") is None
    assert session.app.console.screen == "home"
    assert session.app.settings.settings.ftp == 262
    assert session.command("open_settings") is None
    assert session.app.console.view()["screen"]["garmin_signed_in"]
    assert session.command("rider_choose", rider="anna") is None
    assert session.app.settings.settings.ftp == 205
    session.app.recorder.flush()
    data = tmp_path / "data"
    assert load_settings(data / "riders" / "anna").ftp == 205
    assert load_settings(data / "riders" / "ferran").ftp == 262
    await session.close()
    again = AppSession(tmp_path, riders=RIDERS)
    assert again.app.riders.active == ANNA
    assert again.app.settings.settings.ftp == 205
    await again.close()


@pytest.mark.case("S-RDR-05")
@pytest.mark.asyncio
async def test_the_devices_follow_the_rider(tmp_path: Path) -> None:
    save_settings(tmp_path / "data" / "riders" / "anna",
                  Settings(hrm=DeviceRef(STRAP, "Her strap")))
    session = AppSession(tmp_path, riders=RIDERS)
    devices = session.app.devices
    assert devices.address(DeviceKind.HRM) == HRM_ADDRESS
    assert session.command("rider_choose", rider="anna") is None
    await session.clock.advance(1.0)
    assert devices.address(DeviceKind.HRM) == STRAP
    assert devices.address(DeviceKind.TRAINER) == D100_ADDRESS
    await session.close()


@pytest.mark.case("S-RDR-06")
@pytest.mark.asyncio
async def test_a_ride_goes_to_its_own_riders_accounts(
        tmp_path: Path) -> None:
    clock = SteppedClock()
    old_files(tmp_path / "data")
    icu = {"i100": FakeAccount(clock, Outcome.CREATED),
           "i200": FakeAccount(clock, Outcome.CREATED)}
    garmin: dict[Path, FakeUploader] = {}

    def garmin_of(tokens: Path) -> FakeUploader:
        return garmin.setdefault(tokens, FakeUploader(clock, Outcome.CREATED))

    session = AppSession(tmp_path, clock=clock, riders=RIDERS,
                         upload_simulated=True,
                         account=lambda s: icu[s.athlete_id],
                         garmin_account=garmin_of)
    app = session.app
    tasks = [asyncio.get_running_loop().create_task(w.run())
             for w in (app.uploads, app.garmin_uploads)]
    await session.begin(ERG_CHECK)
    await session.until(30.0)
    assert session.command("finish") is None
    app.recorder.flush()
    await clock.advance(5.0)
    assert session.command("rider_choose", rider="anna") is None
    assert session.command("open_settings") is None
    assert session.command("settings_set", key="garmin_upload_on",
                           value=True) is None
    assert session.command("back") is None
    await clock.advance(60.0)
    await session.begin(ERG_CHECK)
    await session.until(30.0)
    assert session.command("finish") is None
    app.recorder.flush()
    await clock.advance(5.0)
    his, hers = sorted((tmp_path / "data" / "rides").iterdir())
    assert [c[1] for c in icu["i100"].calls] == [his.name]
    assert icu["i200"].calls == []
    assert meta_of(hers)["upload"] == "pending"
    assert session.command("back") is None
    assert session.command("open_settings") is None
    assert session.command("intervals_account_set", athlete_id="i200",
                           api_key="key-anna") is None
    await clock.advance(5.0)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await session.close()
    assert [c[1] for c in icu["i200"].calls] == [hers.name]
    data = tmp_path / "data" / "riders"
    assert list(garmin) == [data / "anna" / "garmin"]
    assert [c[1] for c in garmin[data / "anna" / "garmin"].calls] == [
        hers.name]
    assert (meta_of(his)["rider"], meta_of(hers)["rider"]) == (
        "ferran", "anna")
    assert meta_of(hers)["upload"] == "done"
    assert (data / "anna" / "secrets.json").is_file()


@pytest.mark.case("S-RDR-07")
@pytest.mark.asyncio
async def test_past_rides_are_the_rider_riding_now(tmp_path: Path) -> None:
    rides = tmp_path / "data" / "rides"
    stamped_ride(rides, "2026-11-01T170000Z", None)
    stamped_ride(rides, "2026-11-02T170000Z", "anna")
    stamped_ride(rides, "2026-11-03T170000Z", "ferran")
    stamped_ride(rides, "2026-11-04T170000Z", "bob")
    session = AppSession(tmp_path, riders=RIDERS)

    def listed() -> list[str]:
        assert session.command("open_history") is None
        screen = session.app.console.view()["screen"]
        return [r["ride_id"] for r in screen["rides"]]

    assert listed() == ["2026-11-03T170000Z", "2026-11-01T170000Z"]
    assert session.command("rider_choose", rider="anna") is None
    assert listed() == ["2026-11-02T170000Z"]
    await session.close()


@pytest.mark.case("S-RDR-08")
@pytest.mark.asyncio
async def test_the_rider_changes_only_outside_a_ride(tmp_path: Path) -> None:
    alone = AppSession(tmp_path / "alone")
    assert alone.command("rider_choose", rider="rider") == "bad_request"
    assert "riders" not in alone.app.console.view()
    await alone.close()
    session = AppSession(tmp_path, riders=RIDERS)
    assert session.command("rider_choose", rider="bob") == "bad_request"
    assert session.command("open_calibration") is None
    assert session.command("rider_choose", rider="anna") == "invalid_state"
    assert session.command("back") is None
    await session.begin(ERG_CHECK)
    assert session.command("rider_choose", rider="anna") == "invalid_state"
    await session.until(30.0)
    assert session.command("finish") is None
    session.app.recorder.flush()
    await session.clock.advance(5.0)
    his = session.app.console.view()["screen"]["ride_id"]
    assert session.command("back") is None
    assert session.command("open_history") is None
    assert session.command("open_ride", ride_id=his) is None
    assert session.command("rider_choose", rider="anna") is None
    assert session.app.console.screen == "home"
    await session.clock.advance(60.0)
    await session.begin(ERG_CHECK)
    await session.until(30.0)
    assert session.command("finish") is None
    await session.clock.advance(5.0)
    hers = session.app.console.view()["screen"]["ride_id"]
    assert hers != his
    assert session.app.riders.active == ANNA
    await session.close()


@pytest.mark.case("S-RDR-09")
@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_the_workouts_of_the_rider_before_are_dropped(
        tmp_path: Path, fail: bool) -> None:
    clock = SteppedClock()
    his = GatedProvider(fail)
    hers = RecordedProvider([], [])
    library = load_json("intervals/workouts.json")
    cache_of(tmp_path / "anna").parent.mkdir(parents=True)
    cache_of(tmp_path / "anna").write_text(json.dumps({
        "schema": 1, "downloaded_utc": "2026-11-20T08:00:00.000Z",
        "events": [], "workouts": library}))
    catalog = WorkoutCatalog(clock, his, cache_of(tmp_path / "ferran"), [],
                             lambda: None)
    late = asyncio.get_running_loop().create_task(catalog.refresh())
    catalog.request_refresh()
    await asyncio.sleep(0)
    catalog.switch(hers, cache_of(tmp_path / "anna"))
    shown = [e.ref for e in catalog.library()]
    assert shown and catalog.today() == []
    his.gate.set()
    await late
    await catalog.close()
    assert [e.ref for e in catalog.library()] == shown
    assert catalog.offline_since is None
    assert not cache_of(tmp_path / "ferran").exists()


@pytest.mark.case("S-RDR-10")
@pytest.mark.asyncio
async def test_an_interrupted_ride_is_taken_up_by_its_rider(
        tmp_path: Path) -> None:
    first = AppSession(tmp_path / "first", riders=RIDERS)
    assert first.command("rider_choose", rider="anna") is None
    await first.begin(ERG_CHECK)
    await first.until(130.0)
    again = Restarted(first, tmp_path / "again")
    again.app = App(dataclasses.replace(app_config(tmp_path / "again"),
                                        riders=RIDERS),
                    again.clock, boot=first.app.recorder.boot_id)
    await again.start()
    assert again.app.riders.active == ANNA
    assert again.app.console.command("rider_choose",
                                     {"rider": "ferran"}) is None
    assert again.home()["recovery"] is not None
    assert again.command("recovery_finish") is None
    assert again.app.riders.active == ANNA
    ride_dir = await again.close()
    await first.close()
    assert meta_of(ride_dir)["rider"] == "anna"
    assert meta_of(ride_dir)["state"] == "finished"


@pytest.mark.case("S-RDR-11")
def test_wow_garmin_signs_in_the_rider_named(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "wow.toml"
    data = tmp_path / "data"
    path.write_text(CONFIG.format(data=data) + RIDERS_TOML)
    factory = Factory()
    args = parse_args(["--config", str(path), "--rider", "anna", "login"])
    assert run(args, account(factory), answers("her@example.com", "1"),
               answers("secret")) == 0
    tokens = data / "riders" / "anna" / "garmin"
    assert factory.made[-1].calls == [("login", str(tokens))]
    assert (data / "riders" / "ferran").is_dir()
    assert capsys.readouterr().out.endswith(f"tokens in {tokens}\n")
    for argv in (["login"], ["--rider", "bob", "login"]):
        args = parse_args(["--config", str(path), *argv])
        assert run(args, account(factory), answers(), answers()) == 2
    assert "--rider: ferran, anna" in capsys.readouterr().err
    path.write_text(CONFIG.format(data=data))
    args = parse_args(["--config", str(path), "--rider", "anna", "check"])
    assert run(args, account(factory), answers(), answers()) == 2
    assert "no [riders]" in capsys.readouterr().err
