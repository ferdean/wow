"""Crash recovery in the app shell (L3, T-RCV-01 to T-RCV-05).

A crash is a copy of the data directory taken mid-ride, after the
recorder has written everything queued: what a kill leaves on disk. A
second app starts on the copy, in the same boot or another one.
"""

import json
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from garmin_fit_sdk import Decoder, Stream

from tests.support.app_rig import (
    ERG_CHECK, AppSession, app_config, read_jsonl, ride_dirs,
)
from tests.support.routes import climb, gpx
from wow.adapters.clock_stepped import SteppedClock
from wow.app.main import App
from wow.core.ride import RidePhase

GAP = 20.0


class Restarted:
    """The app started again on what the first one left on disk."""

    def __init__(self, first: AppSession, tmp: Path, gap: float = GAP,
                 boot: str | None = None, synchronised: bool = True) -> None:
        first.app.recorder.flush()
        shutil.copytree(first.app.config.data, tmp / "data")
        self.clock = SteppedClock(
            first.clock.monotonic() + gap if boot is None else 50.0,
            first.clock.utc() + timedelta(seconds=gap), synchronised)
        self.app = App(app_config(tmp), self.clock,
                       boot=boot or first.app.recorder.boot_id)

    async def start(self) -> dict[str, Any]:
        await self.app.start()
        return self.home()

    def home(self) -> dict[str, Any]:
        screen: dict[str, Any] = self.app.console.view()["screen"]
        return screen

    def command(self, name: str) -> str | None:
        return self.app.console.command(name, {})

    async def close(self) -> Path:
        await self.clock.advance(5.0)
        await self.clock.drive(self.app.devices.close(), limit=60.0)
        await self.clock.drive(self.app.rides.close(), limit=60.0)
        if self.app.scheduler is not None:
            await self.app.scheduler.close()
        await self.app.hub.close()
        await self.app.web.stop()
        self.app.recorder.stop()
        return ride_dirs(self.app.config)[-1]


async def riding(tmp: Path, until: float = 130.0) -> AppSession:
    session = AppSession(tmp / "first")
    await session.begin(ERG_CHECK)
    await session.until(until)
    return session


def journal(ride: Path, kind: str) -> list[dict[str, Any]]:
    return [r for r in read_jsonl(ride / "events.jsonl")
            if r["type"] == kind]


@pytest.mark.case("T-RCV-01")
@pytest.mark.req("APP-809")
@pytest.mark.asyncio
async def test_home_offers_the_ride_with_the_outage(tmp_path: Path) -> None:
    first = await riding(tmp_path)
    again = Restarted(first, tmp_path / "again")
    offer = (await again.start())["recovery"]
    assert offer["ride_id"] == ride_dirs(first.app.config)[-1].name
    assert offer["can_continue"] is True
    assert offer["outage"] == pytest.approx(GAP, abs=1.1)
    await again.clock.advance(10.0)
    assert again.home()["recovery"]["outage"] == pytest.approx(
        GAP + 10.0, abs=1.1)
    await again.close()
    await first.close()


@pytest.mark.case("T-RCV-02")
@pytest.mark.req("APP-809", "APP-318")
@pytest.mark.asyncio
async def test_continue_rides_on_in_the_same_directory(
        tmp_path: Path) -> None:
    first = await riding(tmp_path)
    crash_t = first.ride_time()
    again = Restarted(first, tmp_path / "again")
    await again.start()
    await first.until(crash_t + GAP + 30.0)
    assert again.command("recovery_continue") is None
    assert again.app.console.screen == "ride"
    await again.clock.advance(30.0)
    ride = again.app.rides.ride
    now = again.clock.monotonic()
    assert ride.ride_time(now) == pytest.approx(crash_t + GAP + 30.0, abs=1.1)
    assert ride.step == first.app.rides.ride.step
    assert again.command("finish") is None
    ride_dir = await again.close()
    await first.close()
    assert ride_dir.name == ride_dirs(first.app.config)[-1].name
    assert len(ride_dirs(again.app.config)) == 1
    recovered = journal(ride_dir, "recovered")
    assert len(recovered) == 1
    assert recovered[0]["outage"] == pytest.approx(GAP, abs=1.1)
    starts = [r["t_ride"] for r in journal(ride_dir, "dropout_start")
              if r["device"] == "trainer"]
    assert starts and starts[-1] == pytest.approx(crash_t, abs=1.1)
    seconds = [s["t"] for s in read_jsonl(ride_dir / "samples.jsonl")]
    assert seconds == list(range(len(seconds)))
    gap = [s for s in read_jsonl(ride_dir / "samples.jsonl")
           if crash_t + 2 < s["t"] < crash_t + GAP - 2]
    assert gap and all(s["power"] is None for s in gap)
    assert (ride_dir / "ride.fit").exists()
    meta = json.loads((ride_dir / "meta.json").read_text())
    assert meta["state"] == "finished"


