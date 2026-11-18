"""The Garmin Connect adapter (supporting tests S-GAR-01 to S-GAR-08)."""

import asyncio
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import requests
from garminconnect import (
    Garmin, GarminConnectAuthenticationError, GarminConnectConnectionError,
    GarminConnectInvalidFileFormatError, GarminConnectTooManyRequestsError,
)
from garminconnect.client import token_file_path

from wow.adapters.garmin_connect import (
    GarminConnect, GarminError, outcome_of_result, outcome_of_status,
    status_of,
)
from wow.app.config import GARMIN_TOKEN_FILE
from wow.core.upload import Outcome

UPLOAD_URL = "https://connectapi.garmin.com/upload-service/upload"


@dataclass
class Reply:
    """An HTTP response as python-garminconnect reads it."""

    status_code: int
    body: Any = None

    def json(self) -> Any:
        return self.body


def refused(status: int) -> GarminConnectConnectionError:
    error = GarminConnectConnectionError(f"API Error {status}")
    error.response = Reply(status)
    return error


@dataclass
class Tokens:
    """The fake token store: what was loaded, or why it can't be."""

    problem: Exception | None = None
    loaded: list[str] = field(default_factory=list)

    def load(self, path: str) -> None:
        if self.problem is not None:
            raise self.problem
        self.loaded.append(path)


class FakeGarmin:
    """Stands in for python-garminconnect's Garmin."""

    def __init__(self, tokens: Tokens, answer: Any = None,
                 *args: Any, **kwargs: Any) -> None:
        self.client = tokens
        self.answer = answer
        self.args = args
        self.kwargs = kwargs
        self.full_name: str | None = "Ferran"
        self.display_name: str | None = "ferran.d"
        self.calls: list[tuple[str, str | None]] = []
        self.release: threading.Event | None = None

    def _reply(self, name: str, path: str) -> Any:
        self.calls.append((name, path))
        if self.release is not None:
            self.release.wait(5.0)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def login(self, /, tokenstore: str | None = None
              ) -> tuple[str | None, Any]:
        if self.args and ("logout", tokenstore) in self.calls:
            raise GarminConnectAuthenticationError(
                "Username and password are required")
        self._reply("login", tokenstore or "")
        return None, None

    def logout(self, tokenstore: str | None = None) -> None:
        self.calls.append(("logout", tokenstore))

    def upload_activity(self, activity_path: str) -> Any:
        return self._reply("upload", activity_path)

    def import_activity(self, activity_path: str) -> dict[str, Any]:
        result: dict[str, Any] = self._reply("import", activity_path)
        return result


class Factory:
    """Makes FakeGarmin clients and remembers them."""

    def __init__(self, answer: Any = None, tokens: Tokens | None = None,
                 full_name: str | None = "Ferran") -> None:
        self.answer = answer
        self.tokens = tokens or Tokens()
        self.full_name = full_name
        self.made: list[FakeGarmin] = []
        self.release: threading.Event | None = None

    def __call__(self, *args: Any, **kwargs: Any) -> FakeGarmin:
        garmin = FakeGarmin(self.tokens, self.answer, *args, **kwargs)
        garmin.release = self.release
        garmin.full_name = self.full_name
        self.made.append(garmin)
        return garmin


def accepted(failures: list[Any] | None = None) -> dict[str, Any]:
    return {"detailedImportResult": {"uploadId": 42, "successes": [],
                                     "failures": failures or []}}


def fit_file(tmp_path: Path) -> Path:
    ride = tmp_path / "rides" / "2026-11-18T171500Z"
    ride.mkdir(parents=True)
    fit = ride / "ride.fit"
    fit.write_bytes(b".FIT")
    return fit


@pytest.mark.case("S-GAR-01")
def test_http_status_to_outcome() -> None:
    assert [outcome_of_status(s) for s in (
        None, 409, 401, 403, 429, 500, 503, 400, 404, 413)] == [
        Outcome.TRY_AGAIN, Outcome.KNOWN, Outcome.KEY_REFUSED,
        Outcome.KEY_REFUSED, Outcome.TRY_AGAIN, Outcome.TRY_AGAIN,
        Outcome.TRY_AGAIN, Outcome.REFUSED, Outcome.REFUSED,
        Outcome.REFUSED]


@pytest.mark.case("S-GAR-01")
def test_the_status_is_found_behind_a_wrapped_error() -> None:
    inner = refused(409)
    try:
        raise GarminConnectConnectionError("duplicate") from inner
    except GarminConnectConnectionError as outer:
        assert status_of(outer) == 409
    assert status_of(GarminConnectConnectionError("no response")) is None


