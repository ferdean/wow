"""Past rides: history, download, delete, storage (L3, L5).

T-VIEW-07, T-WEB-03, T-REC-06, T-HK-01.
"""

import json
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp import web

from tests.app.test_uploads import make_ride, meta
from tests.support.app_rig import AppSession, app_config
from wow.adapters.clock_stepped import SteppedClock
from wow.app.history import fit_name
from wow.app.main import App
from wow.web.server import https_app

METRICS = {"duration": 3600, "avg_power": 180.0, "max_power": 330,
           "np": 190.0, "intensity_factor": 0.76, "tss": 57.84,
           "work_kj": 648.0, "time_in_zone": [0, 0, 3600, 0, 0, 0],
           "avg_hr_bpm": 130.0, "max_hr_bpm": 150}


def kept(rides: Path, ride_id: str, state: str = "finished",
         upload: str = "done", title: str = "Long ride + SS") -> Path:
    ride_dir = make_ride(rides, ride_id, upload)
    data = meta(ride_dir)
    data.update({"state": state, "title": title, "metrics": METRICS,
                 "start_utc": ride_id[:10] + "T17:40:48.000Z"})
    (ride_dir / "meta.json").write_text(json.dumps(data))
    return ride_dir


def screen(session: AppSession) -> dict[str, Any]:
    value: dict[str, Any] = session.app.console.view()["screen"]
    return value


@pytest.mark.case("T-VIEW-07")
@pytest.mark.req("APP-611")
def test_history_lists_the_kept_rides(tmp_path: Path) -> None:
    rides = tmp_path / "data" / "rides"
    kept(rides, "2026-11-12T162426Z", upload="failed")
    kept(rides, "2026-11-13T170154Z", state="discarded")
    kept(rides, "2026-11-14T180000Z", upload="off", title="Free ride")
    session = AppSession(tmp_path)
    assert session.command("open_history") is None
    history = screen(session)
    assert history["name"] == "history"
    assert history["rides"] == [
        {"ride_id": "2026-11-14T180000Z",
         "start_utc": "2026-11-14T17:40:48.000Z", "title": "Free ride",
         "duration": 3600, "tss": 57.8, "upload": "off",
         "garmin_upload": None},
        {"ride_id": "2026-11-12T162426Z",
         "start_utc": "2026-11-12T17:40:48.000Z",
         "title": "Long ride + SS", "duration": 3600, "tss": 57.8,
         "upload": "failed", "garmin_upload": None}]
    assert history["free_mb"] > 0
    assert session.command("open_ride",
                           ride_id="2026-11-12T162426Z") is None
    summary = screen(session)
    assert (summary["name"], summary["upload"]) == ("summary", "failed")
    assert summary["metrics"]["np"] == 190
    assert session.command("back") is None
    assert screen(session)["name"] == "history"


@pytest.mark.case("T-WEB-03")
@pytest.mark.req("APP-610")
@pytest.mark.asyncio
async def test_a_ride_file_downloads_as_an_attachment(tmp_path: Path) -> None:
    ride_dir = kept(tmp_path, "2026-11-13T170154Z")

    async def no_socket(_request: web.Request) -> web.StreamResponse:
        return web.Response(status=400)

    runner = web.AppRunner(https_app(tmp_path / "static", no_socket,
                                     tmp_path))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = f"http://127.0.0.1:{runner.addresses[0][1]}"
    try:
        async with aiohttp.ClientSession() as client:
            async with client.get(
                    f"{base}/rides/2026-11-13T170154Z/ride.fit") as response:
                assert response.status == 200
                assert await response.read() == b"fit"
                assert response.headers["Content-Disposition"] == (
                    'attachment; filename='
                    '"wow-2026-11-13-Long-ride-SS.fit"')
            for path in ("/rides/2026-11-01T000000Z/ride.fit",
                         "/rides/..%2Fsecrets/ride.fit"):
                async with client.get(base + path) as response:
                    assert response.status == 404
    finally:
        await runner.cleanup()
    assert fit_name(meta(ride_dir)) == "wow-2026-11-13-Long-ride-SS.fit"


@pytest.mark.case("T-REC-06")
@pytest.mark.req("APP-612")
@pytest.mark.asyncio
async def test_nothing_is_removed_without_the_rider(tmp_path: Path) -> None:
    rides = tmp_path / "data" / "rides"
    ids = [f"2026-{1 + i // 280:02d}-{1 + i % 28:02d}T{i % 24:02d}"
           f"{i % 60:02d}{i // 60 % 60:02d}Z" for i in range(1000)]
    for i, ride_id in enumerate(ids):
        kept(rides, ride_id, upload="failed" if i % 10 == 0 else "done")
    clock = SteppedClock()
    app = App(app_config(tmp_path), clock)
    await app.start()
    await clock.advance(60.0)
    assert len(list(rides.iterdir())) == 1000
    assert app.console.command("open_history", {}) is None
    assert len(app.console.view()["screen"]["rides"]) == 1000
    assert app.console.command("delete_ride", {"ride_id": ids[5]}) is None
    assert sorted(p.name for p in rides.iterdir()) == sorted(
        set(ids) - {ids[5]})
    assert app.console.command("delete_ride",
                               {"ride_id": "../settings"}) == "bad_request"
    await clock.drive(app.stop(), limit=60.0)


@pytest.mark.case("T-HK-01")
@pytest.mark.req("APP-612")
@pytest.mark.parametrize("free, warned", [(990_000_000, True),
                                          (1_010_000_000, False)])
def test_storage_low_below_one_gigabyte(tmp_path: Path, free: int,
                                        warned: bool) -> None:
    app = App(app_config(tmp_path), SteppedClock(),
              free_bytes=lambda _path: free)
    warnings = app.console.view()["warnings"]
    expected = [{"kind": "storage_low", "free_mb": free // 1_000_000}]
    assert (warnings == expected) is warned
    if not warned:
        assert warnings == []
