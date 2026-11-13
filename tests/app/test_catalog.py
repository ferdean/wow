"""The workout catalog with recorded intervals.icu answers, and the
intervals.icu adapter against a local server (L3, L4)."""

import base64
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from tests.support.app_rig import RecordedProvider
from tests.support.timeline import load_json
from wow.adapters.clock_stepped import SteppedClock
from wow.adapters.intervals_icu import IntervalsIcu
from wow.app.workout_catalog import WorkoutCatalog, builtin_entries
from wow.ports.workouts import ProviderError

ZURICH = timezone(timedelta(hours=1))
EVENTS: list[Any] = load_json("intervals/events.json")
WORKOUTS: list[Any] = load_json("intervals/workouts.json")


def catalog(tmp: Path, clock: SteppedClock,
            provider: RecordedProvider | None) -> WorkoutCatalog:
    return WorkoutCatalog(clock, provider, tmp / "cache.json",
                          builtin_entries(), lambda: None, ZURICH)


def at(local: str) -> SteppedClock:
    moment = datetime.fromisoformat(local).replace(tzinfo=ZURICH)
    return SteppedClock(utc_start=moment.astimezone(UTC))


@pytest.mark.case("T-CAT-01")
@pytest.mark.req("APP-201")
@pytest.mark.asyncio
@pytest.mark.parametrize("day,names", [
    ("2026-11-14", ["Long ride + SS"]),
    ("2026-11-16", ["Test workout"]),
    ("2026-11-17", ["VO2 Max – 3×10′ 40/20s"]),
    ("2026-11-19", []),
    ("2026-11-15", []),
])
async def test_today_lists_the_rides_of_the_local_day(
        tmp_path: Path, day: str, names: list[str]) -> None:
    clock = at(f"{day}T12:00:00")
    provider = RecordedProvider(EVENTS, WORKOUTS)
    workouts = catalog(tmp_path, clock, provider)
    await clock.drive(workouts.refresh())
    assert [e.name for e in workouts.today()] == names
    assert provider.asked[0] == (date.fromisoformat(day), date.fromisoformat(
        day) + timedelta(days=6))


@pytest.mark.case("T-CAT-02")
@pytest.mark.req("APP-201")
@pytest.mark.asyncio
@pytest.mark.parametrize("local,names", [
    ("2026-11-13T23:59:59", []),
    ("2026-11-14T00:00:01", ["Long ride + SS"]),
    ("2026-11-14T00:30:00", ["Long ride + SS"]),
])
async def test_the_day_follows_local_time_not_utc(
        tmp_path: Path, local: str, names: list[str]) -> None:
    clock = at(local)
    workouts = catalog(tmp_path, clock, RecordedProvider(EVENTS, WORKOUTS))
    await clock.drive(workouts.refresh())
    assert [e.name for e in workouts.today()] == names


@pytest.mark.case("T-CAT-03")
@pytest.mark.req("APP-202")
@pytest.mark.asyncio
async def test_offline_lists_come_from_the_cache(tmp_path: Path) -> None:
    clock = at("2026-11-14T08:00:00")
    provider = RecordedProvider(EVENTS, WORKOUTS)
    workouts = catalog(tmp_path, clock, provider)
    await clock.drive(workouts.refresh())
    assert workouts.offline_since is None
    provider.failing = True
    await clock.advance(3 * 24 * 3600.0)
    later = catalog(tmp_path, clock, provider)
    await clock.drive(later.refresh())
    assert later.offline_since == "2026-11-14T07:00:00.000Z"
    assert [e.name for e in later.today()] == ["VO2 Max – 3×10′ 40/20s"]
    assert len(later.library()) == 3


@pytest.mark.case("T-CAT-04")
@pytest.mark.req("APP-202", "APP-211")
@pytest.mark.asyncio
async def test_without_cache_or_network_the_built_ins_remain(
        tmp_path: Path) -> None:
    clock = at("2026-11-14T08:00:00")
    provider = RecordedProvider(EVENTS, WORKOUTS)
    provider.failing = True
    workouts = catalog(tmp_path, clock, provider)
    await clock.drive(workouts.refresh())
    assert workouts.today() == [] and workouts.library() == []
    assert {e.ref for e in workouts.builtin} >= {"builtin:ramp-test",
                                                 "builtin:erg-check"}
    assert workouts.offline_since is None


@pytest.mark.case("T-CAT-05")
@pytest.mark.req("APP-210")
@pytest.mark.asyncio
async def test_the_library_lists_rides_only(tmp_path: Path) -> None:
    clock = at("2026-11-14T08:00:00")
    workouts = catalog(tmp_path, clock, RecordedProvider(EVENTS, WORKOUTS))
    await clock.drive(workouts.refresh())
    assert [e.ref for e in workouts.library()] == [
        "library:2", "library:1", "library:3"]


@pytest.mark.case("T-WKO-12")
@pytest.mark.req("APP-210")
@pytest.mark.asyncio
async def test_a_workout_without_a_workout_doc_is_not_rideable(
        tmp_path: Path) -> None:
    clock = at("2026-11-14T08:00:00")
    workouts = catalog(tmp_path, clock, RecordedProvider(EVENTS, WORKOUTS))
    await clock.drive(workouts.refresh())
    notes = workouts.find("library:3")
    assert notes is not None and notes.workout is None
    found = workouts.find("library:1")
    assert found is not None and found.workout is not None


@pytest.mark.case("S-ICU-01")
@pytest.mark.asyncio
async def test_the_adapter_authenticates_and_reports_errors() -> None:
    seen: list[tuple[str, str, dict[str, str]]] = []

    async def answer(request: web.Request) -> web.Response:
        seen.append((request.path, request.headers["Authorization"],
                     dict(request.query)))
        if "broken" in request.path:
            return web.Response(status=500)
        if request.path.endswith("/workouts"):
            return web.json_response([{"id": 1}])
        return web.json_response([{"id": 2}])

    app = web.Application()
    app.router.add_get("/api/v1/athlete/{id}/{what}", answer)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    try:
        base = f"http://127.0.0.1:{port}/api/v1"
        icu = IntervalsIcu("i1", "secret", base)
        assert await icu.planned(date(2026, 11, 14),
                                 date(2026, 11, 20)) == [{"id": 2}]
        assert await icu.library() == [{"id": 1}]
        path, auth, query = seen[0]
        assert path == "/api/v1/athlete/i1/events"
        assert auth == "Basic " + base64.b64encode(
            b"API_KEY:secret").decode()
        assert query == {"oldest": "2026-11-14", "newest": "2026-11-20"}
        with pytest.raises(ProviderError):
            await IntervalsIcu("broken", "k", base).library()
        with pytest.raises(ProviderError):
            await IntervalsIcu("i1", "k", "http://127.0.0.1:1").library()
    finally:
        await runner.cleanup()