@pytest.mark.case("S-GAR-02")
def test_import_report_to_outcome() -> None:
    duplicate = [{"messages": [{"code": 202,
                                "content": "Duplicate Activity."}]}]
    broken = [{"messages": [{"code": 100, "content": "Invalid file"}]}]
    assert outcome_of_result(accepted()) == Outcome.CREATED
    assert outcome_of_result(None) == Outcome.CREATED
    assert outcome_of_result({"detailedImportResult": "?"}) == (
        Outcome.CREATED)
    assert outcome_of_result(accepted(duplicate)) == Outcome.KNOWN
    assert outcome_of_result(accepted(broken)) == Outcome.REFUSED
    assert outcome_of_result(accepted(["odd", {"messages": "x"}])) == (
        Outcome.REFUSED)
    assert outcome_of_result(accepted([{"messages": ["Duplicate"]}])) == (
        Outcome.KNOWN)


@pytest.mark.case("S-GAR-03")
@pytest.mark.parametrize("as_import", [False, True])
def test_send_loads_the_tokens_then_uploads_once(
        tmp_path: Path, as_import: bool) -> None:
    factory = Factory(accepted())
    fit = fit_file(tmp_path)
    garmin = GarminConnect(tmp_path / "garmin", factory)
    assert garmin.send(fit, as_import) == Outcome.CREATED
    [made] = factory.made
    assert made.kwargs == {"retry_attempts": 0}
    assert factory.tokens.loaded == [str(tmp_path / "garmin")]
    assert made.calls == [("import" if as_import else "upload", str(fit))]


@pytest.mark.case("S-GAR-04")
@pytest.mark.parametrize("problem", [
    GarminConnectConnectionError("Token path not loading cleanly"),
    GarminConnectAuthenticationError("Missing tokens from dict load")])
def test_unusable_tokens_wait_for_the_rider(tmp_path: Path,
                                            problem: Exception) -> None:
    factory = Factory(accepted(), Tokens(problem))
    garmin = GarminConnect(tmp_path / "garmin", factory)
    assert garmin.send(fit_file(tmp_path)) == Outcome.KEY_REFUSED
    assert factory.made[0].calls == []


@pytest.mark.case("S-GAR-05")
@pytest.mark.parametrize(("error", "outcome"), [
    (refused(409), Outcome.KNOWN),
    (refused(401), Outcome.KEY_REFUSED),
    (refused(500), Outcome.TRY_AGAIN),
    (refused(400), Outcome.REFUSED),
    (GarminConnectConnectionError("Import error"), Outcome.TRY_AGAIN),
    (GarminConnectAuthenticationError("expired"), Outcome.KEY_REFUSED),
    (GarminConnectTooManyRequestsError("slow down"), Outcome.TRY_AGAIN),
    (GarminConnectInvalidFileFormatError("not FIT"), Outcome.REFUSED),
    (ValueError("bad path"), Outcome.REFUSED),
    (FileNotFoundError("gone"), Outcome.REFUSED),
    (requests.ConnectionError("no route to host"), Outcome.TRY_AGAIN),
    (requests.Timeout("read timed out"), Outcome.TRY_AGAIN),
])
def test_library_errors_to_outcome(tmp_path: Path, error: Exception,
                                   outcome: Outcome) -> None:
    garmin = GarminConnect(tmp_path / "garmin", Factory(error))
    assert garmin.send(fit_file(tmp_path)) == outcome


@pytest.mark.case("S-GAR-06")
@pytest.mark.asyncio
async def test_the_port_runs_off_the_event_loop_and_times_out(
        tmp_path: Path) -> None:
    fit = fit_file(tmp_path)
    factory = Factory(accepted())
    assert await GarminConnect(tmp_path / "g", factory).upload(
        fit, "ERG check") == Outcome.CREATED
    slow = Factory(accepted())
    slow.release = threading.Event()
    garmin = GarminConnect(tmp_path / "g", slow, timeout=0.05)
    try:
        assert await garmin.upload(fit, "ERG check") == Outcome.TRY_AGAIN
    finally:
        slow.release.set()
        await asyncio.sleep(0.05)


@pytest.mark.case("S-GAR-07")
def test_sign_in_starts_afresh_and_stores_the_tokens(tmp_path: Path) -> None:
    factory = Factory()
    tokens = tmp_path / "garmin"
    garmin = GarminConnect(tokens, factory)
    codes = iter(["123456"])
    assert garmin.sign_in("me@example.com", "secret",
                          lambda: next(codes)) == "Ferran"
    old, made = factory.made
    assert (old.args, old.calls) == ((), [("logout", str(tokens))])
    assert made.args == ("me@example.com", "secret")
    assert made.kwargs["prompt_mfa"]() == "123456"
    assert made.calls == [("login", str(tokens))]
    assert garmin.check() == "Ferran"
    assert factory.made[2].args == () and factory.made[2].calls == [
        ("login", str(tokens))]
    garmin.sign_out()
    assert factory.made[3].calls == [("logout", str(tokens))]


