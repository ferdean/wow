"""Workouts as intervals.icu sends them (S6 files of 13 Nov 2026) and the
built-in ramp test, parsed and planned (L1)."""

import json
from fractions import Fraction
from importlib import resources
from pathlib import Path
from typing import Any

import pytest

from tests.support.timeline import TESTDATA, load_json
from wow.core.intervals_doc import block_label, parse_builtin, parse_workout
from wow.core.numbers import round_half_up
from wow.core.plan import make_plan
from wow.core.workout import PowerTarget, PowerUnit, StepKind, Workout

EVENTS: list[dict[str, Any]] = load_json("intervals/events.json")
LIBRARY: list[dict[str, Any]] = load_json("intervals/workouts.json")
PLANS = sorted((TESTDATA / "workouts").glob("*.plan.json"))


def workout(items: list[dict[str, Any]], item_id: int) -> Workout:
    item = next(i for i in items if i["id"] == item_id)
    return parse_workout(f"test:{item_id}", item["name"], None,
                         item["workout_doc"])


def one_step(step: dict[str, Any], zones: list[Any] | None = None
             ) -> Workout:
    doc: dict[str, Any] = {"steps": [step]}
    if zones is not None:
        doc["zoneTimes"] = zones
    return parse_workout("test:one", "One", None, doc)


VO2_3030 = 1
TEST_WORKOUT = 2


@pytest.mark.case("T-WKO-01")
@pytest.mark.req("APP-204", "APP-302")
@pytest.mark.parametrize("ftp", [250, 300])
def test_s6_percent_scales_with_ftp_and_watts_do_not(ftp: int) -> None:
    plan = make_plan(workout(LIBRARY, VO2_3030), ftp)
    by_start = {s.start: s for s in plan.steps}
    assert by_start[1140.0].power == 330
    assert by_start[1500.0].power == ftp / 2


@pytest.mark.case("T-WKO-02")
@pytest.mark.req("APP-205")
def test_ranges_ride_at_their_midpoint() -> None:
    steps = workout(LIBRARY, TEST_WORKOUT).blocks
    assert steps[0].steps[0].target == PowerTarget(90.0, PowerUnit.PERCENT_FTP)
    assert steps[1].steps[0].target == PowerTarget(160.0, PowerUnit.WATTS)
    assert steps[0].steps[0].end is None and steps[1].steps[0].end is None


@pytest.mark.case("T-WKO-03")
@pytest.mark.req("APP-204", "APP-205")
def test_zone_two_rides_at_the_middle_of_its_zone_times() -> None:
    plan = make_plan(workout(LIBRARY, VO2_3030), 250)
    first = plan.steps[0]
    assert first.kind == StepKind.ERG
    assert first.power is not None and round_half_up(first.power) == 163


@pytest.mark.case("T-WKO-04")
@pytest.mark.req("APP-205", "APP-206")
@pytest.mark.parametrize("step", [
    {"duration": 60, "power": {"units": "power_zone", "value": 7}},
    {"duration": 60, "power": {"units": "power_zone", "value": 9}},
    {"duration": 60, "hr": {"units": "hr_zone", "value": 2}},
    {"duration": 60, "pace": {"units": "pace_zone", "value": 2}},
    {"duration": 60, "power": {"units": "%mmp", "value": 70}},
], ids=["zone-7", "unknown-zone", "heart-rate", "pace", "mmp"])
def test_targets_the_app_cannot_apply_are_marked(step: dict[str, Any]) -> None:
    zones = next(i for i in LIBRARY if i["id"] == VO2_3030)[
        "workout_doc"]["zoneTimes"]
    plan = make_plan(one_step(step, zones), 250)
    assert plan.steps[0].kind == StepKind.UNSUPPORTED
    assert plan.steps[0].power is None and plan.duration == 60


@pytest.mark.case("T-WKO-05")
@pytest.mark.req("APP-204", "APP-205")
def test_ramps_keep_both_ends_and_their_direction() -> None:
    up = make_plan(workout(LIBRARY, TEST_WORKOUT), 250).steps[2]
    assert (up.power, up.end_power, up.ramp) == (
        Fraction(125), Fraction(375, 2), True)
    down = make_plan(workout(LIBRARY, VO2_3030), 250).steps[-2]
    assert (down.power, down.end_power) == (Fraction(170), Fraction(120))
    assert down.power_at(down.start + down.duration / 2) == 145


@pytest.mark.case("T-WKO-06")
@pytest.mark.req("APP-204")
def test_free_ride_has_no_target() -> None:
    last = make_plan(workout(LIBRARY, VO2_3030), 250).steps[-1]
    assert last.kind == StepKind.FREE_RIDE
    assert last.power is None and last.duration == 300


@pytest.mark.case("T-WKO-07")
@pytest.mark.req("APP-204")
def test_a_nested_repeat_is_one_block_of_twelve_steps() -> None:
    parsed = workout(LIBRARY, VO2_3030)
    block = parsed.blocks[2]
    assert (block.label, block.repeats, block.duration) == ("Set 1", 6, 360)
    plan = make_plan(parsed, 250)
    assert len([s for s in plan.steps if s.block == 2]) == 12
    assert block_label("Block 1 - SS 15min\n3x") == "Block 1 - SS 15min"
    assert block_label("3x") is None


@pytest.mark.case("T-WKO-08")
@pytest.mark.req("APP-209")
def test_step_text_and_warm_up_marks_become_cues() -> None:
    ramp = parse_builtin(json.loads(resources.files("wow.builtin").joinpath(
        "ramp-test.json").read_text("utf-8")))
    plan = make_plan(ramp, 250)
    assert plan.steps[1].text == "Warm-up: a little harder"
    assert plan.steps[-1].text == "Cool-down"
    vo2 = make_plan(workout(LIBRARY, VO2_3030), 250)
    assert vo2.steps[0].text == "Warm-up" and vo2.steps[-2].text == (
        "Cool-down")


@pytest.mark.case("T-WKO-09")
@pytest.mark.req("APP-203")
@pytest.mark.parametrize("path", PLANS, ids=[p.stem for p in PLANS])
def test_every_s6_plan_matches_its_fixture(path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    items = EVENTS if fixture["source"].endswith("events.json") else LIBRARY
    plan = make_plan(workout(items, fixture["id"]), fixture["ftp"])
    rows = [[s.start, s.end,
             None if s.power is None else round_half_up(s.power),
             None if s.end_power is None else round_half_up(s.end_power),
             str(s.kind)] for s in plan.steps]
    assert rows == fixture["steps"]
    assert plan.duration == fixture["duration_intervals_icu"]


@pytest.mark.case("T-WKO-11")
@pytest.mark.req("APP-211")
def test_the_ramp_test_runs_as_designed() -> None:
    form = json.loads(resources.files("wow.builtin").joinpath(
        "ramp-test.json").read_text("utf-8"))
    ramp = parse_builtin(form)
    plan = make_plan(ramp, 250)
    assert [(s.duration, s.power) for s in plan.steps[:3]] == [
        (600.0, Fraction(120)), (180.0, Fraction(150)),
        (120.0, Fraction(100))]
    block = ramp.blocks[3]
    assert block.repeats == 1 and len(block.steps) == 25
    assert [s.power for s in plan.steps[3:28]] == list(range(120, 601, 20))
    assert {s.duration for s in plan.steps[3:28]} == {60}
    assert plan.steps[-1].kind == StepKind.FREE_RIDE
    assert plan.steps[-1].duration == 300 and plan.duration == 2700
