import json
import os

import pytest

from tests.support.scenes import (
    D100,
    LIMITED,
    THIRTY_THIRTY,
    advance,
    scenes,
    started_ride,
)
from tests.support.timeline import TESTDATA
from wow.core.plan import make_plan
from wow.core.ride import Refused, Ride, Start
from wow.core.view import (
    Latest,
    PowerAverage,
    plan_message,
    pre_ride_screen,
    ride_screen,
    ride_warnings,
)
from wow.core.devices import LinkState
from wow.core.vocab import Problem

GOLDEN = TESTDATA / "display"


@pytest.mark.case("T-VIEW-01")
@pytest.mark.req("APP-401")
def test_erg_step_shows_everything_the_rider_needs() -> None:
    ride = started_ride()
    advance(ride, 175.0)
    screen = ride_screen(ride, 175.0, 222, 157)
    assert screen["mode"] == "erg" and not screen["waiting_for_power"]
    assert screen["target"] == 220 and screen["target_zone"] == 3
    assert screen["power"] == 222 and screen["hr_bpm"] == 157
    assert screen["step"] == {
        "index": 1,
        "count": 7,
        "left": 25.0,
        "text": None,
    }
    assert screen["next"] == {
        "kind": "erg",
        "target": 140,
        "zone": 2,
        "duration": 30.0,
    }
    assert (screen["elapsed"], screen["remaining"]) == (65.0, 175.0)
    assert screen["intensity_pct"] == 100


@pytest.mark.case("T-VIEW-01")
@pytest.mark.req("APP-401")
def test_last_step_has_no_next_and_done_has_no_step() -> None:
    ride = started_ride()
    advance(ride, 330.0)
    last = ride_screen(ride, 330.0, 140, 120)
    assert last["step"]["index"] == 6 and last["next"] is None
    advance(ride, 400.0)
    done = ride_screen(ride, 400.0, 100, 120)
    assert done["workout_done"] and done["step"] is None
    assert done["target"] is None and done["remaining"] is None


@pytest.mark.case("T-VIEW-02")
@pytest.mark.req("APP-402")
def test_power_is_the_mean_of_the_last_three_seconds() -> None:
    average = PowerAverage()
    for tenth in range(100):
        average.add(tenth * 0.1, 200 + tenth)
    assert average.value(9.95) == 285
    average.add(10.0, None)
    assert average.value(12.85) == 299
    assert average.value(12.95) is None
    assert PowerAverage().value(0.0) is None


@pytest.mark.case("T-VIEW-02")
@pytest.mark.req("APP-402")
def test_mean_rounds_half_up() -> None:
    average = PowerAverage()
    average.add(0.0, 200)
    average.add(0.5, 201)
    assert average.value(1.0) == 201


@pytest.mark.case("T-VIEW-10")
@pytest.mark.req("APP-301")
def test_armed_ride_waits_for_power_at_zero_with_the_load_set() -> None:
    ride = started_ride(first_power=None)
    screen = ride_screen(ride, 160.0, None, 110)
    assert screen["waiting_for_power"] is True
    assert screen["elapsed"] == 0.0
    assert screen["target"] == 140
    assert screen["step"]["left"] == 60.0


@pytest.mark.case("T-RID-04")
@pytest.mark.req("APP-117")
def test_pre_ride_shows_the_trainer_missing() -> None:
    plan = make_plan(THIRTY_THIRTY, 250)
    assert (
        pre_ride_screen(plan, LinkState.NOT_FOUND)["blocked"]
        == "trainer_missing"
    )
    assert pre_ride_screen(plan, LinkState.SEARCHING)["can_start"] is False
    ready = pre_ride_screen(plan, LinkState.CONNECTED)
    assert (ready["can_start"], ready["blocked"]) == (True, None)
    ride = Ride()
    assert ride.handle(Start(THIRTY_THIRTY, 250, D100, 1.5), 0.0) == [
        Refused(Problem.TRAINER_MISSING)
    ]


@pytest.mark.case("T-RID-05")
@pytest.mark.req("APP-116")
def test_missing_strap_shows_heart_rate_missing() -> None:
    hr = Latest()
    ride = started_ride()
    assert ride_screen(ride, 120.0, 140, hr.value(120.0))["hr_bpm"] is None
    hr.add(120.0, 150)
    assert hr.value(122.9) == 150 and hr.value(123.0) is None


@pytest.mark.case("S-VIEW-01")
def test_limited_target_is_a_warning_while_riding() -> None:
    ride = started_ride(LIMITED)
    assert ride_warnings(ride, ["control_refused"]) == [
        {"kind": "control_refused"},
        {"kind": "target_limited", "requested_power": 650, "sent_power": 600},
    ]
    assert ride_screen(ride, 120.0, 600, 150)["target_limited"] is True


