"""Spin-down calibration (L2 and L3, T-CAL-01 to T-CAL-06)."""

from pathlib import Path
from typing import Any

import pytest

from tests.support.app_rig import ERG_CHECK, AppSession, read_jsonl
from wow.core import uuids
from wow.core.ftms_codec import SpinDownStatus
from wow.core.spindown import (
    SPINDOWN_TIMEOUT, Answered, Begin, Cancel, Phase, RequestSpinDown, Result,
    SetLowest, SpinDownMachine, Status, Tick,
)


def screen(session: AppSession) -> dict[str, Any]:
    value: dict[str, Any] = session.app.console.view()["screen"]
    return value


def control_writes(session: AppSession) -> list[str]:
    d100 = session.app.d100
    assert d100 is not None
    return [data.hex() for char, data in d100.traffic.writes
            if char == uuids.FITNESS_MACHINE_CONTROL_POINT]


async def calibrating(tmp: Path) -> AppSession:
    session = AppSession(tmp)
    assert session.command("open_calibration") is None
    await session.clock.advance(10.0)
    assert screen(session)["blocked"] is None
    assert session.command("calibration_start") is None
    return session


@pytest.mark.case("T-CAL-01")
@pytest.mark.req("APP-501")
@pytest.mark.asyncio
async def test_calibration_requests_control_then_spin_down(
        tmp_path: Path) -> None:
    session = await calibrating(tmp_path)
    assert screen(session)["phase"] == "starting"
    await session.clock.advance(0.5)
    writes = control_writes(session)
    assert writes[0] == "00" and writes[-1] == "1301"
    await session.close()


@pytest.mark.case("T-CAL-02")
@pytest.mark.req("APP-502")
@pytest.mark.asyncio
async def test_band_live_speed_and_stop_pedaling(tmp_path: Path) -> None:
    session = await calibrating(tmp_path)
    await session.clock.advance(2.0)
    view = screen(session)
    assert (view["phase"], view["band_kmh"]) == ("speed_up", [0.0, 40.0])
    assert view["speed_kmh"] is not None
    await session.clock.advance(3.0)
    assert screen(session)["phase"] == "stop_pedaling"
    await session.close()


@pytest.mark.case("T-CAL-03")
@pytest.mark.req("APP-503")
@pytest.mark.asyncio
@pytest.mark.parametrize("outcome, phase, ok, hex_", [
    (SpinDownStatus.SUCCESS, "success", True, "1402976c"),
    (SpinDownStatus.ERROR, "error", False, "1403")])
async def test_result_shown_and_logged(tmp_path: Path,
                                       outcome: SpinDownStatus, phase: str,
                                       ok: bool, hex_: str) -> None:
    session = AppSession(tmp_path)
    assert session.app.d100 is not None
    session.app.d100.spin_down_outcome = outcome
    assert session.command("open_calibration") is None
    await session.clock.advance(10.0)
    assert session.command("calibration_start") is None
    await session.clock.advance(40.0)
    view = screen(session)
    assert view["phase"] == phase
    assert view["last"]["ok"] is ok
    await session.close()
    log = read_jsonl(session.app.config.data / "logs" / "calibration.jsonl")
    assert [(r["ok"], r["hex"]) for r in log] == [(ok, hex_)]
    assert log[0]["utc"] == view["last"]["utc"]


@pytest.mark.case("T-CAL-04")
@pytest.mark.req("APP-504")
def test_no_result_in_120_s_times_out() -> None:
    machine = SpinDownMachine()
    assert machine.handle(Begin(), 0.0) == [RequestSpinDown()]
    machine.handle(Answered(1, (0.0, 40.0)), 0.4)
    machine.handle(Status(bytes([0x14, 0x04])), 5.0)
    assert machine.handle(Tick(), SPINDOWN_TIMEOUT - 0.1) == []
    assert machine.phase == Phase.STOP_PEDALING
    actions = machine.handle(Tick(), SPINDOWN_TIMEOUT)
    assert actions == [SetLowest(), Result(False, "timeout", b"")]
    assert str(machine.phase) == "timeout"
    assert machine.next_deadline() is None


@pytest.mark.case("T-CAL-04")
@pytest.mark.req("APP-504")
@pytest.mark.asyncio
async def test_timeout_in_the_app_leaves_the_lowest_level(
        tmp_path: Path) -> None:
    session = AppSession(tmp_path)
    assert session.app.d100 is not None
    session.app.d100.spin_down_outcome = None
    assert session.command("open_calibration") is None
    await session.clock.advance(10.0)
    assert session.command("calibration_start") is None
    await session.clock.advance(SPINDOWN_TIMEOUT + 1.0)
    assert screen(session)["phase"] == "timeout"
    assert control_writes(session)[-1] == "0400"
    assert session.command("back") is None
    assert screen(session)["name"] == "home"
    await session.close()


@pytest.mark.case("T-CAL-05")
@pytest.mark.req("APP-505")
@pytest.mark.asyncio
async def test_no_spin_down_while_a_ride_runs(tmp_path: Path) -> None:
    session = AppSession(tmp_path)
    await session.begin(ERG_CHECK)
    calibration = session.app.calibration
    for step in ("armed", "running", "paused", "workout_done"):
        if step == "running":
            await session.clock.advance(5.0)
        elif step == "paused":
            assert session.command("pause") is None
        elif step == "workout_done":
            assert session.command("resume") is None
            await session.until(361.0)
        assert session.app.rides.ride.phase.value == step
        assert calibration.start(True) == "ride_running"
        assert session.command("calibration_start") == "invalid_state"
    assert "1301" not in control_writes(session)
    assert session.command("finish") is None
    await session.close()


@pytest.mark.case("T-CAL-06")
@pytest.mark.req("APP-506")
@pytest.mark.asyncio
async def test_a_requested_spin_down_is_offered_once_no_ride_runs(
        tmp_path: Path) -> None:
    session = AppSession(tmp_path)
    d100 = session.app.d100
    assert d100 is not None
    await session.begin(ERG_CHECK)
    await session.clock.advance(10.0)
    d100.request_spin_down()
    await session.clock.advance(1.0)
    assert session.app.console.view()["warnings"] == []
    assert session.command("finish") is None
    await session.clock.advance(1.0)
    assert session.command("back") is None
    assert {"kind": "spindown_requested"} in session.app.console.view()[
        "warnings"]
    await session.close()


@pytest.mark.case("T-CAL-04")
@pytest.mark.req("APP-504")
def test_the_machine_ignores_what_does_not_belong() -> None:
    machine = SpinDownMachine()
    assert machine.handle(Status(bytes([0x14, 0x02])), 0.0) == []
    assert machine.handle(Answered(1, None), 0.0) == []
    machine.handle(Begin(), 0.0)
    assert machine.handle(Begin(), 0.1) == []
    assert machine.handle(Status(bytes([0x01])), 0.2) == []
    assert machine.handle(Cancel(), 0.3) == [SetLowest()]
    assert machine.elapsed(5.0) == pytest.approx(0.3)
    assert machine.handle(Cancel(), 0.4) == []
    machine.handle(Begin(), 1.0)
    refused = machine.handle(Answered(5, None), 1.4)
    assert refused == [SetLowest(), Result(False, "refused",
                                           bytes([0x80, 0x13, 5]))]
    assert machine.handle(Tick(), 200.0) == []
