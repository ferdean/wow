from typing import Any

import pytest

from tests.support.timeline import case_names, run_case
from wow.core.ride import RIDE_FORMS, Ride, Tick

DIRECTORY = "timelines/ride"

REQUIREMENTS = {
    "T-RID-01": ("APP-301",),
    "T-RID-02": ("APP-301",),
    "T-RID-03": ("APP-301",),
    "T-RID-04": ("APP-117",),
    "T-RID-05": ("APP-116",),
    "T-RID-06": ("APP-304", "APP-605"),
    "T-RID-18": ("APP-825",),
}


def cases() -> list[Any]:
    return [
        pytest.param(
            name, id=name,
            marks=[pytest.mark.case(name[:8]),
                   pytest.mark.req(*REQUIREMENTS.get(name[:8], ()))])
        for name in case_names(DIRECTORY)
    ]


@pytest.mark.parametrize("name", cases())
def test_timeline(name: str) -> None:
    actual, expected = run_case(DIRECTORY, name, Ride, RIDE_FORMS, Tick())
    assert actual == expected


def run(name: str) -> list[list[Any]]:
    actual, _ = run_case(DIRECTORY, name, Ride, RIDE_FORMS, Tick())
    return actual


def journal(timeline: list[list[Any]], event: str) -> list[list[Any]]:
    return [[at, action] for at, action in timeline
            if action["type"] == "journal" and action["event"] == event]


@pytest.mark.case("T-RID-01")
@pytest.mark.req("APP-301")
def test_nothing_is_recorded_before_the_first_power() -> None:
    timeline = run("T-RID-01-first-power")
    before = [action for at, action in timeline if at < 14]
    assert {a["type"] for a in before} == {"journal", "set_trainer"}
    assert all(a["t_ride"] is None for a in before if a["type"] == "journal")
    assert journal(timeline, "ride_started")[0][0] == 14


@pytest.mark.case("T-RID-03")
@pytest.mark.req("APP-301")
def test_cancel_records_no_ride() -> None:
    for name in ("T-RID-03-cancel", "T-RID-03-timeout"):
        timeline = run(name)
        assert journal(timeline, "ride_started") == []
        assert journal(timeline, "step_started") == []


@pytest.mark.case("T-RID-06")
@pytest.mark.req("APP-304", "APP-605")
def test_each_command_leads_its_boundary_by_the_lead_time() -> None:
    timeline = run("T-RID-06-boundaries")
    sends = [at for at, a in timeline
             if a["type"] == "set_trainer" and a["command"]["type"] == "erg"]
    starts = [at for at, _ in journal(timeline, "step_started")]
    assert [round(b - a, 6) for a, b in zip(sends[1:], starts[1:])] == [
        1.5] * 6


def ended(timeline: list[list[Any]]) -> list[tuple[float, str | None]]:
    finished = journal(timeline, "finished")
    return [(at, a["data"]["cause"]) for at, a in finished] + [
        (at, None) for at, a in timeline if a["type"] == "ended"
        and a["cause"] != "finished"]


@pytest.mark.case("T-RID-18")
@pytest.mark.req("APP-825")
@pytest.mark.parametrize(("name", "at"), [
    ("T-RID-18-running", 1810.0), ("T-RID-18-workout-done", 1810.0),
    ("T-RID-18-paused", 1900.0), ("T-RID-18-power-1799", 3609.0),
    ("T-RID-18-tap-1799", 3609.0)])
def test_a_ride_left_alone_finishes_after_30_minutes(
        name: str, at: float) -> None:
    timeline = run(name)
    assert ended(timeline) == [(at, "idle")]
    last = [a for t, a in timeline if t == at]
    assert last[-1] == {"type": "ended", "cause": "finished"}
    assert {"type": "set_trainer", "command": {
        "type": "resistance", "level_raw": 0}} in last
