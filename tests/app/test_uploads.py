"""Uploads to intervals.icu (L3, T-UPL-01 to T-UPL-05, S-ICU-02)."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from aiohttp import web

from tests.support.app_rig import ERG_CHECK, AppSession
from wow.adapters.clock_stepped import SteppedClock
from wow.adapters.intervals_icu import IntervalsIcu, outcome_of
from wow.app.upload_worker import UploadWorker
from wow.core.upload import Outcome

RIDE = "2026-11-10T174048Z"
DAY = 24 * 3600.0


class FakeUploader:
    """Answers with scripted outcomes, then with the last one."""

    def __init__(self, clock: SteppedClock | None, *outcomes: Outcome
                 ) -> None:
        self.clock = clock
        self.outcomes = list(outcomes)
        self.calls: list[tuple[float, str, str]] = []

    async def upload(self, fit: Path, name: str) -> Outcome:
        now = 0.0 if self.clock is None else self.clock.monotonic()
        self.calls.append((now, fit.parent.name, name))
        if len(self.outcomes) > 1:
            return self.outcomes.pop(0)
        return self.outcomes[0]


def make_ride(rides: Path, ride_id: str = RIDE,
              upload: str = "pending") -> Path:
    ride_dir = rides / ride_id
    ride_dir.mkdir(parents=True)
    (ride_dir / "ride.fit").write_bytes(b"fit")
    (ride_dir / "meta.json").write_text(json.dumps({
        "schema": 1, "ride_id": ride_id, "state": "finished",
        "title": "ERG check", "upload": upload}))
    return ride_dir


def meta(ride_dir: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads((ride_dir / "meta.json").read_text())
    return value


class Running:
    """A worker running on the stepped clock."""

    def __init__(self, clock: SteppedClock, uploader: FakeUploader,
                 rides: Path) -> None:
        self.worker = UploadWorker(clock, uploader, rides, lambda: None)
        self.worker.load()
        self.task = asyncio.get_running_loop().create_task(self.worker.run())

    async def stop(self) -> None:
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


async def running(clock: SteppedClock, uploader: FakeUploader,
                  rides: Path) -> Running:
    worker = Running(clock, uploader, rides)
    await clock.advance(0.0)
    return worker


@pytest_asyncio.fixture
async def server() -> AsyncIterator[tuple[str, list[dict[str, Any]]]]:
    seen: list[dict[str, Any]] = []

    async def activities(request: web.Request) -> web.Response:
        form = await request.post()
        upload = form["file"]
        assert isinstance(upload, web.FileField)
        seen.append({"path": request.path, "query": dict(request.query),
                     "auth": request.headers["Authorization"],
                     "type": request.content_type,
                     "file": upload.file.read(),
                     "filename": upload.filename})
        return web.json_response({"id": "a1"}, status=201)

    app = web.Application()
    app.router.add_post("/api/v1/athlete/{id}/activities", activities)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    yield f"http://127.0.0.1:{runner.addresses[0][1]}/api/v1", seen
    await runner.cleanup()


@pytest.mark.case("T-UPL-01")
@pytest.mark.req("APP-607")
@pytest.mark.asyncio
async def test_one_multipart_post_with_basic_authentication(
        server: tuple[str, list[dict[str, Any]]], tmp_path: Path) -> None:
    base, seen = server
    ride_dir = make_ride(tmp_path)
    icu = IntervalsIcu("i1", "secret", base)
    assert await icu.upload(ride_dir / "ride.fit", "ERG check") == (
        Outcome.CREATED)
    assert len(seen) == 1
    request = seen[0]
    assert request["path"] == "/api/v1/athlete/i1/activities"
    assert request["query"] == {"name": "ERG check"}
    assert request["type"] == "multipart/form-data"
    assert (request["file"], request["filename"]) == (b"fit", "ride.fit")
    assert request["auth"] == "Basic " + base64.b64encode(
        b"API_KEY:secret").decode()


@pytest.mark.case("T-UPL-01")
@pytest.mark.req("APP-607")
@pytest.mark.asyncio
@pytest.mark.parametrize("upload_on", [True, False])
async def test_finish_uploads_without_the_rider(tmp_path: Path,
                                                upload_on: bool) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps(
        {"schema": 1, "upload_on": upload_on}))
    uploader = FakeUploader(None, Outcome.CREATED)
    session = AppSession(tmp_path, uploader=uploader)
    uploader.clock = session.clock
    task = asyncio.get_running_loop().create_task(session.app.uploads.run())
    await session.begin(ERG_CHECK)
    await session.until(30.0)
    assert session.command("finish") is None
    session.app.recorder.flush()
    await session.clock.advance(5.0)
    ride_dir = await session.close()
    await session.clock.advance(1.0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    if upload_on:
        assert [c[1] for c in uploader.calls] == [ride_dir.name]
        assert meta(ride_dir)["upload"] == "done"
    else:
        assert uploader.calls == []
        assert meta(ride_dir)["upload"] == "off"


@pytest.mark.case("T-UPL-02")
@pytest.mark.req("APP-608")
@pytest.mark.asyncio
async def test_failures_are_retried_until_one_succeeds(
        tmp_path: Path) -> None:
    clock = SteppedClock()
    ride_dir = make_ride(tmp_path)
    uploader = FakeUploader(clock, Outcome.TRY_AGAIN, Outcome.TRY_AGAIN,
                            Outcome.TRY_AGAIN, Outcome.CREATED)
    worker = await running(clock, uploader, tmp_path)
    assert meta(ride_dir)["upload"] == "retrying"
    await clock.advance(3600.0)
    await worker.stop()
    times = [c[0] for c in uploader.calls]
    assert len(times) == 4
    assert max(b - a for a, b in zip(times, times[1:])) <= 900.0
    assert meta(ride_dir)["upload"] == "done"
    assert (ride_dir / "ride.fit").exists()


@pytest.mark.case("T-UPL-03")
@pytest.mark.req("APP-608")
@pytest.mark.asyncio
async def test_seven_days_of_retries_across_restarts(tmp_path: Path) -> None:
    clock = SteppedClock()
    ride_dir = make_ride(tmp_path)
    uploader = FakeUploader(clock, Outcome.TRY_AGAIN)
    counts = []
    for days in (1.0, 2.5, 4.0):
        worker = await running(clock, uploader, tmp_path)
        await clock.advance(days * DAY)
        await worker.stop()
        counts.append(len(uploader.calls))
        await clock.advance(600.0)
    assert counts[0] > 90 and counts[1] > counts[0] and counts[2] > counts[1]
    assert meta(ride_dir)["upload"] == "failed"
    worker = await running(clock, uploader, tmp_path)
    before = len(uploader.calls)
    await clock.advance(DAY)
    assert len(uploader.calls) == before
    assert worker.worker.retry(RIDE)
    await clock.advance(1.0)
    assert len(uploader.calls) == before + 1
    await worker.stop()


@pytest.mark.case("T-UPL-04")
@pytest.mark.req("APP-608")
@pytest.mark.asyncio
async def test_a_refused_key_waits_for_the_rider(tmp_path: Path) -> None:
    clock = SteppedClock()
    ride_dir = make_ride(tmp_path)
    uploader = FakeUploader(clock, Outcome.KEY_REFUSED, Outcome.CREATED)
    worker = await running(clock, uploader, tmp_path)
    await clock.advance(DAY)
    assert len(uploader.calls) == 1
    assert meta(ride_dir)["upload"] == "auth_error"
    assert worker.worker.retry(RIDE)
    await clock.advance(1.0)
    assert len(uploader.calls) == 2
    assert meta(ride_dir)["upload"] == "done"
    await worker.stop()


@pytest.mark.case("T-UPL-05")
@pytest.mark.req("APP-609")
@pytest.mark.asyncio
async def test_a_done_ride_is_never_sent_again_unasked(
        tmp_path: Path) -> None:
    clock = SteppedClock()
    make_ride(tmp_path)
    uploader = FakeUploader(clock, Outcome.CREATED)
    for _ in range(3):
        worker = await running(clock, uploader, tmp_path)
        await clock.advance(DAY / 2)
        await worker.stop()
    assert len(uploader.calls) == 1
    worker = await running(clock, uploader, tmp_path)
    assert worker.worker.retry(RIDE)
    await clock.advance(DAY)
    assert len(uploader.calls) == 2
    await worker.stop()


@pytest.mark.case("S-ICU-02")
def test_http_status_to_outcome() -> None:
    assert [outcome_of(s) for s in (201, 200, 401, 403, 429, 500, 503,
                                    400, 404)] == [
        Outcome.CREATED, Outcome.KNOWN, Outcome.KEY_REFUSED,
        Outcome.KEY_REFUSED, Outcome.TRY_AGAIN, Outcome.TRY_AGAIN,
        Outcome.TRY_AGAIN, Outcome.REFUSED, Outcome.REFUSED]
