"""Scripted view states of the core (test plan 3.1), shared by the view
tests and the golden views in testdata/display/."""

from datetime import date
from typing import Any

from tests.support.timeline import load_json
from wow.app.workout_catalog import load_builtin, planned_on, rides_of
from wow.core.devices import LinkState, Range, TrainerCapabilities
from wow.core.metrics import ride_metrics
from wow.core.plan import make_plan
from wow.core.ride import (
    Pause, PowerSeen, ResistanceStep, Ride, Start, SwitchMode, Tick,
    TrainerLink,
)
from wow.core.view import (
    calibration_screen,
    history_entry,
    history_screen,
    home_screen,
    recovery_offer,
    pre_ride_screen,
    ride_screen,
    ride_warnings,
    summary_screen,
    view_state,
    workout_card,
)
from wow.core.vocab import Mode, UploadState, WarningKind
from wow.core.workout import (
    Block, PowerTarget, PowerUnit, Step, Workout, free_ride_workout,
)

D100 = TrainerCapabilities(Range(50, 600, 1), Range(0, 100, 1), True, False)

THIRTY_THIRTY = Workout(
    "builtin:test-3030",
    "Warm-up and 3 x 30/30",
    None,
    (
        Block(
            None,
            1,
            (Step(60.0, PowerTarget(140, PowerUnit.WATTS), "Warm-up"),),
        ),
        Block(
            "30/30",
            3,
            (
                Step(30.0, PowerTarget(88, PowerUnit.PERCENT_FTP), None),
                Step(30.0, PowerTarget(140, PowerUnit.WATTS), None),
            ),
        ),
    ),
)

LIMITED = Workout(
    "builtin:test-limited",
    "Above the range",
    None,
    (
        Block(
            None,
            1,
            (Step(60.0, PowerTarget(650, PowerUnit.WATTS), "Too much"),),
        ),
    ),
)


def started_ride(
    workout: Workout = THIRTY_THIRTY,
    start: float = 100.0,
    first_power: float | None = 110.0,
) -> Ride:
    ride = Ride()
    ride.handle(TrainerLink(True), start)
    ride.handle(Start(workout, 250, D100, 1.5), start)
    if first_power is not None:
        ride.handle(PowerSeen(1), first_power)
    return ride


def advance(ride: Ride, until: float) -> None:
    deadline = ride.next_deadline()
    while deadline is not None and deadline <= until:
        ride.handle(Tick(), deadline)
        deadline = ride.next_deadline()


def envelope(view: dict[str, Any]) -> dict[str, Any]:
    return {"type": "view", "seq": 1, "sent_mono_ms": 0.0, **view}


def card_of(workout: Workout, source: str = "builtin") -> dict[str, Any]:
    return workout_card(workout, make_plan(workout, 250), source,
                        workout.ref, workout.name)


def ramp_test() -> Workout:
    (ramp,) = [w for w in load_builtin() if w.ref == "builtin:ramp-test"]
    return ramp


def long_ride_scenes() -> dict[str, dict[str, Any]]:
    (entry,) = [e for e in planned_on(load_json("intervals/events.json"),
                                      date(2026, 11, 14))]
    assert entry.workout is not None
    ride = Ride()
    ride.handle(TrainerLink(True), 100.0)
    ride.handle(Start(entry.workout, 250, D100, 1.0), 100.0)
    ride.handle(PowerSeen(1), 101.0)
    advance(ride, 101.0 + 3886.0)
    sweet_spot = view_state(
        ride_screen(ride, 101.0 + 3886.0, 225, 155), LinkState.CONNECTED,
        LinkState.CONNECTED, 80, ride_warnings(ride, []), None)
    advance(ride, 101.0 + 6307.0)
    done = view_state(
        ride_screen(ride, 101.0 + 6307.0, 48, 113), LinkState.CONNECTED,
        LinkState.CONNECTED, 80, ride_warnings(ride, []), None)
    return {"ride_long_step_left": envelope(sweet_spot),
            "ride_workout_done_after_an_hour": envelope(done)}


