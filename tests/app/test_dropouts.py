"""Dropouts of the trainer, the strap and the display in a ride (L3)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.support.app_rig import (
    ERG_CHECK, app_config, read_jsonl, ride_dirs,
)
from tests.support.page import FakeSocket
from tools import check_ride
from wow.adapters.ble_sim import Fault, FaultKind, SimFaults
from wow.adapters.clock_stepped import DEFAULT_START, SteppedClock
from wow.app.main import App


def fault(kind: FaultKind, start: float, end: float) -> Fault:
    return Fault(kind, DEFAULT_START + start, DEFAULT_START + end)


class Display:
    """A page on the app's hub, connected and disconnected at will."""

    def __init__(self, app: App, clock: SteppedClock) -> None:
        self._app, self._clock = app, clock
        self.socket: FakeSocket | None = None
        self._serving: asyncio.Future[None] | None = None

    async def open(self) -> FakeSocket:
        self.socket = FakeSocket(self._clock)
        self._serving = asyncio.ensure_future(self._app.hub.serve(
            self.socket, self.socket.messages()))
        await self._clock.settle()
        return self.socket

    async def close(self) -> None:
        if self.socket is not None:
            await self.socket.close()
        if self._serving is not None:
            await asyncio.gather(self._serving, return_exceptions=True)


Riding = tuple[App, SteppedClock, asyncio.Task[None]]


async def riding(tmp: Path, faults: SimFaults) -> Riding:
    clock = SteppedClock()
    app = App(app_config(tmp), clock, sim_faults=faults)
    app.recorder.start()
    pump = asyncio.get_running_loop().create_task(app.hub.run())
    assert app.console.command("open_workout", {"ref": ERG_CHECK}) is None
    await clock.run_until(DEFAULT_START + 15.0)
    assert app.console.command("start", {}) is None
    return app, clock, pump


async def finish(app: App, clock: SteppedClock,
                 pump: asyncio.Task[None]) -> Path:
    assert app.console.command("finish", {}) is None
    await clock.advance(5.0)
    await clock.drive(app.devices.close(), limit=60.0)
    await clock.drive(app.rides.close(), limit=60.0)
    await app.hub.close()
    pump.cancel()
    await asyncio.gather(pump, return_exceptions=True)
    if app.scheduler is not None:
        await app.scheduler.close()
    app.recorder.stop()
    return ride_dirs(app.config)[-1]


def links(app: App) -> tuple[str, str]:
    view: dict[str, Any] = app.console.view()
    return view["links"]["trainer"], view["links"]["hrm"]


@pytest.mark.case("T-VIEW-03")
@pytest.mark.req("APP-405")
@pytest.mark.asyncio
async def test_dropouts_show_in_the_next_view(tmp_path: Path) -> None:
    faults = SimFaults(
        trainer=(fault(FaultKind.SILENCE, 60.0, 64.0),
                 fault(FaultKind.LINK_LOSS, 80.0, 90.0)),
        strap=(fault(FaultKind.LINK_LOSS, 100.0, 110.0),))
    clock = SteppedClock()
    app = App(app_config(tmp_path), clock, sim_faults=faults)
    app.recorder.start()
    seen = {"home": links(app)}
    assert app.console.command("open_workout", {"ref": ERG_CHECK}) is None
    await clock.run_until(DEFAULT_START + 15.0)
    seen["pre_ride"] = links(app)
    assert app.console.command("start", {}) is None
    await clock.run_until(DEFAULT_START + 62.0)
    assert links(app) == ("connected", "connected")
    await clock.run_until(DEFAULT_START + 63.2)
    assert links(app)[0] == "dropout"
    await clock.run_until(DEFAULT_START + 64.5)
    assert links(app)[0] == "connected"
    await clock.run_until(DEFAULT_START + 80.01)
    assert links(app)[0] == "dropout"
    await clock.run_until(DEFAULT_START + 100.01)
    assert links(app)[1] == "dropout"
    await clock.run_until(DEFAULT_START + 125.0)
    assert links(app) == ("connected", "connected")
    assert app.console.command("finish", {}) is None
    seen["summary"] = links(app)
    assert seen == {"home": ("not_found", "not_found"),
                    "pre_ride": ("connected", "connected"),
                    "summary": ("connected", "connected")}
    await clock.advance(5.0)
    await clock.drive(app.devices.close(), limit=60.0)
    await clock.drive(app.rides.close(), limit=60.0)
    app.recorder.stop()


