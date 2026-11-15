"""The Pi's share of the display latencies, real time (L5 on the Pi):
T-WEB-07 and T-WEB-08.

They measure the Pi, so they run there; WOW_LATENCY_MINUTES shortens
T-WEB-07 for a quick look:

    uv run pytest -m "pi and slow" -s tests/web/test_latency.py
"""

import asyncio
import bisect
import json
import os
import time
from pathlib import Path
from typing import Any

import aiohttp
import pytest

from tests.support.app_rig import app_config, read_jsonl, ride_dirs
from tests.support.page import Page, open_page
from tools import check_ride
from wow.adapters.clock_system import SystemClock
from wow.app.main import App
from wow.core.workout import Block, PowerTarget, PowerUnit, Step, Workout

pytestmark = [pytest.mark.pi, pytest.mark.slow]

STEADY = Workout("test:steady", "Steady for the latency test", None, (
    Block(None, 1, (Step(3600.0, PowerTarget(180, PowerUnit.WATTS),
                         None),)),))
TAP_GAP = 0.7
TAPS = 100


async def riding(app: App, page: Page) -> None:
    assert (await page.command("open_workout", ref=STEADY.ref))["ok"]
    await page.wait_for(lambda m: m["type"] == "view"
                        and m["links"]["trainer"] == "connected",
                        timeout=30.0)
    assert (await page.command("start"))["ok"]
    await page.wait_for(lambda m: m["type"] == "view"
                        and not m["screen"].get("waiting_for_power", True),
                        timeout=30.0)


async def ping(page: Page, number: int) -> float:
    sent = time.monotonic() * 1000
    await page.socket.send_json({"type": "ping", "id": 10_000 + number,
                                 "t_page_ms": sent})
    await page.wait_for(lambda m: m["type"] == "pong"
                        and m["id"] == 10_000 + number)
    return time.monotonic() * 1000 - sent


async def finish(app: App, page: Page) -> Path:
    assert (await page.command("finish"))["ok"]
    await asyncio.sleep(4.0)
    await page.socket.close()
    await app.stop()
    (ride,) = ride_dirs(app.config)
    return ride


@pytest.mark.case("T-WEB-07")
@pytest.mark.req("APP-803")
@pytest.mark.asyncio
async def test_values_reach_a_view_within_120_ms(tmp_path: Path) -> None:
    minutes = float(os.environ.get("WOW_LATENCY_MINUTES", "10"))
    app = App(app_config(tmp_path), SystemClock(None), sim_pedal_after=1.0,
              workouts=[STEADY])
    await app.start()
    async with aiohttp.ClientSession() as session:
        page = await open_page(app, session)
        await riding(app, page)
        await page.collect(minutes * 60)
        ride = await finish(app, page)
    views = sorted((float(m["data_mono_ms"]), float(m["sent_mono_ms"]))
                   for _, m in page.views() if m["data_mono_ms"] is not None)
    shown = [v[0] for v in views]
    arrivals = [float(r["mono_ms"]) for r in read_jsonl(ride / "ble.jsonl")
                if r["op"] == "notify" and r["uuid"] in (
                    check_ride.INDOOR_BIKE_DATA, check_ride.HEART_RATE)
                and float(r["mono_ms"]) <= shown[-1]]
    delays = sorted(views[bisect.bisect_left(shown, a - 1.0)][1] - a
                    for a in arrivals)
    p95 = delays[int(len(delays) * 0.95)]
    print(f"{len(delays)} values: 95 % within {p95:.1f} ms, "
          f"worst {delays[-1]:.1f} ms")
    assert arrivals[-1] - arrivals[0] >= minutes * 60_000 - 5_000
    assert p95 <= 120.0 and delays[-1] <= 250.0


@pytest.mark.case("T-WEB-08")
@pytest.mark.req("APP-802")
@pytest.mark.asyncio
async def test_commands_reach_the_trainer_within_50_ms(
        tmp_path: Path) -> None:
    app = App(app_config(tmp_path), SystemClock(None), sim_pedal_after=1.0,
              workouts=[STEADY])
    await app.start()
    async with aiohttp.ClientSession() as session:
        page = await open_page(app, session)
        await riding(app, page)
        assert (await page.command("switch_mode", mode="resistance"))["ok"]
        for number in range(TAPS):
            rtt = await ping(page, number)
            await page.socket.send_str(json.dumps({
                "type": "command", "id": 20_000 + number,
                "name": "resistance", "args": {"step": 1 - 2 * (number % 2)},
                "tap_mono_ms": time.monotonic() * 1000, "rtt_ms": rtt}))
            await page.collect(TAP_GAP)
        ride = await finish(app, page)
    taps: list[dict[str, Any]] = [
        t for t in read_jsonl(ride / "timing.jsonl") if t["kind"] == "tap"]
    answers = sorted(float(r["mono_ms"]) for r in check_ride.indications(
        read_jsonl(ride / "ble.jsonl")))
    assert len(taps) == TAPS and all(t["write_mono_ms"] for t in taps)
    on_time, delays = 0, []
    for tap in taps:
        written, received = tap["write_mono_ms"], tap["recv_mono_ms"]
        delays.append(written - received)
        index = bisect.bisect_left(answers, received)
        answered = answers[index] if index < len(answers) else None
        on_time += written - received <= 50.0 or (
            tap["pending"] and answered is not None
            and written - answered <= 100.0)
    print(f"{TAPS} taps: {on_time} in time, worst {max(delays):.1f} ms, "
          f"{sum(t['pending'] for t in taps)} while a procedure was pending")
    assert on_time >= 0.95 * TAPS and max(delays) <= 1000.0
