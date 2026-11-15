"""The installed service on the Pi (L6): T-SYS-03, T-SYS-04, T-SYS-06.

Needs wow.service installed by deploy/install.sh, `simulate = true` in
/etc/wow/wow.toml while the tests run, and sudo for systemctl and for
reading /var/lib/wow (run `sudo -v` first):

    uv run pytest -m "pi and slow" -s tests/system/test_service.py
"""

import asyncio
import itertools
import json
import os
import subprocess
import time
from collections.abc import Callable
from typing import Any

import aiohttp
import pytest

URL = os.environ.get("WOW_URL", "https://127.0.0.1")
DATA = os.environ.get("WOW_DATA", "/var/lib/wow")
ERG_CHECK = "builtin:erg-check"
RESTART_LIMIT = 10.0
OFFER_LIMIT = 15.0

pytestmark = [pytest.mark.pi, pytest.mark.slow]


def systemctl(*args: str) -> str:
    return subprocess.run(["sudo", "systemctl", *args], check=True,
                          capture_output=True, text=True).stdout


def main_pid() -> tuple[int, str]:
    out = systemctl("show", "-p", "MainPID", "-p", "ActiveState", "wow")
    values = dict(line.split("=", 1) for line in out.split())
    return int(values["MainPID"]), values["ActiveState"]


def kill() -> float:
    systemctl("kill", "--signal=KILL", "wow")
    return time.monotonic()


async def back_after(old_pid: int, killed: float) -> float:
    while time.monotonic() - killed < 30.0:
        pid, state = main_pid()
        if pid not in (0, old_pid) and state == "active":
            return time.monotonic() - killed
        await asyncio.sleep(0.2)
    raise AssertionError("wow did not come back within 30 s")


def sudo_read(path: str) -> str:
    return subprocess.run(["sudo", "cat", path], check=True,
                          capture_output=True, text=True).stdout


class Page:
    """A display connection to the service."""

    def __init__(self, session: aiohttp.ClientSession,
                 socket: aiohttp.ClientWebSocketResponse) -> None:
        self._session, self._socket = session, socket
        self._ids = itertools.count(1)
        self.view: dict[str, Any] = {}

    @classmethod
    async def open(cls, limit: float = 60.0) -> "Page":
        started = time.monotonic()
        while True:
            session = aiohttp.ClientSession()
            try:
                socket = await session.ws_connect(f"{URL}/ws", ssl=False)
                page = cls(session, socket)
                await page.until(lambda v: True, 10.0)
                return page
            except (aiohttp.ClientError, OSError, AssertionError):
                await session.close()
                if time.monotonic() - started > limit:
                    raise
                await asyncio.sleep(0.5)

    async def until(self, check: Callable[[dict[str, Any]], bool],
                    limit: float) -> dict[str, Any]:
        end = time.monotonic() + limit
        while time.monotonic() < end:
            try:
                message = await self._socket.receive_json(
                    timeout=max(0.1, end - time.monotonic()))
            except TimeoutError:
                break
            if message.get("type") == "view":
                view: dict[str, Any] = message
                self.view = view
                if check(view):
                    return view
        raise AssertionError(f"view not reached; last: {self.view}")

    async def command(self, name: str, **args: Any) -> None:
        await self._socket.send_json({"type": "command",
                                      "id": next(self._ids), "name": name,
                                      "args": args})

    async def close(self) -> None:
        await self._socket.close()
        await self._session.close()


def screen(view: dict[str, Any]) -> dict[str, Any]:
    value: dict[str, Any] = view["screen"]
    return value


async def ride_running(page: Page) -> str:
    await page.until(lambda v: screen(v)["name"] == "home", 30.0)
    await page.command("open_workout", ref=ERG_CHECK)
    await page.until(lambda v: v["links"]["trainer"] == "connected", 30.0)
    await page.command("start")
    await page.until(lambda v: screen(v)["name"] == "ride" and not screen(v)[
        "waiting_for_power"], 30.0)
    rides = sudo_read_dir(f"{DATA}/rides")
    return rides[-1]


def sudo_read_dir(path: str) -> list[str]:
    out = subprocess.run(["sudo", "ls", "-1", path], check=True,
                         capture_output=True, text=True).stdout
    return sorted(out.split())


async def finish_offer(page: Page) -> None:
    await page.until(lambda v: screen(v)["name"] == "home" and screen(v)[
        "recovery"] is not None, 30.0)
    await page.command("recovery_finish")
    await page.until(lambda v: screen(v)["name"] == "summary", 15.0)
    await page.command("back")


@pytest.mark.case("T-SYS-03")
@pytest.mark.req("APP-811")
@pytest.mark.asyncio
async def test_restarted_within_10_s_after_kill_9() -> None:
    times = []
    for _ in range(5):
        pid, state = main_pid()
        assert state == "active"
        times.append(await back_after(pid, kill()))
        await asyncio.sleep(3.0)
    print("restart times:", [round(t, 1) for t in times])
    assert max(times) <= RESTART_LIMIT


@pytest.mark.case("T-SYS-06")
@pytest.mark.req("APP-809", "APP-811")
@pytest.mark.asyncio
async def test_kill_during_a_ride_offers_it_and_continue_works() -> None:
    page = await Page.open()
    ride_id = await ride_running(page)
    await asyncio.sleep(20.0)
    pid, _ = main_pid()
    killed = kill()
    await page.close()
    await back_after(pid, killed)
    page = await Page.open(limit=OFFER_LIMIT)
    view = await page.until(lambda v: screen(v)["name"] == "home" and screen(
        v)["recovery"] is not None, OFFER_LIMIT)
    offered = time.monotonic() - killed
    print(f"offered after {offered:.1f} s: {screen(view)['recovery']}")
    assert offered <= OFFER_LIMIT
    assert screen(view)["recovery"]["ride_id"] == ride_id
    await page.command("recovery_continue")
    await page.until(lambda v: screen(v)["name"] == "ride", 10.0)
    await page.until(lambda v: v["links"]["trainer"] == "connected", 30.0)
    await page.command("finish")
    await page.until(lambda v: screen(v)["name"] == "summary", 15.0)
    await page.command("back")
    await page.close()
    journal = sudo_read(f"{DATA}/rides/{ride_id}/events.jsonl")
    assert '"type": "recovered"' in journal


@pytest.mark.case("T-SYS-04")
@pytest.mark.req("APP-320")
@pytest.mark.asyncio
async def test_stop_during_a_ride_leaves_the_lowest_level() -> None:
    page = await Page.open()
    ride_id = await ride_running(page)
    await asyncio.sleep(10.0)
    await page.close()
    systemctl("stop", "wow")
    lines = [json.loads(line) for line in sudo_read(
        f"{DATA}/rides/{ride_id}/ble.jsonl").splitlines() if line]
    trainer = [r for r in lines if r.get("dev") == "trainer"]
    writes = [i for i, r in enumerate(trainer) if r["op"] == "write"
              and r["uuid"].startswith("00002ad9")]
    assert trainer[writes[-1]]["hex"].startswith("04")
    after = [r["op"] for r in trainer[writes[-1]:]]
    assert "disconnected" in after
    systemctl("start", "wow")
    page = await Page.open()
    await finish_offer(page)
    await page.close()
