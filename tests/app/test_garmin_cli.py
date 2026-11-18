"""wow-garmin, the Garmin Connect sign-in tool (supporting S-GAR-15)."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from garminconnect import GarminConnectAuthenticationError

from tests.adapters.test_garmin_connect import Factory, accepted, refused
from wow.adapters.garmin_connect import GarminConnect
from wow.app.garmin_cli import main, parse_args, run

CONFIG = """
[web]
cert = "c.crt"
key = "c.key"
root_cert = "r.crt"

[paths]
data = "{data}"
"""


def config(tmp_path: Path) -> Path:
    path = tmp_path / "wow.toml"
    path.write_text(CONFIG.format(data=tmp_path / "data"))
    return path


def answers(*values: str) -> Callable[[str], str]:
    given: Iterator[str] = iter(values)
    return lambda _prompt: next(given)


def account(factory: Factory) -> Callable[[Path], GarminConnect]:
    return lambda tokens: GarminConnect(tokens, factory)


@pytest.mark.case("S-GAR-15")
def test_login_asks_once_and_stores_in_the_data_directory(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    factory = Factory()
    args = parse_args(["--config", str(config(tmp_path)), "login"])
    code = run(args, account(factory), answers("me@example.com", "654321"),
               answers("secret"))
    assert code == 0
    old, made = factory.made
    assert made.args == ("me@example.com", "secret")
    assert made.kwargs["prompt_mfa"]() == "654321"
    tokens = tmp_path / "data" / "garmin"
    assert old.calls == [("logout", str(tokens))]
    assert made.calls == [("login", str(tokens))]
    assert capsys.readouterr().out == (
        f"Signed in as Ferran; tokens in {tokens}\n")


@pytest.mark.case("S-GAR-15")
def test_check_and_logout(tmp_path: Path,
                          capsys: pytest.CaptureFixture[str]) -> None:
    path = str(config(tmp_path))
    factory = Factory()
    for action in ("check", "logout"):
        assert run(parse_args(["--config", path, action]), account(factory),
                   answers(), answers()) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Tokens accepted for Ferran"
    assert out[1].startswith("Tokens deleted from ")
    refusing = Factory(GarminConnectAuthenticationError("401"))
    assert run(parse_args(["--config", path, "check"]), account(refusing),
               answers(), answers()) == 1
    assert capsys.readouterr().err == "Garmin Connect: 401\n"


@pytest.mark.case("S-GAR-15")
@pytest.mark.parametrize(("answer", "as_import", "code", "word"), [
    (accepted(), False, 0, "created"),
    (accepted(), True, 0, "created"),
    (refused(409), False, 0, "known"),
    (refused(401), False, 1, "key_refused"),
])
def test_upload_one_file_by_hand(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], answer: object,
        as_import: bool, code: int, word: str) -> None:
    fit = tmp_path / "ride.fit"
    fit.write_bytes(b".FIT")
    factory = Factory(answer)
    argv = ["--config", str(config(tmp_path)), "upload", str(fit)]
    args = parse_args(argv + (["--import"] if as_import else []))
    assert run(args, account(factory), answers(), answers()) == code
    assert factory.made[0].calls == [
        ("import" if as_import else "upload", str(fit))]
    assert capsys.readouterr().out == f"{fit}: {word}\n"


@pytest.mark.case("S-GAR-15")
def test_main_refuses_a_missing_file_without_going_online(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "nothing.fit"
    with pytest.raises(SystemExit) as stopped:
        main(["--config", str(config(tmp_path)), "upload", str(missing)])
    assert stopped.value.code == 1
    assert capsys.readouterr().err == f"{missing}: no such file\n"
