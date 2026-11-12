"""System tests on the Pi, real time, simulated devices (L6).

T-SYS-01 runs 60 minutes; set WOW_SYS_MINUTES for a shorter look:

    WOW_SYS_MINUTES=5 uv run pytest -m "pi and slow" tests/system
"""

import asyncio
import os
import time
from pathlib import Path

import aiohttp
import pytest

from tests.support.app_rig import app_config, read_jsonl, ride_dirs
from tests.support.page import open_page
from tools import check_ride
from wow.adapters.clock_system import SystemClock
from wow.app.main import App
from wow.core.workout import Block, PowerTarget, PowerUnit, Step, Workout

PING_INTERVAL = 5.0


def thirty_thirty(minutes: float) -> Workout:
    pairs = max(1, round(minutes))
    return Workout(
        "test:sys-3030",
        "30/30 for the system test",
        None,
        (
            Block(
                "30/30",
                pairs,
                (
                    Step(30.0, PowerTarget(330, PowerUnit.WATTS), None),
                    Step(30.0, PowerTarget(140, PowerUnit.WATTS), None),
                ),
            ),
        ),
    )


@pytest.mark.case("T-SYS-01")
@pytest.mark.req("APP-801")
@pytest.mark.pi
@pytest.mark.slow
@pytest.mark.asyncio
async def test_real_time_interval_ride_with_a_display(tmp_path: Path) -> None:
    minutes = float(os.environ.get("WOW_SYS_MINUTES", "60"))
    workout = thirty_thirty(minutes)
    app = App(
        app_config(tmp_path),
        SystemClock(None),
        sim_pedal_after=1.0,
        workouts=[workout],
    )
    await app.start()
    try:
        async with aiohttp.ClientSession() as session:
            page = await open_page(app, session)
            assert (await page.command("open_workout", ref=workout.ref))["ok"]
            await page.wait_for(
                lambda m: (
                    m["type"] == "view"
                    and m["links"]["trainer"] == "connected"
                ),
                timeout=30.0,
            )
            assert (await page.command("start"))["ok"]
            end = time.monotonic() + minutes * 60 + 5.0
            ping = 0
            while time.monotonic() < end:
                ping += 1
                await page.socket.send_json(
                    {
                        "type": "ping",
                        "id": ping,
                        "t_page_ms": time.monotonic() * 1000,
                    }
                )
                await page.collect(min(PING_INTERVAL, end - time.monotonic()))
            assert (await page.command("finish"))["ok"]
            await asyncio.sleep(4.0)
            await page.socket.close()
    finally:
        await app.stop()
    (ride,) = ride_dirs(app.config)
    outcome = check_ride.rr02(
        read_jsonl(ride / "events.jsonl"),
        read_jsonl(ride / "ble.jsonl"),
        read_jsonl(app.config.data / "logs" / "ble-system.jsonl"),
    )
    print(outcome.line(), f"loop lag worst {app.lag.worst * 1000:.1f} ms")
    assert outcome.result == "pass"
    assert app.lag.late == 0
