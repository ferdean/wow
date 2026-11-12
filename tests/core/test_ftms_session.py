from typing import Any

import pytest

from tests.support.timeline import case_names, run_case
from wow.core.devices import Erg, Range, TrainerCapabilities
from wow.core.ftms_session import (
    SESSION_FORMS, FtmsSession, LinkUp, Phase, SetCommand, Tick,
)

DIRECTORY = "timelines/ftms_session"

REQUIREMENTS = {
    "T-SES-01": ("APP-104",),
    "T-SES-02": ("APP-105",),
    "T-SES-03": ("APP-105",),
    "T-SES-04": ("APP-105",),
    "T-SES-05": ("APP-106",),
    "T-SES-06": ("APP-107",),
    "T-SES-07": ("APP-103", "APP-107"),
    "T-SES-08": ("APP-105", "APP-502"),
    "T-SES-09": ("APP-801",),
    "T-SES-10": ("APP-320",),
}


def case_id(name: str) -> str:
    return name[:8]


def cases() -> list[Any]:
    return [
        pytest.param(
            name, id=name,
            marks=[pytest.mark.case(case_id(name)),
                   pytest.mark.req(*REQUIREMENTS.get(case_id(name), ()))])
        for name in case_names(DIRECTORY)
    ]


def run(name: str) -> tuple[list[list[Any]], list[list[Any]]]:
    return run_case(DIRECTORY, name, FtmsSession, SESSION_FORMS, Tick())


def writes(timeline: list[list[Any]]) -> list[tuple[float, str]]:
    return [(at, action["data"]) for at, action in timeline
            if action["type"] == "write"]


@pytest.mark.parametrize("name", cases())
def test_timeline(name: str) -> None:
    actual, expected = run(name)
    assert actual == expected


@pytest.mark.case("T-SES-04")
@pytest.mark.req("APP-105")
def test_control_requested_every_two_seconds_while_refused() -> None:
    actual, _ = run("T-SES-04-refused")
    requests = [at for at, data in writes(actual) if data == "00"]
    refused = [at for at in requests if 10.0 <= at <= 610.0]
    gaps = {round(b - a, 6) for a, b in zip(refused, refused[1:])}
    assert gaps == {2.0}
    assert refused[0] == 10.0 and refused[-1] == 610.0


@pytest.mark.case("T-SES-05")
@pytest.mark.req("APP-106")
def test_superseded_target_is_never_written() -> None:
    actual, _ = run("T-SES-05-latest-wins")
    assert "054f01" not in [data for _, data in writes(actual)]


@pytest.mark.case("T-SES-06")
@pytest.mark.req("APP-107")
def test_silent_trainer_gets_the_command_every_thirty_seconds() -> None:
    actual, _ = run("T-SES-06-no-answer")
    resent = [at for at, data in writes(actual) if data == "05c800"][1:]
    assert resent[0] == 40.0
    assert {round(b - a, 6) for a, b in zip(resent, resent[1:])} == {30.0}
    assert resent[-1] == 610.0


@pytest.mark.case("T-SES-07")
@pytest.mark.req("APP-103", "APP-107")
def test_erg_unavailable_after_not_supported() -> None:
    session = FtmsSession()
    capabilities = TrainerCapabilities(Range(50, 600, 1), Range(0, 100, 1),
                                       True, False)
    session.handle(LinkUp(capabilities), 0.0)
    session.handle(_indication("800001"), 0.2)
    session.handle(_indication("800701"), 0.4)
    session.handle(SetCommand(Erg(200)), 5.0)
    session.handle(_indication("800502"), 5.2)
    remaining = session.capabilities()
    assert remaining is not None and remaining.power is None
    assert remaining.resistance == Range(0, 100, 1)
    assert session.phase == Phase.READY and session.in_control()


def _indication(hex_text: str) -> Any:
    return SESSION_FORMS.load({"type": "indication", "data": hex_text})