@pytest.mark.case("T-RCV-03")
@pytest.mark.req("APP-809")
@pytest.mark.asyncio
async def test_finish_from_the_offer_writes_the_files(
        tmp_path: Path) -> None:
    first = await riding(tmp_path)
    crash_t = first.ride_time()
    again = Restarted(first, tmp_path / "again")
    await again.start()
    assert again.command("recovery_finish") is None
    await again.clock.advance(1.0)
    assert again.app.console.screen == "summary"
    assert again.command("back") is None
    assert again.home()["recovery"] is None
    ride_dir = await again.close()
    await first.close()
    meta = json.loads((ride_dir / "meta.json").read_text())
    assert meta["state"] == "finished"
    assert meta["metrics"]["duration"] == pytest.approx(crash_t, abs=2)
    assert (ride_dir / "ride.fit").exists()
    assert journal(ride_dir, "finished")[0]["t_ride"] == pytest.approx(
        crash_t, abs=1.1)


@pytest.mark.case("T-RCV-04")
@pytest.mark.req("APP-809")
@pytest.mark.asyncio
async def test_after_a_reboot_the_outage_comes_from_utc(
        tmp_path: Path) -> None:
    first = await riding(tmp_path)
    again = Restarted(first, tmp_path / "synced", gap=90.0, boot="other")
    offer = (await again.start())["recovery"]
    assert offer["can_continue"] is True
    assert offer["outage"] == pytest.approx(90.0, abs=1.1)
    await again.close()
    blind = Restarted(first, tmp_path / "blind", gap=90.0, boot="other",
                      synchronised=False)
    offer = (await blind.start())["recovery"]
    assert (offer["can_continue"], offer["outage"]) == (False, None)
    assert blind.command("recovery_continue") == "invalid_state"
    assert blind.command("recovery_finish") is None
    await blind.close()
    await first.close()


@pytest.mark.case("T-RCV-05")
@pytest.mark.req("APP-809")
@pytest.mark.asyncio
async def test_armed_is_cancelled_and_paused_is_offered(
        tmp_path: Path) -> None:
    waiting = AppSession(tmp_path / "armed", sim_pedal_after=1e6)
    await waiting.begin(ERG_CHECK)
    await waiting.clock.advance(5.0)
    again = Restarted(waiting, tmp_path / "armed-again")
    assert (await again.start())["recovery"] is None
    meta = json.loads((ride_dirs(again.app.config)[-1] / "meta.json")
                      .read_text())
    assert meta["state"] == "cancelled"
    await again.close()
    await waiting.close()
    paused = await riding(tmp_path / "paused", until=100.0)
    assert paused.command("pause") is None
    await paused.clock.advance(10.0)
    later = Restarted(paused, tmp_path / "paused-again")
    assert (await later.start())["recovery"]["can_continue"] is True
    assert later.command("recovery_continue") is None
    await later.clock.advance(20.0)
    ride = later.app.rides.ride
    assert ride.phase == RidePhase.PAUSED
    assert ride.ride_time(later.clock.monotonic()) == pytest.approx(
        100.0, abs=1.1)
    assert later.command("resume") is None
    await later.clock.advance(5.0)
    assert ride.ride_time(later.clock.monotonic()) == pytest.approx(
        105.0, abs=1.1)
    await later.close()
    await paused.close()


@pytest.mark.case("T-RCV-06")
@pytest.mark.req("APP-908")
@pytest.mark.asyncio
async def test_a_recovered_ride_keeps_its_route(tmp_path: Path) -> None:
    folder = tmp_path / "first" / "data" / "routes"
    folder.mkdir(parents=True)
    (folder / "ramp.gpx").write_bytes(gpx(climb(3000, 0.04), "Ramp"))
    first = AppSession(tmp_path / "first")
    assert first.command("open_workout", ref=ERG_CHECK) is None
    await first.app.routes.refresh()
    assert first.command("set_route", file="ramp.gpx") is None
    await first.clock.advance(15.0)
    assert first.command("start") is None
    await first.until(130.0)
    (folder / "ramp.gpx").unlink()
    again = Restarted(first, tmp_path / "again")
    await again.start()
    assert again.command("recovery_continue") is None
    await again.clock.advance(60.0)
    assert again.command("finish") is None
    ride_dir = await again.close()
    await first.close()
    meta = json.loads((ride_dir / "meta.json").read_text())
    assert meta["route"]["name"] == "Ramp" and meta["rider_kg"] == 75
    assert meta["route"]["distance_m"] > 500
    samples = read_jsonl(ride_dir / "samples.jsonl")
    data = bytearray((ride_dir / "ride.fit").read_bytes())
    records = Decoder(Stream.from_byte_array(data)).read()[0]["record_mesgs"]
    assert len(records) == len(samples)
    assert all("distance" in r for r in records)
