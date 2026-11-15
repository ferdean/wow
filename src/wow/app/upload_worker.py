"""Upload finished rides to intervals.icu.

The upload worker (3A, app/upload_worker; ICD 4.8.3; APP-607 to
APP-609): uploads each finished ride once without the rider, retries
every 15 minutes for 7 days, waits for the rider after a refused key,
and keeps the state in the ride's `meta.json`, so it survives restarts.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from wow.app.history import FIT_FILE, read_meta, ride_path, utc_of, write_meta
from wow.core.timefmt import utc_text
from wow.core.upload import (
    Upload, asked_again, finished, given_up, started, wait,
)
from wow.core.vocab import UploadState
from wow.ports.clock import Clock
from wow.ports.upload import ActivityUploader

logger = logging.getLogger(__name__)


class UploadWorker:
    """Uploads rides in the background."""

    def __init__(self, clock: Clock, uploader: ActivityUploader | None,
                 rides: Path, on_change: Callable[[], None]) -> None:
        self._clock = clock
        self._uploader = uploader
        self._rides = rides
        self._on_change = on_change
        self._uploads: dict[str, Upload] = {}
        self._wake = asyncio.Event()

    def state(self, ride_id: str) -> UploadState | None:
        """Return a ride's upload state, if the worker knows it."""
        upload = self._uploads.get(ride_id)
        return None if upload is None else upload.state

    def load(self) -> None:
        """Pick up the rides whose upload isn't over."""
        if not self._rides.is_dir():
            return
        for ride_dir in self._rides.iterdir():
            meta = read_meta(ride_dir)
            if meta is not None and meta.get("state") == "finished":
                upload = _upload(meta)
                if wait(upload, self._clock.utc()) is not None:
                    self._uploads[ride_dir.name] = upload

    def queue(self, ride_id: str) -> None:
        """Upload a ride whose files are being written."""
        self._uploads[ride_id] = Upload(UploadState.PENDING)
        self._wake.set()

    def retry(self, ride_id: str) -> bool:
        """Upload a ride again at the rider's request."""
        if self.state(ride_id) == UploadState.UPLOADING:
            return False
        ride_dir = ride_path(self._rides, ride_id)
        if ride_dir is None:
            return False
        self._uploads[ride_id] = asked_again()
        self._save(ride_dir, self._uploads[ride_id])
        self._wake.set()
        return True

    def set_uploader(self, uploader: ActivityUploader) -> None:
        """Upload through a new account from now on (APP-706)."""
        self._uploader = uploader
        self._wake.set()

    async def run(self) -> None:
        """Upload whatever is due, until cancelled.

        Without an intervals.icu account nothing is sent and the rides
        stay pending until an account is entered.
        """
        if self._uploader is None:
            logger.info("no intervals.icu account: uploads wait")
        while True:
            now = self._clock.utc()
            due = None if self._uploader is None else self._next(now)
            if due is not None and due[1] <= 0.0:
                await self._attempt(due[0])
                continue
            self._wake.clear()
            waiting = asyncio.ensure_future(self._wake.wait())
            sleeping = None if due is None else asyncio.ensure_future(
                self._clock.sleep_until(self._clock.monotonic() + due[1]))
            pending = [t for t in (waiting, sleeping) if t is not None]
            try:
                await asyncio.wait(pending,
                                   return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in pending:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    def _next(self, now: datetime) -> tuple[str, float] | None:
        best: tuple[str, float] | None = None
        for ride_id, upload in list(self._uploads.items()):
            ended = given_up(upload, now)
            if ended != upload:
                self._uploads[ride_id] = ended
                self._store(ride_id, ended)
                continue
            seconds = wait(upload, now)
            if seconds is not None and (best is None or seconds < best[1]):
                best = (ride_id, seconds)
        return best

    async def _attempt(self, ride_id: str) -> None:
        ride_dir = ride_path(self._rides, ride_id)
        meta = None if ride_dir is None else read_meta(ride_dir)
        if ride_dir is None or meta is None:
            self._uploads.pop(ride_id, None)
            return
        fit = ride_dir / FIT_FILE
        if meta.get("state") != "finished" or not fit.exists():
            await self._clock.sleep_until(self._clock.monotonic() + 1.0)
            return
        upload = started(self._uploads[ride_id], self._clock.utc())
        self._uploads[ride_id] = upload
        self._save(ride_dir, upload)
        assert self._uploader is not None
        outcome = await self._uploader.upload(fit, str(meta.get("title")))
        logger.info("upload of %s: %s", ride_id, outcome)
        upload = finished(upload, outcome, self._clock.utc())
        self._uploads[ride_id] = upload
        self._save(ride_dir, upload)

    def _store(self, ride_id: str, upload: Upload) -> None:
        ride_dir = ride_path(self._rides, ride_id)
        if ride_dir is not None:
            self._save(ride_dir, upload)

    def _save(self, ride_dir: Path, upload: Upload) -> None:
        meta = read_meta(ride_dir)
        if meta is None:
            return
        meta.update({
            "upload": upload.state,
            "upload_first_utc": _text(upload.first_utc),
            "upload_last_utc": _text(upload.last_utc),
            "upload_attempts": upload.attempts})
        write_meta(ride_dir, meta)
        self._on_change()


def _upload(meta: dict[str, Any]) -> Upload:
    state = UploadState(str(meta.get("upload", UploadState.OFF)))
    if state == UploadState.UPLOADING:
        state = UploadState.RETRYING
    first, last = meta.get("upload_first_utc"), meta.get("upload_last_utc")
    return Upload(state, None if first is None else utc_of(str(first)),
                  None if last is None else utc_of(str(last)),
                  int(meta.get("upload_attempts", 0)))


def _text(moment: datetime | None) -> str | None:
    return None if moment is None else utc_text(moment)
