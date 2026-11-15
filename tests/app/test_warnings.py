"""Warnings of SL-10 and the abandoned ride in the app (L1 and L3;
T-VIEW-05, T-VIEW-08, T-HK-02, T-RID-18)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.support.app_rig import AppSession, read_jsonl
from tests.support.scenes import started_ride
from wow.adapters.ble_sim import Fault, FaultKind, SimFaults
from wow.adapters.clock_stepped import DEFAULT_START, SteppedClock
from wow.app.housekeeping import CertificateWatch, certificate_end
from wow.core.view import (
    battery_warning, certificate_warning, clock_warning, ride_warnings,
)
from wow.core.workout import Block, PowerTarget, PowerUnit, Step, Workout

CERT = Path(__file__).resolve().parents[2] / "testdata" / "tls" / (
    "server.crt")
CERT_END = datetime(2036, 11, 9, 6, 27, 56, tzinfo=UTC)
HOUR_AT_150 = Workout("test:hour", "An hour at 150 W", None, (Block(
    None, 1, (Step(3600.0, PowerTarget(150, PowerUnit.WATTS), None),)),))


def kinds(view: dict[str, Any]) -> list[str]:
    return [w["kind"] for w in view["warnings"]]


@pytest.mark.case("T-VIEW-05")
@pytest.mark.req("APP-112", "APP-406")
def test_battery_warning_at_or_below_the_threshold() -> None:
    assert battery_warning(21, 20) == []
    assert battery_warning(20, 20) == [
        {"kind": "hrm_battery_low", "battery_pct": 20}]
    assert battery_warning(5, 20) == [
        {"kind": "hrm_battery_low", "battery_pct": 5}]
    assert battery_warning(40, 50) == [
        {"kind": "hrm_battery_low", "battery_pct": 40}]
    assert battery_warning(None, 20) == []
    extra = battery_warning(5, 20)
    assert ride_warnings(started_ride(), [], extra)[-1] == extra[0]


@pytest.mark.case("T-VIEW-05")
@pytest.mark.req("APP-112", "APP-406")
@pytest.mark.asyncio
@pytest.mark.parametrize(("battery", "threshold", "warned"), [
    (21, 20, False), (20, 20, True), (5, 20, True), (40, 50, True)])
async def test_pre_ride_and_ride_views_carry_battery_and_warning(
        tmp_path: Path, battery: int, threshold: int, warned: bool) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps(
        {"battery_warn_pct": threshold}))
    session = AppSession(tmp_path)
    assert session.app.sim is not None
    strap = [s for s in session.app.sim._servers.values()
             if s.advertisement().name == "HRM200:739158"][0]
    strap.battery_raw = battery  # type: ignore[attr-defined]
    assert session.command("open_workout", ref="builtin:erg-check") is None
    await session.clock.advance(15.0)
    pre_ride = session.app.console.view()
    assert session.command("start") is None
    await session.until(5.0)
    ride = session.app.console.view()
    for view in (pre_ride, ride):
        assert view["hrm_battery_pct"] == battery
        assert ("hrm_battery_low" in kinds(view)) == warned
    await session.close()


@pytest.mark.case("T-VIEW-08")
@pytest.mark.req("APP-824")
def test_clock_warning_only_when_not_synchronised() -> None:
    assert clock_warning(False) == [{"kind": "clock_unsynced"}]
    assert clock_warning(True) == []


@pytest.mark.case("T-VIEW-08")
@pytest.mark.req("APP-824")
@pytest.mark.asyncio
@pytest.mark.parametrize("synchronised", [False, True])
async def test_a_ride_started_without_time_sync_warns(
        tmp_path: Path, synchronised: bool) -> None:
    clock = SteppedClock(synchronised=synchronised)
    session = AppSession(tmp_path, clock=clock)
    home = session.app.console.view()
    await session.begin("builtin:erg-check")
    await session.until(5.0)
    clock.set_synchronised(True)
    ride = session.app.console.view()
    for view in (home, ride):
        assert ("clock_unsynced" in kinds(view)) == (not synchronised)
    await session.close()


@pytest.mark.case("T-HK-02")
@pytest.mark.req("APP-830")
@pytest.mark.parametrize(("days", "shown"), [
    (29, [{"kind": "cert_expiring", "days_left": 29}]),
    (30, [{"kind": "cert_expiring", "days_left": 30}]), (31, [])])
def test_certificate_warning_from_30_days(
        days: int, shown: list[dict[str, Any]]) -> None:
    clock = SteppedClock(utc_start=CERT_END - timedelta(days=days))
    watch = CertificateWatch(clock, CERT)
    assert watch.days_left() == days
    assert certificate_warning(watch.days_left()) == shown
    assert watch.valid_until == "2036-11-09T06:27:56.000Z"


@pytest.mark.case("T-HK-02")
@pytest.mark.req("APP-830")
@pytest.mark.asyncio
async def test_home_shows_the_certificate_warning(tmp_path: Path) -> None:
    clock = SteppedClock(utc_start=CERT_END - timedelta(days=12, hours=3))
    session = AppSession(tmp_path, clock=clock)
    assert {"kind": "cert_expiring", "days_left": 12} in (
        session.app.console.view()["warnings"])
    assert certificate_end(tmp_path / "missing.crt") is None
    assert CertificateWatch(clock, tmp_path / "missing.crt").days_left() is (
        None)
    assert certificate_warning(-3) == [
        {"kind": "cert_expiring", "days_left": 0}]
    await session.close()


@pytest.mark.case("T-RID-18")
@pytest.mark.req("APP-825")
@pytest.mark.asyncio
async def test_the_app_finishes_a_forgotten_ride(tmp_path: Path) -> None:
    stops = DEFAULT_START + 15.0 + 600.0
    faults = SimFaults(trainer=(Fault(FaultKind.POWER_ZERO, stops,
                                      stops + 7200.0),))
    session = AppSession(tmp_path, sim_faults=faults,
                         workouts=[HOUR_AT_150])
    await session.begin(HOUR_AT_150.ref)
    await session.clock.advance(600.0 + 1800.0 + 10.0)
    assert session.app.console.screen == "summary"
    session.app.recorder.flush()
    ride = await session.close()
    journal = read_jsonl(ride / "events.jsonl")
    (finished,) = [e for e in journal if e["type"] == "finished"]
    assert finished["cause"] == "idle"
    assert 2390.0 <= finished["t_ride"] <= 2400.0
    meta = json.loads((ride / "meta.json").read_text())
    assert meta["state"] == "finished" and (ride / "ride.fit").exists()
    assert [e for e in journal if e["type"] == "trainer_command"][-1][
        "level_raw"] == 0