def sl05_scenes() -> dict[str, dict[str, Any]]:
    paused = started_ride()
    advance(paused, 150.0)
    paused.handle(Pause(), 150.0)
    switched = started_ride()
    advance(switched, 140.0)
    switched.handle(SwitchMode(Mode.RESISTANCE), 140.0)
    switched.handle(ResistanceStep(1), 140.5)
    free = Ride()
    free.handle(TrainerLink(True), 100.0)
    free.handle(Start(free_ride_workout(), 250, D100, 1.0), 100.0)
    free.handle(PowerSeen(90), 101.0)
    free.handle(SwitchMode(Mode.ERG, 183), 400.0)
    plan = make_plan(THIRTY_THIRTY, 250)
    connected = LinkState.CONNECTED

    def ride(state: Ride, at: float) -> dict[str, Any]:
        return envelope(view_state(ride_screen(state, at, 182, 141),
                                   connected, connected, 80,
                                   ride_warnings(state, []), None))

    return {
        "ride_paused": ride(paused, 170.0),
        "ride_resistance_block": ride(switched, 141.0),
        "ride_free_ride_by_power": ride(free, 401.0),
        "pre_ride_free_ride": envelope(view_state(pre_ride_screen(
            make_plan(free_ride_workout(), 250), connected, (), True),
            connected, connected, 80, [], None)),
        "pre_ride_block_in_resistance": envelope(view_state(pre_ride_screen(
            plan, connected, (Mode.ERG, Mode.RESISTANCE)), connected,
            connected, 80, [], None)),
    }


def sl07_scenes() -> dict[str, dict[str, Any]]:
    builtin = [card_of(ramp_test()), card_of(THIRTY_THIRTY)]
    links = (LinkState.NOT_FOUND, LinkState.NOT_FOUND, None)
    metrics = ride_metrics([180] * 3600, [130] * 3600, 250,
                           (55, 75, 90, 105, 120))
    return {
        "home_recovery": envelope(view_state(home_screen(
            builtin, recovery=recovery_offer(
                "2026-11-15T071500Z", "2026-11-15T07:15:03.120Z", 134.2)),
            *links, [{"kind": WarningKind.STORAGE_LOW, "free_mb": 812},
                     {"kind": WarningKind.SPINDOWN_REQUESTED}], None)),
        "home_recovery_finish_only": envelope(view_state(home_screen(
            builtin, recovery=recovery_offer(
                "2026-11-15T071500Z", "2026-11-15T07:15:03.120Z", None)),
            *links, [], None)),
        "history": envelope(view_state(history_screen([
            history_entry("2026-11-14T180000Z", "2026-11-14T18:00:02.400Z",
                          "Free ride", metrics, UploadState.OFF),
            history_entry("2026-11-13T170154Z", "2026-11-13T17:01:58.010Z",
                          "Long ride + SS", metrics, UploadState.DONE),
            history_entry("2026-11-12T162426Z", "2026-11-12T16:24:30.900Z",
                          "ERG check", metrics, UploadState.FAILED)],
            31512), *links, [], None)),
        "summary_past": envelope(view_state(
            summary_screen("2026-11-12T162426Z", "ERG check",
                           "2026-11-12T16:24:30.900Z", metrics,
                           UploadState.FAILED, past=True), *links, [],
            None)),
        "calibration_idle": envelope(view_state(calibration_screen(
            "idle", None, None, 0.0, ("2026-11-10T19:02:11.000Z", True),
            None), LinkState.CONNECTED, LinkState.NOT_FOUND, None, [],
            None)),
        "calibration_speed_up": envelope(view_state(calibration_screen(
            "speed_up", (0.0, 40.0), 33.7, 3.2, None, None),
            LinkState.CONNECTED, LinkState.NOT_FOUND, None, [], None)),
        "calibration_stop_pedaling": envelope(view_state(calibration_screen(
            "stop_pedaling", (0.0, 40.0), 31.5, 9.0, None, None),
            LinkState.CONNECTED, LinkState.NOT_FOUND, None, [], None)),
        "calibration_success": envelope(view_state(calibration_screen(
            "success", (0.0, 40.0), 0.0, 30.4,
            ("2026-11-15T07:40:12.000Z", True), None),
            LinkState.CONNECTED, LinkState.NOT_FOUND, None, [], None)),
        "calibration_blocked": envelope(view_state(calibration_screen(
            "idle", None, None, 0.0, None, "trainer_missing"),
            LinkState.SEARCHING, LinkState.NOT_FOUND, None, [], None)),
    }


