"""Upload rides to Garmin Connect.

Garmin offers no API for uploading activities, so this goes through
python-garminconnect, an unofficial client that signs in the way the
Garmin Connect app does. The app never sees the password: `wow-garmin
login` signs in once and stores tokens in the data directory; every
upload loads them, and the library writes refreshed tokens back.
"""

import asyncio
import logging
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Final, Protocol

from garminconnect import (
    Garmin, GarminConnectAuthenticationError, GarminConnectConnectionError,
    GarminConnectInvalidFileFormatError, GarminConnectTooManyRequestsError,
)

from wow.core.upload import Outcome

logger = logging.getLogger(__name__)

UPLOAD_TIMEOUT: Final[float] = 60.0
DUPLICATE: Final[int] = 409
AUTH_REFUSED: Final[tuple[int, ...]] = (401, 403)
TOO_MANY: Final[int] = 429
LIBRARY_ERRORS: Final[tuple[type[Exception], ...]] = (
    GarminConnectAuthenticationError, GarminConnectConnectionError,
    GarminConnectTooManyRequestsError, OSError, ValueError)


class TokenStore(Protocol):
    """The part of the library's client that holds the tokens."""

    def load(self, path: str) -> None:
        """Read the tokens from a token directory."""
        ...


class GarminClient(Protocol):
    """The part of python-garminconnect's `Garmin` that wow uses."""

    @property
    def client(self) -> TokenStore:
        """Return the token-holding client."""
        ...

    @property
    def full_name(self) -> str | None:
        """Return the account's full name, once signed in."""
        ...

    @property
    def display_name(self) -> str | None:
        """Return the account's display name, once signed in."""
        ...

    def login(self, /, tokenstore: str | None = None
              ) -> tuple[str | None, Any]:
        """Sign in from stored tokens or with the password."""
        ...

    def logout(self, tokenstore: str | None = None) -> None:
        """Forget the stored tokens."""
        ...

    def upload_activity(self, activity_path: str) -> Any:
        """Upload an activity file."""
        ...

    def import_activity(self, activity_path: str) -> dict[str, Any]:
        """Upload an activity file as an import."""
        ...


ClientFactory = Callable[..., GarminClient]


class GarminError(Exception):
    """Signing in or checking the account failed."""


class GarminConnect:
    """One Garmin Connect account, through its stored tokens."""

    def __init__(self, tokens: Path, client: ClientFactory = Garmin,
                 timeout: float = UPLOAD_TIMEOUT) -> None:
        self._tokens = tokens
        self._client = client
        self._timeout = timeout

    async def upload(self, fit: Path, name: str) -> Outcome:
        """Upload a FIT file (the port); Garmin names the activity."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self.send, fit), self._timeout)
        except TimeoutError:
            logger.warning("Garmin upload of %s timed out", fit.parent.name)
            return Outcome.TRY_AGAIN

    def send(self, fit: Path, as_import: bool = False) -> Outcome:
        """Upload a FIT file and wait; as an import when asked."""
        garmin = self._client(retry_attempts=0)
        try:
            garmin.client.load(str(self._tokens))
        except (GarminConnectAuthenticationError,
                GarminConnectConnectionError) as error:
            logger.warning("Garmin tokens unusable: %s", error)
            return Outcome.KEY_REFUSED
        send = garmin.import_activity if as_import else garmin.upload_activity
        try:
            result = send(str(fit))
        except GarminConnectAuthenticationError as error:
            return _logged(Outcome.KEY_REFUSED, error)
        except GarminConnectTooManyRequestsError as error:
            return _logged(Outcome.TRY_AGAIN, error)
        except GarminConnectConnectionError as error:
            return _logged(outcome_of_status(status_of(error)), error)
        except (GarminConnectInvalidFileFormatError, ValueError,
                FileNotFoundError) as error:
            return _logged(Outcome.REFUSED, error)
        except OSError as error:
            return _logged(Outcome.TRY_AGAIN, error)
        return outcome_of_result(result)

    def sign_in(self, email: str, password: str,
                mfa: Callable[[], str]) -> str:
        """Sign in with the password, store the tokens; return the name.

        Old tokens are deleted first, so the password is always used.
        """
        self.sign_out()
        garmin = self._client(email, password, prompt_mfa=mfa)
        self._call(lambda: garmin.login(str(self._tokens)))
        return account_name(garmin)

    def check(self) -> str:
        """Sign in from the stored tokens; return the account name."""
        garmin = self._client()
        self._call(lambda: garmin.login(str(self._tokens)))
        return account_name(garmin)

    def sign_out(self) -> None:
        """Delete the stored tokens; Garmin keeps them valid until expiry."""
        garmin = self._client()
        self._call(lambda: garmin.logout(str(self._tokens)))

    @staticmethod
    def _call(action: Callable[[], object]) -> None:
        try:
            action()
        except LIBRARY_ERRORS as error:
            raise GarminError(str(error)) from error


def account_name(garmin: GarminClient) -> str:
    """Return the name to show for a signed-in account."""
    return garmin.full_name or garmin.display_name or "your account"


def status_of(error: BaseException) -> int | None:
    """Return the HTTP status behind a library error, if there is one."""
    seen: BaseException | None = error
    while seen is not None:
        status = getattr(getattr(seen, "response", None), "status_code", None)
        if isinstance(status, int):
            return status
        seen = seen.__cause__
    return None


def outcome_of_status(status: int | None) -> Outcome:
    """Return what a refused upload's HTTP status means."""
    if status is None or status == TOO_MANY or status >= 500:
        return Outcome.TRY_AGAIN
    if status == DUPLICATE:
        return Outcome.KNOWN
    if status in AUTH_REFUSED:
        return Outcome.KEY_REFUSED
    return Outcome.REFUSED


def outcome_of_result(result: object) -> Outcome:
    """Return what an accepted upload's import report means."""
    report = (result.get("detailedImportResult")
              if isinstance(result, dict) else None)
    failures = report.get("failures") if isinstance(report, dict) else None
    if not failures or not isinstance(failures, list):
        upload = report.get("uploadId") if isinstance(report, dict) else None
        logger.info("Garmin accepted the upload (upload ID %s)", upload)
        return Outcome.CREATED
    words = " ".join(failure_texts(failures))
    logger.warning("Garmin reported failures: %s", words)
    return Outcome.KNOWN if "duplicate" in words.lower() else Outcome.REFUSED


def failure_texts(failures: Iterable[object]) -> list[str]:
    """Return the message texts of an import report's failures."""
    texts = []
    for failure in failures:
        messages = (failure.get("messages")
                    if isinstance(failure, dict) else None)
        for message in messages if isinstance(messages, list) else []:
            text = (message.get("content")
                    if isinstance(message, dict) else message)
            if isinstance(text, str):
                texts.append(text)
    return texts


def _logged(outcome: Outcome, error: Exception) -> Outcome:
    logger.warning("Garmin upload: %s (%s)", outcome, error)
    return outcome
