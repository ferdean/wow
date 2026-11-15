"""A simulated 4-hour ride on the stepped clock (L3, T-E2E-04)."""

import gc
import json
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from tests.support.app_rig import AppSession, read_jsonl
from tests.support.timeline import TESTDATA
from tools import check_ride
from wow.adapters.ble_sim import Fault, FaultKind, SimFaults
from wow.adapters.clock_stepped import DEFAULT_START
from wow.core.workout import Block, PowerTarget, PowerUnit, Step, Workout

HOUR = 3600.0
FIXTURE = TESTDATA / "metrics" / "t-e2e-04.metrics.json"
FLAT_BYTES = 16 * 1024
LONG = Workout("test:four-hours", "Four hours with ramps", None, (
    Block("Endurance", 4, (
        Step(2400.0, PowerTarget(72, PowerUnit.PERCENT_FTP), None),
        Step(600.0, PowerTarget(150, PowerUnit.WATTS), "Ramp",
             end=PowerTarget(250, PowerUnit.WATTS)),
        Step(600.0, PowerTarget(140, PowerUnit.WATTS), None))),))
PAUSE_AT = 3 * HOUR
PAUSE_FOR = 300.0


def fault(kind: FaultKind, start: float, length: float) -> Fault:
    begin = DEFAULT_START + 15.0 + 3.0 + start
    return Fault(kind, begin, begin + length)


def deep_size(*roots: object) -> int:
    """Return the bytes held by objects and what they reach, once each.

    Classes, modules and functions are shared code, not state.
    """
    seen: set[int] = set()
    todo = list(roots)
    total = 0
    while todo:
        item = todo.pop()
        if id(item) in seen or isinstance(item, (
                type, types.ModuleType, types.FunctionType,
                types.MethodType, types.BuiltinFunctionType)):
            continue
        seen.add(id(item))
        total += sys.getsizeof(item)
        todo.extend(gc.get_referents(item))
    return total


def core_bytes(session: AppSession) -> int:
    """Return the size of the core state machines of the ride."""
    app = session.app
    rides = app.rides
    return deep_size(rides.ride, rides._sampler, app.trainer._session,
                     app.console._power, app.console._hr)


@pytest.mark.case("T-E2E-04")
@pytest.mark.req("APP-812", "APP-804")
@pytest.mark.asyncio
async def test_a_four_hour_ride_with_dropouts_a_pause_and_ramps(
        tmp_path: Path) -> None:
    faults = SimFaults(
        trainer=(fault(FaultKind.LINK_LOSS, HOUR + 10.0, 40.0),),
        strap=(fault(FaultKind.LINK_LOSS, 2 * HOUR + 20.0, 60.0),))
    session = AppSession(tmp_path, sim_faults=faults, workouts=[LONG])
    await session.begin(LONG.ref)
    await session.until(HOUR + 5.0)
    after_an_hour = core_bytes(session)
    await session.until(PAUSE_AT)
    assert session.command("pause") is None
    await session.clock.advance(PAUSE_FOR)
    assert session.command("resume") is None
    await session.until(4 * HOUR - 0.5)
    at_the_end = core_bytes(session)
    assert session.command("finish") is None
    session.app.recorder.flush()
    ride = await session.close()
    samples = read_jsonl(ride / "samples.jsonl")
    events = read_jsonl(ride / "events.jsonl")
    ble = read_jsonl(ride / "ble.jsonl")
    system = check_ride.this_run(read_jsonl(
        session.app.config.data / "logs" / "ble-system.jsonl"), ble)
    assert len(samples) == 14_400
    assert [s["t"] for s in samples] == list(range(14_400))
    outcomes = {o.check: o for o in (check_ride.rr02(events, ble, system),
                                     check_ride.rr03(events),
                                     check_ride.rr05(events, samples, ble))}
    assert {c: o.result for c, o in outcomes.items()} == {
        "RR-02": "pass", "RR-03": "pass", "RR-05": "pass"}, outcomes
    assert "worst +0.0 ms" in outcomes["RR-03"].detail
    assert "worst 0.0 ms" in outcomes["RR-02"].detail
    dropouts = [(e["type"], e["device"]) for e in events
                if e["type"].startswith("dropout")]
    assert dropouts == [("dropout_start", "trainer"),
                        ("dropout_end", "trainer"),
                        ("dropout_start", "hrm"), ("dropout_end", "hrm")]
    assert [e["type"] for e in events if e["type"] in (
        "paused", "resumed")] == ["paused", "resumed"]
    metrics: dict[str, Any] = json.loads(
        (ride / "meta.json").read_text())["metrics"]
    if os.environ.get("WOW_UPDATE_GOLDEN") == "1":
        FIXTURE.write_text(json.dumps(metrics, indent=1) + "\n")
    assert metrics == json.loads(FIXTURE.read_text())
    assert metrics["duration"] == 14_400
    assert at_the_end - after_an_hour < FLAT_BYTES, (
        after_an_hour, at_the_end)