def sl04_scenes() -> dict[str, dict[str, Any]]:
    library = rides_of(load_json("intervals/workouts.json"))
    cards = [card_of(e.workout, "library") if e.workout else workout_card(
        None, None, "library", e.ref, e.name) for e in library]
    ramp = ramp_test()
    plan = make_plan(ramp, 250)
    free = Ride()
    free.handle(TrainerLink(True), 100.0)
    free.handle(Start(ramp, 250, D100, 1.0, free_ride_level_pct=20), 100.0)
    free.handle(PowerSeen(1), 101.0)
    advance(free, 101.0 + plan.steps[-1].start + 10.0)
    power = [150] * 600 + [300] * 300 + [None] * 5 + [120] * 295
    hr = [130] * 900 + [None] * 300
    metrics = ride_metrics(power, hr, 250)
    return {
        "home_offline_with_lists": envelope(view_state(
            home_screen([card_of(ramp)], cards[:1], cards),
            LinkState.NOT_FOUND, LinkState.NOT_FOUND, None,
            [{"kind": WarningKind.WORKOUTS_OFFLINE,
              "downloaded_utc": "2026-11-14T07:00:00.000Z"}], None)),
        "pre_ride_ramp_test": envelope(view_state(
            pre_ride_screen(plan, LinkState.CONNECTED),
            LinkState.CONNECTED, LinkState.CONNECTED, 80, [], None)),
        "ride_free_ride_step": envelope(view_state(
            ride_screen(free, 101.0 + plan.steps[-1].start + 10.0, 140, 150),
            LinkState.CONNECTED, LinkState.CONNECTED, 80,
            ride_warnings(free, []), None)),
        **long_ride_scenes(),
        "summary": envelope(view_state(
            summary_screen("2026-11-14T071500Z", ramp.name,
                           "2026-11-14T07:15:00.000Z", metrics,
                           UploadState.PENDING),
            LinkState.CONNECTED, LinkState.CONNECTED, 80, [], None)),
    }


def scenes() -> dict[str, dict[str, Any]]:
    plan = make_plan(THIRTY_THIRTY, 250)
    card = workout_card(THIRTY_THIRTY, plan, "builtin", THIRTY_THIRTY.ref,
                        THIRTY_THIRTY.name)
    armed = started_ride(first_power=None)
    erg = started_ride()
    advance(erg, 180.0)
    limited = started_ride(LIMITED)
    done = started_ride()
    advance(done, 400.0)
    return {
        "home": envelope(
            view_state(
                home_screen([card]),
                LinkState.CONNECTED,
                LinkState.CONNECTED,
                80,
                [],
                None,
            )
        ),
        "pre_ride": envelope(
            view_state(
                pre_ride_screen(plan, LinkState.CONNECTED),
                LinkState.CONNECTED,
                LinkState.SEARCHING,
                None,
                [],
                None,
            )
        ),
        "pre_ride_trainer_missing": envelope(
            view_state(
                pre_ride_screen(plan, LinkState.NOT_FOUND),
                LinkState.NOT_FOUND,
                LinkState.CONNECTED,
                80,
                [],
                None,
            )
        ),
        "ride_waiting_for_power": envelope(
            view_state(
                ride_screen(armed, 105.0, None, 120),
                LinkState.CONNECTED,
                LinkState.CONNECTED,
                80,
                ride_warnings(armed, []),
                105000.0,
            )
        ),
        "ride_erg": envelope(
            view_state(
                ride_screen(erg, 180.0, 221, 158),
                LinkState.CONNECTED,
                LinkState.CONNECTED,
                80,
                ride_warnings(erg, []),
                179950.0,
            )
        ),
        "ride_erg_last_5_s": envelope(
            view_state(
                ride_screen(erg, 196.0, 219, 161),
                LinkState.CONNECTED,
                LinkState.CONNECTED,
                80,
                ride_warnings(erg, []),
                195950.0,
            )
        ),
        "ride_erg_target_limited": envelope(
            view_state(
                ride_screen(limited, 120.0, 598, 170),
                LinkState.CONNECTED,
                LinkState.CONNECTED,
                80,
                ride_warnings(limited, ["trainer_not_responding"]),
                119950.0,
            )
        ),
        "ride_erg_strap_missing": envelope(
            view_state(
                ride_screen(erg, 181.0, 220, None),
                LinkState.CONNECTED,
                LinkState.NOT_FOUND,
                None,
                ride_warnings(erg, []),
                180950.0,
            )
        ),
        "ride_workout_done": envelope(
            view_state(
                ride_screen(done, 400.0, 101, 120),
                LinkState.CONNECTED,
                LinkState.CONNECTED,
                80,
                ride_warnings(done, []),
                399950.0,
            )
        ),
        **sl04_scenes(),
        **sl05_scenes(),
        **sl07_scenes(),
    }