@pytest.mark.case("T-E2E-03")
@pytest.mark.req("APP-318", "APP-319", "APP-603", "APP-805", "APP-806",
                 "APP-807")
@pytest.mark.asyncio
async def test_uc07_trainer_strap_and_display_lost_in_one_ride(
        tmp_path: Path) -> None:
    faults = SimFaults(
        trainer=(fault(FaultKind.LINK_LOSS, 100.0, 120.0),),
        strap=(fault(FaultKind.LINK_LOSS, 140.0, 160.0),))
    app, clock, pump = await riding(tmp_path, faults)
    display = Display(app, clock)
    await display.open()
    await clock.run_until(DEFAULT_START + 180.0)
    await display.close()
    await clock.run_until(DEFAULT_START + 240.0)
    socket = await display.open()
    opened = clock.monotonic()
    await clock.advance(5.0)
    views = [(t, m) for t, m in socket.of_type("view") if t <= opened + 5]
    assert views and views[0][1]["screen"]["name"] == "ride"
    assert views[0][1]["screen"]["elapsed"] >= 215.0
    await clock.run_until(DEFAULT_START + 300.0)
    await display.close()
    ride = await finish(app, clock, pump)
    events = read_jsonl(ride / "events.jsonl")
    started = next(e["mono_ms"] for e in events
                   if e["type"] == "ride_started") / 1000
    log = read_jsonl(ride / "ble.jsonl")
    back = [r["mono_ms"] / 1000 - DEFAULT_START for r in log
            if r["op"] == "write" and r["gen"] == 2 and r["hex"][:2] == "05"]
    assert back and back[0] <= 130.0
    samples = read_jsonl(ride / "samples.jsonl")
    assert [s["t"] for s in samples] == list(range(len(samples)))
    gap = [s for s in samples
           if 104.0 <= s["t"] + started - DEFAULT_START <= 118.0]
    assert gap and all(s["power"] is None for s in gap)
    strap_gap = [s for s in samples
                 if 144.0 <= s["t"] + started - DEFAULT_START <= 158.0]
    assert strap_gap and all(s["hr_bpm"] is None for s in strap_gap)
    rr05 = check_ride.rr05(events, samples, log)
    assert rr05.result == "pass", rr05.detail
    assert {(e["type"], e["device"]) for e in events if "device" in e} == {
        ("dropout_start", "trainer"), ("dropout_end", "trainer"),
        ("dropout_start", "hrm"), ("dropout_end", "hrm")}


@pytest.mark.case("T-WEB-05")
@pytest.mark.req("APP-807")
@pytest.mark.asyncio
async def test_a_page_gone_for_a_minute_changes_nothing(
        tmp_path: Path) -> None:
    app, clock, pump = await riding(tmp_path, SimFaults())
    display = Display(app, clock)
    await display.open()
    await clock.run_until(DEFAULT_START + 100.0)
    await display.close()
    await clock.run_until(DEFAULT_START + 160.0)
    socket = await display.open()
    opened = clock.monotonic()
    await clock.advance(5.0)
    first = socket.of_type("view")[0]
    assert first[0] - opened <= 5.0
    assert first[1]["screen"]["elapsed"] >= 140.0
    await display.close()
    ride = await finish(app, clock, pump)
    samples = read_jsonl(ride / "samples.jsonl")
    closed = [s for s in samples if 90 <= s["t"] <= 135]
    assert len(closed) == 46 and all(s["power"] for s in closed)
    commands = [e for e in read_jsonl(ride / "events.jsonl")
                if e["type"] == "trainer_command" and e["t_ride"]
                and 82 <= e["t_ride"] <= 142]
    assert commands
