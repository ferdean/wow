"""Uploads to Garmin Connect in the app (supporting S-GAR-09 to S-GAR-14)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from tests.app.test_recovery import Restarted
from tests.app.test_uploads import FakeUploader, make_ride, meta, running
from tests.support.app_rig import ERG_CHECK, AppSession, app_config
from wow.adapters.clock_stepped import SteppedClock
from wow.app.config import GARMIN_TOKEN_FILE, garmin_tokens
from wow.app.main import App
from wow.app.upload_worker import GARMIN, UploadWorker, one_account
from wow.core.upload import Outcome
from wow.core.vocab import UploadState

RIDE = "2026-11-10T174048Z"


def settings(data: Path, **values: Any) -> None:
    data.mkdir(parents=True, exist_ok=True)
    (data / "settings.json").write_text(json.dumps({"schema": 1, **values}))


def sign_in(data: Path) -> None:
    tokens = garmin_tokens(data)
    tokens.mkdir(parents=True, exist_ok=True)
    (tokens / GARMIN_TOKEN_FILE).write_text("{}")


def screen(session: AppSession) -> dict[str, Any]:
    value: dict[str, Any] = session.app.console.view()["screen"]
    return value


async def finished_ride(tmp_path: Path, garmin: FakeUploader,
                        icu: FakeUploader,
                        **extra: Any) -> tuple[AppSession, Path]:
    session = AppSession(tmp_path, uploader=icu, garmin=garmin, **extra)
    garmin.clock = icu.clock = session.clock
    tasks = [asyncio.get_running_loop().create_task(w.run())
             for w in (session.app.uploads, session.app.garmin_uploads)]
    await session.begin(ERG_CHECK)
    await session.until(30.0)
    assert session.command("finish") is None
    session.app.recorder.flush()
    await session.clock.advance(5.0)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    ride_dir = await session.close()
    return session, ride_dir


@pytest.mark.case("S-GAR-09")
@pytest.mark.asyncio
async def test_the_garmin_worker_keeps_its_own_fields(tmp_path: Path) -> None:
    clock = SteppedClock()
    ride_dir = make_ride(tmp_path, upload="done")
    data = meta(ride_dir)
    data["garmin_upload"] = "pending"
    (ride_dir / "meta.json").write_text(json.dumps(data))
    garmin = FakeUploader(clock, Outcome.TRY_AGAIN, Outcome.CREATED)
    worker = UploadWorker(clock, one_account(garmin), tmp_path,
                          lambda: None, GARMIN)
    worker.load()
    task = asyncio.get_running_loop().create_task(worker.run())
    await clock.advance(1000.0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    after = meta(ride_dir)
    assert len(garmin.calls) == 2
    assert after["garmin_upload"] == "done"
    assert after["garmin_upload_attempts"] == 2
    assert after["garmin_upload_first_utc"] is not None
    assert after["upload"] == "done" and "upload_attempts" not in after


@pytest.mark.case("S-GAR-09")
@pytest.mark.asyncio
async def test_rides_without_garmin_fields_are_left_alone(
        tmp_path: Path) -> None:
    clock = SteppedClock()
    make_ride(tmp_path)
    garmin = FakeUploader(clock, Outcome.CREATED)
    worker = UploadWorker(clock, one_account(garmin), tmp_path,
                          lambda: None, GARMIN)
    worker.load()
    assert worker.state(RIDE) is None
    icu = await running(clock, FakeUploader(clock, Outcome.CREATED),
                        tmp_path)
    await clock.advance(10.0)
    await icu.stop()
    assert garmin.calls == []


@pytest.mark.case("S-GAR-10")
@pytest.mark.asyncio
@pytest.mark.parametrize(("icu_on", "garmin_on"), [
    (False, True), (True, True), (True, False)])
async def test_finish_uploads_where_the_settings_say(
        tmp_path: Path, icu_on: bool, garmin_on: bool) -> None:
    settings(tmp_path / "data", upload_on=icu_on, garmin_upload_on=garmin_on)
    garmin = FakeUploader(None, Outcome.CREATED)
    icu = FakeUploader(None, Outcome.CREATED)
    _, ride_dir = await finished_ride(tmp_path, garmin, icu,
                                      upload_simulated=True)
    sent = [ride_dir.name]
    assert [c[1] for c in garmin.calls] == (sent if garmin_on else [])
    assert [c[1] for c in icu.calls] == (sent if icu_on else [])
    stored = meta(ride_dir)
    assert stored["garmin_upload"] == ("done" if garmin_on else "off")
    assert stored["upload"] == ("done" if icu_on else "off")


@pytest.mark.case("S-GAR-11")
@pytest.mark.asyncio
async def test_a_simulated_ride_never_goes_to_garmin_by_itself(
        tmp_path: Path) -> None:
    settings(tmp_path / "data", garmin_upload_on=True)
    garmin = FakeUploader(None, Outcome.CREATED)
    icu = FakeUploader(None, Outcome.CREATED)
    _, ride_dir = await finished_ride(tmp_path, garmin, icu)
    assert garmin.calls == [] and icu.calls == []
    assert meta(ride_dir)["garmin_upload"] == "off"


@pytest.mark.case("S-GAR-12")
@pytest.mark.asyncio
async def test_summary_shows_garmin_once_signed_in_and_uploads_by_hand(
        tmp_path: Path) -> None:
    data = tmp_path / "data"
    settings(data, upload_on=False)
    garmin = FakeUploader(None, Outcome.KEY_REFUSED, Outcome.CREATED)
    icu = FakeUploader(None, Outcome.CREATED)
    session, ride_dir = await finished_ride(tmp_path, garmin, icu,
                                            upload_simulated=True)
    assert screen(session)["garmin_upload"] is None
    sign_in(data)
    assert screen(session)["garmin_upload"] == "off"
    task = asyncio.get_running_loop().create_task(
        session.app.garmin_uploads.run())
    for expected in ("auth_error", "done"):
        assert session.command("garmin_upload_retry",
                               ride_id=ride_dir.name) is None
        await session.clock.advance(1.0)
        assert screen(session)["garmin_upload"] == expected
    assert session.command("garmin_upload_retry",
                           ride_id="not-a-ride") == "bad_request"
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert len(garmin.calls) == 2 and icu.calls == []
    assert meta(ride_dir)["garmin_upload"] == "done"


@pytest.mark.case("S-GAR-12")
@pytest.mark.asyncio
async def test_history_shows_garmin_and_retries_from_there(
        tmp_path: Path) -> None:
    rides = tmp_path / "data" / "rides"
    ride_dir = make_ride(rides, upload="done")
    stored = meta(ride_dir)
    stored.update({"garmin_upload": "failed", "metrics": {
        "duration": 60, "tss": 1.0, "time_in_zone": []},
        "start_utc": "2026-11-10T17:40:48.000Z"})
    (ride_dir / "meta.json").write_text(json.dumps(stored))
    garmin = FakeUploader(None, Outcome.CREATED)
    session = AppSession(tmp_path, garmin=garmin)
    garmin.clock = session.clock
    assert session.command("open_history") is None
    [entry] = screen(session)["rides"]
    assert (entry["upload"], entry["garmin_upload"]) == ("done", "failed")
    task = asyncio.get_running_loop().create_task(
        session.app.garmin_uploads.run())
    assert session.command("garmin_upload_retry", ride_id=RIDE) is None
    await session.clock.advance(1.0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert screen(session)["rides"][0]["garmin_upload"] == "done"
    assert session.command("open_ride", ride_id=RIDE) is None
    assert screen(session)["garmin_upload"] == "done"
    await session.close()


class Held:
    """An uploader that holds every upload until released."""

    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def upload(self, fit: Path, name: str) -> Outcome:
        await self.release.wait()
        return Outcome.CREATED


@pytest.mark.case("S-GAR-12")
@pytest.mark.asyncio
async def test_a_ride_uploading_to_garmin_is_not_deleted(
        tmp_path: Path) -> None:
    make_ride(tmp_path / "data" / "rides", upload="off")
    held = Held()
    session = AppSession(tmp_path, garmin=held)
    task = asyncio.get_running_loop().create_task(
        session.app.garmin_uploads.run())
    assert session.command("open_history") is None
    assert session.command("garmin_upload_retry", ride_id=RIDE) is None
    await session.clock.advance(1.0)
    assert session.app.garmin_uploads.state(RIDE) == UploadState.UPLOADING
    assert session.command("delete_ride", ride_id=RIDE) == "invalid_state"
    held.release.set()
    await session.clock.advance(1.0)
    assert session.command("delete_ride", ride_id=RIDE) is None
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await session.close()


@pytest.mark.case("S-GAR-13")
@pytest.mark.asyncio
async def test_a_recovered_ride_keeps_its_garmin_upload(
        tmp_path: Path) -> None:
    settings(tmp_path / "first" / "data", garmin_upload_on=True)
    first = AppSession(tmp_path / "first", upload_simulated=True)
    await first.begin(ERG_CHECK)
    await first.until(130.0)
    again = Restarted(first, tmp_path / "again")
    garmin = FakeUploader(again.clock, Outcome.CREATED)
    again.app = App(app_config(tmp_path / "again"), again.clock,
                    boot=first.app.recorder.boot_id, garmin=garmin,
                    upload_simulated=True)
    await again.start()
    assert again.command("recovery_finish") is None
    summary = again.app.rides.summary
    assert summary is not None
    assert summary.garmin_upload == UploadState.PENDING
    await again.clock.advance(5.0)
    ride_dir = await again.close()
    await first.close()
    assert [c[1] for c in garmin.calls] == [ride_dir.name]