@pytest.mark.case("S-GAR-07")
def test_logout_forgets_the_password_like_the_library(
        tmp_path: Path) -> None:
    garmin = FakeGarmin(Tokens(), None, "me@example.com", "secret")
    garmin.logout(str(tmp_path))
    with pytest.raises(GarminConnectAuthenticationError):
        garmin.login(str(tmp_path))
    real = Garmin("me@example.com", "secret")
    real.logout(str(tmp_path))
    assert (real.username, real.password) == (None, None)


@pytest.mark.case("S-GAR-07")
def test_account_names_fall_back(tmp_path: Path) -> None:
    assert GarminConnect(tmp_path, Factory(full_name=None)).check() == (
        "ferran.d")
    assert GarminConnect(tmp_path, Factory()).check() == "Ferran"


@pytest.mark.case("S-GAR-07")
@pytest.mark.parametrize("error", [
    GarminConnectAuthenticationError("Authentication failed (401)"),
    GarminConnectTooManyRequestsError("Too many login attempts"),
    GarminConnectConnectionError("Login failed"),
    requests.ConnectionError("offline")])
def test_sign_in_problems_come_out_as_garmin_errors(
        tmp_path: Path, error: Exception) -> None:
    garmin = GarminConnect(tmp_path, Factory(error))
    with pytest.raises(GarminError):
        garmin.sign_in("me@example.com", "wrong", lambda: "")
    with pytest.raises(GarminError):
        garmin.check()


class Wire:
    """Answers the real library's API requests instead of Garmin."""

    def __init__(self, *answers: Reply | Exception) -> None:
        self.answers = list(answers)
        self.sent: list[dict[str, Any]] = []

    def request(self, method: str, url: str, headers: dict[str, str],
                **kwargs: Any) -> Reply:
        name, handle = kwargs["files"]["file"][:2]
        self.sent.append({"method": method, "url": url,
                          "auth": headers.get("Authorization"),
                          "name": name, "body": handle.read()})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def garmin(self, *args: Any, **kwargs: Any) -> Garmin:
        made = Garmin(*args, **kwargs)
        setattr(made.client._api_session, "request", self.request)
        return made


def stored_tokens(tmp_path: Path) -> Path:
    tokens = tmp_path / "garmin"
    tokens.mkdir(mode=0o700)
    (tokens / GARMIN_TOKEN_FILE).write_text(json.dumps({
        "di_token": "access", "di_refresh_token": None,
        "di_client_id": "wow-test"}))
    return tokens


@pytest.mark.case("S-GAR-08")
@pytest.mark.parametrize(("answer", "outcome"), [
    (Reply(202, accepted()), Outcome.CREATED),
    (Reply(409, accepted([{"messages": [
        {"code": 202, "content": "Duplicate Activity."}]}])), Outcome.KNOWN),
    (Reply(500, {"message": "busy"}), Outcome.TRY_AGAIN),
    (requests.ConnectionError("offline"), Outcome.TRY_AGAIN),
])
def test_the_real_library_posts_the_file_with_the_stored_token(
        tmp_path: Path, answer: Reply | Exception, outcome: Outcome) -> None:
    wire = Wire(answer)
    fit = fit_file(tmp_path)
    garmin = GarminConnect(stored_tokens(tmp_path), wire.garmin)
    assert garmin.send(fit) == outcome
    [sent] = wire.sent
    assert (sent["method"], sent["url"], sent["auth"]) == (
        "POST", UPLOAD_URL, "Bearer access")
    assert (sent["name"], sent["body"]) == ("ride.fit", b".FIT")


@pytest.mark.case("S-GAR-08")
def test_the_real_library_reports_a_refused_token(tmp_path: Path) -> None:
    wire = Wire(Reply(401, {}), Reply(401, {}))
    garmin = GarminConnect(stored_tokens(tmp_path), wire.garmin)
    assert garmin.send(fit_file(tmp_path)) == Outcome.KEY_REFUSED
    assert len(wire.sent) == 2


@pytest.mark.case("S-GAR-08")
def test_the_real_library_without_tokens(tmp_path: Path) -> None:
    wire = Wire()
    garmin = GarminConnect(tmp_path / "garmin", wire.garmin)
    assert garmin.send(fit_file(tmp_path)) == Outcome.KEY_REFUSED
    assert wire.sent == []


@pytest.mark.case("S-GAR-08")
def test_the_token_file_name_is_the_librarys(tmp_path: Path) -> None:
    assert token_file_path(str(tmp_path)) == tmp_path / GARMIN_TOKEN_FILE
