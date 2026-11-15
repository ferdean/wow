"""Tap and paint times in timing.jsonl (ICD 4.6.7, 4.9.5): the log on the
stepped clock, and the hub writing it during a ride (S-TIM-01)."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from tests.support.app_rig import AppSession, read_jsonl
from tests.support.page import FakeSocket
from wow.adapters.clock_stepped import DEFAULT_START, SteppedClock
from wow.app.timing_log import TimingLog


class Log:
    def __init__(self) -> None:
        self.clock = SteppedClock()
        self.lines: list[dict[str, Any]] = []
        self.riding = True
        self.pending = False
        self.log = TimingLog(self.clock,
                             lambda line: self.lines.append(dict(line)),
                             lambda: self.riding, lambda: self.pending)


@pytest.mark.case("S-TIM-01")
@pytest.mark.asyncio
async def test_taps_wait_for_their_write() -> None:
    t = Log()
    now_ms = DEFAULT_START * 1000
    t.pending = True
    t.log.tap("resistance", now_ms - 20.0, 22.4, t.log.received())
    t.log.tap("intensity", now_ms - 15.0, None, t.log.received())
    await t.clock.advance(0.3)
    t.log.written(t.clock.monotonic())
    assert [(x["name"], x["write_mono_ms"], x["pending"], x["rtt_ms"])
            for x in t.lines] == [
        ("resistance", now_ms + 300.0, True, 22.4),
        ("intensity", now_ms + 300.0, True, None)]
    t.pending = False
    t.log.tap("skip", now_ms + 280.0, 18.0, t.log.received())
    await t.clock.advance(1.0)
    assert t.lines[-1]["write_mono_ms"] is None
    assert t.lines[-1]["recv_mono_ms"] == now_ms + 300.0


@pytest.mark.case("S-TIM-01")
@pytest.mark.asyncio
async def test_what_is_left_out() -> None:
    t = Log()
    arrival = t.log.received()
    now_ms = DEFAULT_START * 1000
    t.log.tap("open_history", now_ms, 1.0, arrival)
    t.log.tap("resistance", now_ms + 5.0, 1.0, arrival)
    t.log.tap("resistance", None, 1.0, arrival)
    t.log.tap("resistance", True, 1.0, arrival)
    t.riding = False
    t.log.tap("resistance", now_ms, 1.0, arrival)
    t.log.painted(3, 10.0, 12.0, 30.0, 4.0)
    t.riding = True
    t.log.painted(4, None, 12.0, 30.0, 4.0)
    t.log.painted(5, 10.0, 12.0, "soon", 4.0)
    assert t.lines == []
    t.log.painted(6, 10.0, 12.0, 30.0, "x")
    assert t.lines == [{"kind": "paint", "seq": 6, "data_mono_ms": 10.0,
                        "sent_mono_ms": 12.0, "paint_mono_ms": 30.0,
                        "rtt_ms": None}]
    t.log.tap("pause", now_ms, 3.0, arrival)
    await t.log.close()
    assert t.lines[-1]["name"] == "pause"
    assert t.lines[-1]["write_mono_ms"] is None


@pytest.mark.case("S-TIM-01")
@pytest.mark.asyncio
async def test_the_hub_writes_taps_and_paints_during_a_ride(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    session = AppSession(tmp_path)
    app = session.app
    socket = FakeSocket(session.clock)
    page = asyncio.get_running_loop().create_task(
        app.hub.serve(socket, socket.messages()))
    pump = asyncio.get_running_loop().create_task(app.hub.run())
    await session.begin("builtin:erg-check")
    await session.until(10.0)
    assert session.command("switch_mode", mode="resistance") is None
    await session.clock.advance(1.0)
    seq = socket.of_type("view")[-1][1]["seq"]
    for name, extra in (("resistance", {"args": {"step": 1}}),
                        ("intensity", {"args": {"step": 1}})):
        tap = session.clock.monotonic() * 1000 - 25.0
        await socket.incoming.put(json.dumps({
            "type": "command", "id": 7, "name": name, "tap_mono_ms": tap,
            "rtt_ms": 21.0, **extra}))
        await session.clock.advance(0.0)
        await session.clock.advance(1.5)
    view = socket.of_type("view")[-1][1]
    await socket.incoming.put(json.dumps({
        "type": "painted", "seq": view["seq"], "rtt_ms": 21.0,
        "paint_mono_ms": session.clock.monotonic() * 1000}))
    await socket.incoming.put(json.dumps({"type": "painted", "seq": seq - 99,
                                          "paint_mono_ms": 1.0}))
    await socket.incoming.put(json.dumps({"type": "viewport", "width": 402,
                                          "height": 664}))
    await session.clock.advance(1.0)
    assert session.command("finish") is None
    app.recorder.flush()
    await socket.close()
    await page
    pump.cancel()
    await asyncio.gather(pump, return_exceptions=True)
    ride = await session.close()
    lines = read_jsonl(ride / "timing.jsonl")
    moved, unchanged = [x for x in lines if x["kind"] == "tap"]
    assert moved["name"] == "resistance" and moved["rtt_ms"] == 21.0
    assert 0.0 <= moved["write_mono_ms"] - moved["recv_mono_ms"] < 400.0
    assert unchanged["name"] == "intensity"
    assert unchanged["write_mono_ms"] is None
    (paint,) = [x for x in lines if x["kind"] == "paint"]
    assert (paint["seq"], paint["data_mono_ms"], paint["sent_mono_ms"]) == (
        view["seq"], view["data_mono_ms"], view["sent_mono_ms"])
    assert "display viewport 402 x 664" in caplog.text
