"""Routes in the app shell: listing, choosing, riding, the live ride (L3,
SL-13, SL-14)."""

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

import pytest
from garmin_fit_sdk import Decoder, Stream

from tests.app.test_recovery import Restarted
from tests.support.app_rig import ERG_CHECK, AppSession, read_jsonl
from tests.support.routes import climb, gpx, loop
from wow.app import route_catalog
from wow.app.route_catalog import RouteCatalog, RouteEntry

LOOP = gpx(loop(), "Lake loop")
CLIMB = gpx(climb(3000, 0.05), "Test climb")


def put_routes(tmp: Path, files: dict[str, bytes]) -> Path:
    folder = tmp / "data" / "routes"
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return folder


async def pre_ride(session: AppSession, ref: str | None = ERG_CHECK
                   ) -> dict[str, Any]:
    if ref is None:
        assert session.command("open_free_ride") is None
    else:
        assert session.command("open_workout", ref=ref) is None
    await session.clock.drive(session.app.routes.refresh(), limit=60.0)
    return screen(session)


def screen(session: AppSession) -> dict[str, Any]:
    found: dict[str, Any] = session.app.console.view()["screen"]
    return found


async def settle(session: AppSession) -> None:
    session.app.recorder.flush()
    for _ in range(5):
        await asyncio.sleep(0)


def decode(path: Path) -> Any:
    data = bytearray(path.read_bytes())
    messages, errors = Decoder(Stream.from_byte_array(data)).read()
    assert errors == []
    return messages


