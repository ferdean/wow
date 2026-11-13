import json
from importlib import resources
from typing import Any

import pytest

from tests.support.timeline import load_json
from wow.core.intervals_doc import WorkoutError, parse_builtin, parse_workout
from wow.core.plan import make_plan

PLAIN = load_json("workouts/plain-steps.workout_doc.json")


def plan_rows(ftp: int) -> list[dict[str, Any]]:
    workout = parse_workout("test:plain", "Plain", None, PLAIN["workout_doc"])
    plan = make_plan(workout, ftp)
    return [{"start": s.start, "end": s.end, "block": s.block,
             "power": None if s.power is None else float(s.power)}
            for s in plan.steps]


@pytest.mark.case("T-WKO-01")
@pytest.mark.req("APP-204", "APP-302")
@pytest.mark.parametrize("ftp", [250, 300])
def test_percent_scales_with_ftp_and_watts_do_not(ftp: int) -> None:
    assert plan_rows(ftp) == PLAIN["plans"][str(ftp)]


@pytest.mark.case("T-WKO-01")
@pytest.mark.req("APP-204", "APP-302")
def test_plan_keeps_order_text_and_duration() -> None:
    workout = parse_workout("test:plain", "Plain", "d", PLAIN["workout_doc"])
    plan = make_plan(workout, 250)
    assert plan.plan_id == "test:plain@250"
    assert plan.duration == 720.0
    assert [s.text for s in plan.steps][:2] == ["Warm-up", None]
    assert [b.repeats for b in workout.blocks] == [1, 2, 1, 1]
    assert workout.blocks[1].label == "Two sets"


BUILTINS = sorted(
    p.name for p in resources.files("wow.builtin").iterdir()
    if p.name.endswith(".json"))


@pytest.mark.case("S-WKO-01")
@pytest.mark.parametrize("name", BUILTINS)
def test_builtin_workouts_parse(name: str) -> None:
    form = json.loads(
        resources.files("wow.builtin").joinpath(name).read_text("utf-8"))
    workout = parse_builtin(form)
    assert workout.ref == f"builtin:{form['id']}"
    assert make_plan(workout, 250).duration > 0


@pytest.mark.case("S-WKO-01")
@pytest.mark.parametrize("doc", [
    {"steps": []},
    {"steps": [{"power": {"units": "w", "value": 100}}]},
    {"steps": [{"reps": 0, "steps": [{"duration": 1, "power": {
        "units": "w", "value": 1}}]}]},
    {"steps": ["text"]},
    {"steps": [{"reps": 2, "steps": ["text"]}]},
], ids=["empty", "no-duration", "zero-reps", "not-an-object",
        "inner-not-an-object"])
def test_malformed_documents_are_refused(doc: dict[str, Any]) -> None:
    with pytest.raises(WorkoutError):
        parse_workout("test:x", "X", None, doc)


@pytest.mark.case("S-WKO-01")
def test_unknown_builtin_schema_is_refused() -> None:
    with pytest.raises(WorkoutError):
        parse_builtin({"schema": 2})
