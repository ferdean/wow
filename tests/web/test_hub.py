"""Display WebSocket (ICD IF-06): message parsing and the view pump on the
stepped clock, then the real socket on localhost (L5)."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from tests.support.app_rig import ERG_CHECK, ROOT, app_config
from tests.support.page import open_page
from wow.adapters.clock_stepped import SteppedClock
from wow.adapters.clock_system import SystemClock
from wow.app.main import App
from wow.web.hub import Command, Hub, Malformed, Painted, Ping, parse_up

GOLDEN = ROOT / "testdata" / "display"


@pytest.mark.case("S-HUB-01")
@pytest.mark.parametrize("text, expected", [
    ('{"type": "command", "id": 3, "name": "skip"}', Command(3, "skip", {})),
    ('{"type": "command", "id": 4, "name": "intensity", "args": {"step": 1},'
     ' "tap_mono_ms": 12.5}', Command(4, "intensity", {"step": 1})),
    ('{"type": "ping", "id": 9, "t_page_ms": 1234.5}', Ping(9, 1234.5)),
    ('{"type": "painted", "seq": 18, "paint_mono_ms": 5.0}', Painted(18)),
    ("{", Malformed(None, "not JSON")),
    ("[1, 2]", Malformed(None, "not an object")),
    ('{"type": "command", "id": true, "name": "skip"}',
     Malformed(None, "bad command")),
    ('{"type": "command", "id": 5}', Malformed(5, "bad command")),
    ('{"type": "command", "id": 6, "name": "x", "args": [1]}',
     Malformed(6, "bad command")),
    ('{"type": "ping", "id": 7, "t_page_ms": "now"}',
     Malformed(7, "bad ping")),
    ('{"type": "dance", "id": 8}',
     Malformed(8, "unknown message type 'dance'")),
])
def test_page_messages_are_parsed(text: str, expected: object) -> None:
    assert parse_up(text) == expected


class FakeSource:
    def __init__(self) -> None:
        self.plan_id: str | None = None
        self.commands: list[str] = []

    def view(self) -> dict[str, Any]:
        return {"screen": {"name": "home"}}

    def plan(self) -> dict[str, Any] | None:
        if self.plan_id is None:
            return None
        return {"type": "plan", "plan_id": self.plan_id}

    def command(self, name: str, args: Mapping[str, Any]) -> str | None:
        self.commands.append(name)
        return None if name == "start" else "invalid_state"


class FakeSocket:
    def __init__(self, clock: SteppedClock) -> None:
        self._clock = clock
        self.sent: list[tuple[float, dict[str, Any]]] = []
        self.incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self.closed = False

    async def send_str(self, data: str) -> None:
        self.sent.append((self._clock.monotonic(), json.loads(data)))

    async def close(self, *, code: int = 1000, message: bytes = b"") -> bool:
        self.closed = True
        await self.incoming.put(None)
        return True

    async def messages(self) -> AsyncIterator[str]:
        while (text := await self.incoming.get()) is not None:
            yield text

    def of_type(self, kind: str) -> list[tuple[float, dict[str, Any]]]:
        return [(t, m) for t, m in self.sent if m["type"] == kind]


async def _connected(clock: SteppedClock, source: FakeSource
                     ) -> tuple[Hub, FakeSocket, asyncio.Task[None],
                                asyncio.Task[None]]:
    hub = Hub(clock, source, "0.2.0")
    socket = FakeSocket(clock)
    serving = asyncio.ensure_future(hub.serve(socket, socket.messages()))
    pump = asyncio.ensure_future(hub.run())
    await clock.settle()
    return hub, socket, serving, pump


async def _stop(hub: Hub, serving: asyncio.Task[None],
                pump: asyncio.Task[None]) -> None:
    await hub.close()
    pump.cancel()
    await asyncio.gather(serving, pump, return_exceptions=True)


@pytest.mark.case("S-HUB-02")
@pytest.mark.asyncio
async def test_hello_first_then_a_view_every_second() -> None:
    clock = SteppedClock()
    hub, socket, serving, pump = await _connected(clock, FakeSource())
    await clock.advance(10.0)
    await _stop(hub, serving, pump)
    assert socket.sent[0][1] == {"type": "hello", "app_version": "0.2.0",
                                 "protocol": 1}
    views = socket.of_type("view")
    assert [m["seq"] for _, m in views] == list(range(1, len(views) + 1))
    gaps = [b - a for (a, _), (b, _) in zip(views, views[1:])]
    assert gaps and max(gaps) <= 1.0 + 1e-9
    assert len(views) >= 10


@pytest.mark.case("S-HUB-02")
@pytest.mark.asyncio
async def test_changes_are_coalesced_to_ten_views_a_second() -> None:
    clock = SteppedClock()
    hub, socket, serving, pump = await _connected(clock, FakeSource())
    start = clock.monotonic()
    for _ in range(200):
        hub.changed()
        await clock.advance(0.01)
    await _stop(hub, serving, pump)
    times = [t for t, _ in socket.of_type("view") if t > start]
    assert 18 <= len(times) <= 21
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert min(gaps) >= 0.1 - 1e-9


@pytest.mark.case("S-HUB-02")
@pytest.mark.asyncio
async def test_a_change_is_sent_within_a_tenth_of_a_second() -> None:
    clock = SteppedClock()
    hub, socket, serving, pump = await _connected(clock, FakeSource())
    await clock.advance(0.5)
    changed_at = clock.monotonic()
    hub.changed()
    await clock.advance(0.2)
    await _stop(hub, serving, pump)
    after = [t for t, _ in socket.of_type("view") if t >= changed_at]
    assert after and after[0] - changed_at <= 0.1 + 1e-9


@pytest.mark.case("S-HUB-02")
@pytest.mark.asyncio
async def test_plan_goes_before_the_view_that_needs_it() -> None:
    clock = SteppedClock()
    source = FakeSource()
    source.plan_id = "a@250"
    hub, socket, serving, pump = await _connected(clock, source)
    await clock.advance(1.5)
    source.plan_id = "b@250"
    hub.changed()
    await clock.advance(1.5)
    await socket.incoming.put('{"type": "command", "id": 1, "name": "start"}')
    await socket.incoming.put('{"type": "command", "id": 2, "name": "skip"}')
    await socket.incoming.put('{"type": "ping", "id": 3, "t_page_ms": 7.5}')
    await socket.incoming.put('{"type": "painted", "seq": 2}')
    await clock.advance(0.5)
    await _stop(hub, serving, pump)
    kinds = [m["type"] for _, m in socket.sent]
    assert kinds[:3] == ["hello", "plan", "view"]
    assert [m["plan_id"] for _, m in socket.of_type("plan")] == [
        "a@250", "b@250"]
    acks = [m for _, m in socket.of_type("ack")]
    assert acks == [{"type": "ack", "id": 1, "ok": True},
                    {"type": "ack", "id": 2, "ok": False,
                     "error": "invalid_state"}]
    (pong,) = [m for _, m in socket.of_type("pong")]
    assert pong["id"] == 3 and pong["t_page_ms"] == 7.5
    assert pong["pi_mono_ms"] == pytest.approx(clock.monotonic() * 1000,
                                               abs=600)
    assert socket.closed


def _keys(view: dict[str, Any]) -> tuple[set[str], set[str]]:
    return set(view), set(view["screen"])


@pytest.mark.case("T-WEB-04")
@pytest.mark.req("APP-807", "APP-803")
@pytest.mark.asyncio
async def test_views_during_a_simulated_ride(tmp_path: Path) -> None:
    app = App(app_config(tmp_path), SystemClock(None), sim_pedal_after=0.5)
    await app.start()
    try:
        async with aiohttp.ClientSession() as session:
            page = await open_page(app, session)
            assert (await page.command("open_workout", ref=ERG_CHECK))["ok"]
            await page.wait_for(lambda m: m["type"] == "view"
                                and m["links"]["trainer"] == "connected",
                                timeout=15.0)
            assert (await page.command("start"))["ok"]
            await page.wait_for(lambda m: m["type"] == "view"
                                and m["screen"]["name"] == "ride"
                                and not m["screen"]["waiting_for_power"])
            mark = time.monotonic()
            await page.collect(3.0)
            assert (await page.command("finish"))["ok"]
            await page.socket.close()
    finally:
        await app.stop()
    views = page.views()
    seqs = [m["seq"] for _, m in views]
    assert seqs == list(range(1, len(seqs) + 1))
    assert {m["type"] for _, m in page.received[:3]} >= {"hello"}
    golden_ride = json.loads((GOLDEN / "ride_erg.view.json").read_text())
    golden_home = json.loads((GOLDEN / "home.view.json").read_text())
    golden_pre = json.loads((GOLDEN / "pre_ride.view.json").read_text())
    shapes = {g["screen"]["name"]: _keys(g)
              for g in (golden_ride, golden_home, golden_pre)}
    for _, view in views:
        assert _keys(view) == shapes[view["screen"]["name"]]
    window = [t for t, _ in views if mark <= t <= mark + 3.0]
    assert 3 <= len(window) <= 30
    gaps = [b - a for a, b in zip(window, window[1:])]
    assert max(gaps) <= 1.0 + 0.25


@pytest.mark.case("T-WEB-06")
@pytest.mark.asyncio
async def test_bad_commands_are_refused_and_change_nothing(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    app = App(app_config(tmp_path), SystemClock(None))
    await app.start()
    try:
        async with aiohttp.ClientSession() as session:
            page = await open_page(app, session)
            before = await page.wait_for(lambda m: m["type"] == "view")
            ack = await page.command("start")
            assert ack == {"type": "ack", "id": 1, "ok": False,
                           "error": "invalid_state"}
            ack = await page.command("warp")
            assert ack["error"] == "bad_request"
            await page.socket.send_str("{not json")
            await page.socket.send_str('{"type": "command", "id": 77}')
            bad = await page.wait_for(lambda m: m["type"] == "ack"
                                      and m["id"] == 77)
            assert bad == {"type": "ack", "id": 77, "ok": False,
                           "error": "bad_request"}
            after = await page.wait_for(lambda m: m["type"] == "view")
            assert after["screen"] == before["screen"]
            assert app.console.screen == "home"
            await page.socket.close()
    finally:
        await app.stop()
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "command start refused: invalid_state" in logged
    assert "command warp refused: bad_request" in logged
    assert "not JSON" in logged and "bad command" in logged