@pytest.mark.case("T-RTE-04")
@pytest.mark.req("APP-901", "APP-907")
@pytest.mark.asyncio
async def test_pre_ride_lists_the_usable_routes_by_name(
        tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    put_routes(tmp_path, {"b-loop.gpx": LOOP, "a-climb.GPX": CLIMB,
                          "broken.gpx": b"<gpx", "notes.txt": LOOP,
                          ".hidden.gpx": LOOP,
                          "tiny.gpx": gpx(climb(60, 0.0))})
    session = AppSession(tmp_path)
    caplog.set_level(logging.WARNING)
    found = await pre_ride(session)
    assert [(r["file"], r["name"]) for r in found["routes"]] == [
        ("b-loop.gpx", "Lake loop"), ("a-climb.GPX", "Test climb")]
    lake = found["routes"][0]
    assert lake["length_m"] == pytest.approx(9425, abs=10)
    assert lake["ascent_m"] == 40
    assert found["route"] is None
    left_out = [r.getMessage() for r in caplog.records]
    assert any("broken.gpx left out: not XML" in m for m in left_out)
    assert any("tiny.gpx left out: shorter than 100 m" in m for m in left_out)
    await session.close()


@pytest.mark.case("T-RTE-05")
@pytest.mark.req("APP-902")
@pytest.mark.asyncio
async def test_the_route_chosen_on_pre_ride_is_kept(tmp_path: Path) -> None:
    folder = put_routes(tmp_path, {"b-loop.gpx": LOOP, "a-climb.gpx": CLIMB})
    session = AppSession(tmp_path)
    await pre_ride(session)
    assert session.command("set_route", file="nope.gpx") == "bad_request"
    assert session.command("set_route", file="b-loop.gpx") is None
    assert screen(session)["route"] == "b-loop.gpx"
    await settle(session)
    stored = json.loads((tmp_path / "data" / "settings.json").read_text())
    assert stored["route"] == "b-loop.gpx"
    assert session.command("back") is None
    free = await pre_ride(session, None)
    assert free["free_ride"] and free["route"] == "b-loop.gpx"
    await session.close()
    again = AppSession(tmp_path)
    assert (await pre_ride(again))["route"] == "b-loop.gpx"
    assert again.command("set_route", file=None) is None
    assert screen(again)["route"] is None
    assert again.command("set_route", file="a-climb.gpx") is None
    (folder / "a-climb.gpx").unlink()
    assert again.command("back") is None
    assert (await pre_ride(again))["route"] is None
    await again.close()


@pytest.mark.case("T-RTE-06")
@pytest.mark.req("APP-903", "APP-904", "APP-906")
@pytest.mark.asyncio
async def test_a_ride_on_a_route_gets_its_track(tmp_path: Path) -> None:
    put_routes(tmp_path, {"b-loop.gpx": LOOP})
    session = AppSession(tmp_path)
    await pre_ride(session)
    assert session.command("set_route", file="b-loop.gpx") is None
    await session.clock.advance(15.0)
    assert session.command("start") is None
    await session.until(240.0)
    assert session.command("finish") is None
    done = screen(session)["route"]
    assert done["name"] == "Lake loop" and done["distance_m"] > 1000
    await settle(session)
    ride = await session.close()
    assert (ride / "route.gpx").read_bytes() == LOOP
    meta = json.loads((ride / "meta.json").read_text())
    assert meta["rider_kg"] == 75
    assert meta["route"]["file"] == "b-loop.gpx"
    assert meta["route"]["distance_m"] == pytest.approx(done["distance_m"],
                                                        abs=1.0)
    messages = decode(ride / "ride.fit")
    records = messages["record_mesgs"]
    samples = read_jsonl(ride / "samples.jsonl")
    assert len(records) == len(samples)
    assert all("position_lat" in r and "distance" in r for r in records)
    assert records[-1]["distance"] == pytest.approx(
        meta["route"]["distance_m"], abs=0.1)
    session_mesg = messages["session_mesgs"][0]
    assert session_mesg["sub_sport"] == "virtual_activity"
    assert session_mesg["total_distance"] == pytest.approx(
        meta["route"]["distance_m"], abs=0.1)


@pytest.mark.case("T-RTE-06")
@pytest.mark.req("APP-903", "APP-904", "APP-906")
@pytest.mark.asyncio
async def test_a_past_ride_shows_its_route(tmp_path: Path) -> None:
    put_routes(tmp_path, {"a-climb.gpx": CLIMB})
    session = AppSession(tmp_path)
    await pre_ride(session)
    assert session.command("set_route", file="a-climb.gpx") is None
    await session.clock.advance(15.0)
    assert session.command("start") is None
    await session.until(120.0)
    assert session.command("finish") is None
    await settle(session)
    ride_id = screen(session)["ride_id"]
    assert session.command("back") is None
    assert session.command("open_history") is None
    assert session.command("open_ride", ride_id=ride_id) is None
    past = screen(session)
    assert past["past"] and past["route"]["name"] == "Test climb"
    assert past["route"]["ascent_m"] > 0
    await session.close()


@pytest.mark.case("T-RTE-04")
@pytest.mark.req("APP-901", "APP-907")
@pytest.mark.asyncio
async def test_no_routes_folder_means_no_routes(tmp_path: Path) -> None:
    session = AppSession(tmp_path)
    found = await pre_ride(session)
    assert found["routes"] == [] and found["route"] is None
    await session.close()


@pytest.mark.case("T-RTE-04")
@pytest.mark.req("APP-901", "APP-907")
@pytest.mark.asyncio
async def test_a_slow_older_read_never_replaces_a_newer_one(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = put_routes(tmp_path, {"b-loop.gpx": LOOP})
    catalog = RouteCatalog(folder, lambda: None)
    release = threading.Event()
    real_scan = route_catalog.scan_routes
    calls: list[Path] = []

    def slow_first(path: Path) -> list[RouteEntry]:
        calls.append(path)
        found = real_scan(path)
        if len(calls) == 1:
            release.wait(5.0)
        return found

    monkeypatch.setattr(route_catalog, "scan_routes", slow_first)
    older = asyncio.get_running_loop().create_task(catalog.refresh())
    await asyncio.sleep(0.05)
    (folder / "b-loop.gpx").unlink()
    await catalog.refresh()
    assert catalog.routes == ()
    release.set()
    await older
    assert catalog.routes == ()
    catalog.request_refresh()
    await catalog.close()
    assert catalog.routes == ()


async def ride_on(session: AppSession, file: str) -> None:
    await pre_ride(session)
    assert session.command("set_route", file=file) is None
    await session.clock.advance(15.0)
    assert session.command("start") is None


@pytest.mark.case("T-RTE-07")
@pytest.mark.req("APP-909", "APP-910")
@pytest.mark.asyncio
async def test_the_ride_screen_carries_the_ride_along_the_route(
        tmp_path: Path) -> None:
    put_routes(tmp_path, {"a-climb.gpx": CLIMB})
    session = AppSession(tmp_path)
    assert session.app.console.route() is None
    await ride_on(session, "a-climb.gpx")
    await session.until(60.0)
    first = screen(session)["route"]
    assert first["route_id"] == f"a-climb.gpx@{len(CLIMB)}"
    assert first["speed_kmh"] > 5 and first["grade_pct"] == 5.0
    assert first["distance_m"] > 100
    found = session.app.console.route()
    assert found is not None and found["route_id"] == first["route_id"]
    assert session.app.console.route() is found
    await session.until(120.0)
    later = screen(session)["route"]
    assert later["distance_m"] > first["distance_m"]
    assert later["altitude_m"] > first["altitude_m"]
    assert session.command("pause") is None
    await session.clock.advance(5.0)
    assert screen(session)["route"]["speed_kmh"] == 0.0
    assert session.command("resume") is None
    await session.until(180.0)
    live = session.app.rides.rider
    assert live is not None and live.last is not None
    last = live.last
    assert session.command("finish") is None
    assert session.app.console.route() is None
    ride = await session.close()
    records = decode(ride / "ride.fit")["record_mesgs"]
    seconds = [s["t"] for s in read_jsonl(ride / "samples.jsonl")]
    same = records[seconds.index(last.t)]
    assert same["distance"] == pytest.approx(last.distance_m, abs=0.01)
    assert same["enhanced_speed"] == pytest.approx(last.speed_mps,
                                                   abs=0.001)


@pytest.mark.case("T-RTE-07")
@pytest.mark.req("APP-910")
@pytest.mark.asyncio
async def test_after_a_restart_the_live_ride_goes_on_from_the_crash(
        tmp_path: Path) -> None:
    put_routes(tmp_path / "first", {"a-climb.gpx": CLIMB})
    first = AppSession(tmp_path / "first")
    await ride_on(first, "a-climb.gpx")
    await first.until(130.0)
    crash = screen(first)["route"]["distance_m"]
    again = Restarted(first, tmp_path / "again")
    await again.start()
    assert again.command("recovery_continue") is None
    resumed = again.app.console.view()["screen"]["route"]
    assert resumed["distance_m"] == pytest.approx(crash, abs=40)
    await again.clock.advance(60.0)
    moved = again.app.console.view()["screen"]["route"]
    assert moved["distance_m"] >= resumed["distance_m"]
    assert again.command("finish") is None
    await again.close()
    await first.close()