@pytest.mark.case("S-VIEW-01")
def test_plan_segments_follow_the_intensity() -> None:
    plan = make_plan(THIRTY_THIRTY, 250)
    message = plan_message(plan, intensity_pct=105)
    assert message["plan_id"] == f"{plan.plan_id}@105%"
    first = message["segments"][:2]
    assert [(s["start_power"], s["zone"]) for s in first] == [
        (147, 2), (231, 4)]
    assert plan_message(plan)["plan_id"] == plan.plan_id


@pytest.mark.case("S-VIEW-01")
def test_plan_message_lists_segments_and_blocks() -> None:
    message = plan_message(make_plan(THIRTY_THIRTY, 250))
    assert message["type"] == "plan"
    assert [s["start_power"] for s in message["segments"]] == [
        140,
        220,
        140,
        220,
        140,
        220,
        140,
    ]
    assert message["blocks"][1] == {
        "index": 1,
        "label": "30/30",
        "repeats": 3,
        "duration": 180.0,
        "mode": "erg",
        "steps": [
            {
                "duration": 30.0,
                "kind": "erg",
                "start_power": 220,
                "end_power": 220,
                "zone": 3,
            },
            {
                "duration": 30.0,
                "kind": "erg",
                "start_power": 140,
                "end_power": 140,
                "zone": 2,
            },
        ],
    }


@pytest.mark.case("S-VIEW-01")
@pytest.mark.parametrize("name", sorted(scenes()))
def test_golden_views(name: str) -> None:
    path = GOLDEN / f"{name}.view.json"
    actual = scenes()[name]
    if os.environ.get("WOW_UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(json.dumps(actual, indent=1) + "\n")
    assert json.loads(path.read_text()) == actual


STATES_3_1 = {
    "Home": ["home_plan_and_library", "home", "home_offline_with_lists",
             "home_recovery", "home_cert_expiring"],
    "Pre-ride": ["pre_ride_ramp_test", "pre_ride_trainer_searching",
                 "pre_ride_trainer_missing", "pre_ride_strap_not_found",
                 "pre_ride_battery_low", "pre_ride_unsupported_step",
                 "pre_ride_block_in_resistance", "pre_ride_free_ride"],
    "Ride": ["ride_waiting_for_power", "ride_erg", "ride_erg_last_5_s",
             "ride_erg_target_limited", "ride_erg_trainer_dropout",
             "ride_erg_strap_dropout", "ride_trainer_not_responding",
             "ride_control_refused", "ride_paused", "ride_resistance_block",
             "ride_workout_done", "ride_free_ride_by_power",
             "ride_clock_unsynced"],
    "Summary": ["summary_off", "summary", "summary_uploading",
                "summary_done", "summary_retrying", "summary_failed",
                "summary_auth_error"],
    "Ride history": ["history", "history_empty"],
    "Calibration": ["calibration_idle", "calibration_blocked",
                    "calibration_starting", "calibration_speed_up",
                    "calibration_stop_pedaling", "calibration_success",
                    "calibration_error", "calibration_timeout"],
    "Settings": ["settings_defaults", "settings_account_saved",
                 "settings_scan_running", "settings_scan"],
}


@pytest.mark.case("T-VIEW-09")
@pytest.mark.req("APP-401", "APP-414")
@pytest.mark.parametrize("screen", sorted(STATES_3_1))
def test_every_golden_state_of_the_plan(screen: str) -> None:
    made = scenes()
    for name in STATES_3_1[screen]:
        assert name in made, name
        stored = json.loads((GOLDEN / f"{name}.view.json").read_text())
        assert stored == made[name], name
    home = {"home_recovery": ["storage_low", "spindown_requested"],
            "home_cert_expiring": ["cert_expiring", "clock_unsynced"]}
    for name, kinds in home.items():
        assert [w["kind"] for w in made[name]["warnings"]] == kinds
    uploads = {made[n]["screen"]["upload"] for n in STATES_3_1["Summary"]}
    assert uploads == {"off", "pending", "uploading", "done", "retrying",
                       "failed", "auth_error"}
    phases = {made[n]["screen"]["phase"] for n in STATES_3_1["Calibration"]}
    assert phases == {"idle", "starting", "speed_up", "stop_pedaling",
                      "success", "error", "timeout"}
    erg = made["ride_erg"]["screen"]
    assert erg["mode"] == "erg" and erg["target"] is not None
    resistance = made["ride_resistance_block"]["screen"]
    assert resistance["mode"] == "resistance"
    assert resistance["resistance_pct"] is not None
