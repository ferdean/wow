"""Decide what an upload does next.

The upload states of ICD 4.8.3 (APP-607 to APP-609): an attempt's
outcome moves the state on; failures are retried every 15 minutes for 7
days from the first attempt; a refused key waits for the rider.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from wow.core.vocab import UploadState

UPLOAD_RETRY_INTERVAL: Final[float] = 900.0
UPLOAD_GIVE_UP_AFTER: Final[float] = 7 * 24 * 3600.0
WAITING: Final[tuple[UploadState, ...]] = (
    UploadState.PENDING, UploadState.UPLOADING, UploadState.RETRYING)


class Outcome(StrEnum):
    """What one upload attempt came to."""

    CREATED = "created"
    KNOWN = "known"
    TRY_AGAIN = "try_again"
    KEY_REFUSED = "key_refused"
    REFUSED = "refused"


@dataclass(frozen=True)
class Upload:
    """The upload of one ride, as kept in its meta.json."""

    state: UploadState
    first_utc: datetime | None = None
    last_utc: datetime | None = None
    attempts: int = 0


def started(upload: Upload, now: datetime) -> Upload:
    """Return the upload with an attempt under way."""
    return replace(upload, state=UploadState.UPLOADING,
                   first_utc=upload.first_utc or now, last_utc=now,
                   attempts=upload.attempts + 1)


def finished(upload: Upload, outcome: Outcome, now: datetime) -> Upload:
    """Return the upload after an attempt's outcome."""
    match outcome:
        case Outcome.CREATED | Outcome.KNOWN:
            state = UploadState.DONE
        case Outcome.KEY_REFUSED:
            state = UploadState.AUTH_ERROR
        case Outcome.REFUSED:
            state = UploadState.FAILED
        case _:
            state = (UploadState.FAILED if _expired(upload, now)
                     else UploadState.RETRYING)
    return replace(upload, state=state)


def asked_again() -> Upload:
    """Return the upload the rider asked for by hand (APP-608, APP-609)."""
    return Upload(UploadState.PENDING)


def wait(upload: Upload, now: datetime) -> float | None:
    """Return the seconds until the next attempt, if one is due at all."""
    if upload.state not in WAITING:
        return None
    if upload.state == UploadState.RETRYING and upload.last_utc is not None:
        due = upload.last_utc + timedelta(seconds=UPLOAD_RETRY_INTERVAL)
        return max(0.0, (due - now).total_seconds())
    return 0.0


def given_up(upload: Upload, now: datetime) -> Upload:
    """Return the upload marked failed once its 7 days are over."""
    if upload.state in WAITING and upload.first_utc is not None and (
            _expired(upload, now)):
        return replace(upload, state=UploadState.FAILED)
    return upload


def _expired(upload: Upload, now: datetime) -> bool:
    first = upload.first_utc or now
    return (now - first).total_seconds() >= UPLOAD_GIVE_UP_AFTER
