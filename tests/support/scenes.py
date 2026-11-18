"""Scripted view states of the core (test plan 3.1), shared by the view
tests and the golden views in testdata/display/."""

from datetime import date
from typing import Any

from tests.support.timeline import TESTDATA, load_json
from wow.app.workout_catalog import load_builtin, planned_on, rides_of
from wow.core.devices import (
    DeviceKind, FoundDevice, LinkState, Range, TrainerCapabilities,
)
from wow.core.metrics import ride_metrics
from wow.core.plan import make_plan
from wow.core.ride import (
    RIDING, Pause, PowerSeen, ResistanceStep, Ride, Start, SwitchMode, Tick,
    TrainerLink,
)
from wow.core.route import Route, read_route
from wow.core.settings import DeviceRef, Settings
from wow.core.view import (
    battery_warning,
    calibration_screen,
    certificate_warning,
    clock_warning,
    settings_screen,
    history_entry,
    history_screen,
    home_screen,
    plan_message,
    recovery_offer,
    pre_ride_screen,
    ridden_route,
    ride_screen,
    ride_warnings,
    route_live,
    route_map,
    route_option,
    summary_screen,
    view_state,
    workout_card,
)
from wow.core.vocab import Mode, UploadState, WarningKind
from wow.core.workout import (
    Block, PowerTarget, PowerUnit, Step, Workout, free_ride_workout,
)

ROOT = TESTDATA.parent
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
    """Run the ride's deadlines up to until, the rider pedaling."""
    deadline = ride.next_deadline()
    while deadline is not None and deadline <= until:
        if ride.phase in RIDING:
            ride.handle(PowerSeen(150), deadline)
        ride.handle(Tick(), deadline)
        deadline = ride.next_deadline()


def envelope(view: dict[str, Any]) -> dict[str, Any]:
    return {"type": "view", "seq": 1, "sent_mono_ms": 0.0, **view}


def card_of(workout: Workout, source: str = "builtin") -> dict[str, Any]:
    return workout_card(workout, make_plan(workout, 250), source,
                        workout.ref, workout.name)


HR_STEP = Workout("test:hr", "Heart-rate step", None, (
    Block(None, 1, (Step(300.0, PowerTarget(140, PowerUnit.WATTS),
                         "Warm-up"),
                    Step(600.0, None, "Hold 140 bpm"))),))


def plans() -> dict[str, dict[str, Any]]:
    """Return the plan messages of the golden Pre-ride states, by plan_id,
    for the display's gallery."""
    found = [plan_message(make_plan(w, 250))
             for w in (THIRTY_THIRTY, ramp_test(), HR_STEP)]
    return {str(p["plan_id"]): p for p in found}


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


def _view(screen: dict[str, Any], trainer: LinkState = LinkState.CONNECTED,
          hrm: LinkState = LinkState.CONNECTED, battery: int | None = 80,
          warnings: list[dict[str, Any]] | None = None,
          data_ms: float | None = None) -> dict[str, Any]:
    return envelope(view_state(screen, trainer, hrm, battery,
                               warnings or [], data_ms))


def sl10_scenes() -> dict[str, dict[str, Any]]:
    builtin = [card_of(ramp_test()), card_of(THIRTY_THIRTY)]
    plan = make_plan(THIRTY_THIRTY, 250)
    library = rides_of(load_json("intervals/workouts.json"))
    today = [e for e in planned_on(load_json("intervals/events.json"),
                                   date(2026, 11, 14))]
    unsupported = HR_STEP
    chosen = Settings(trainer=DeviceRef("94:05:BB:03:5D:9D",
                                        "VANRYSEL-HT-9d5d"),
                      hrm=DeviceRef("E0:E2:EF:63:14:BC", "HRM200:739158"))
    found = (FoundDevice("94:05:BB:03:5D:9D", "VANRYSEL-HT-9d5d", -60,
                         DeviceKind.TRAINER),
             FoundDevice("E0:E2:EF:63:14:BC", "HRM200:739158", -55,
                         DeviceKind.HRM),
             FoundDevice("C8:4A:2D:11:22:33", "CADENCE-1816", -70,
                         DeviceKind.CADENCE))
    until = "2036-11-09T06:27:56.000Z"
    erg = started_ride()
    advance(erg, 180.0)
    ride = ride_screen(erg, 180.0, 221, 158)
    pre = pre_ride_screen(plan, LinkState.CONNECTED)
    return {
        "home_plan_and_library": _view(home_screen(
            builtin, [card_of(e.workout, "plan") for e in today
                      if e.workout],
            [card_of(e.workout, "library") for e in library if e.workout])),
        "home_cert_expiring": _view(
            home_screen(builtin), LinkState.NOT_FOUND, LinkState.NOT_FOUND,
            None, certificate_warning(12) + clock_warning(False)),
        "pre_ride_trainer_searching": _view(
            pre_ride_screen(plan, LinkState.SEARCHING), LinkState.SEARCHING,
            LinkState.SEARCHING, None),
        "pre_ride_strap_not_found": _view(pre, hrm=LinkState.NOT_FOUND,
                                          battery=None),
        "pre_ride_battery_low": _view(pre, battery=15,
                                      warnings=battery_warning(15, 20)),
        "pre_ride_unsupported_step": _view(pre_ride_screen(
            make_plan(unsupported, 250), LinkState.CONNECTED)),
        "ride_erg_trainer_dropout": _view(
            ride_screen(erg, 180.0, None, 158), trainer=LinkState.DROPOUT,
            warnings=ride_warnings(erg, [])),
        "ride_erg_strap_dropout": _view(
            ride_screen(erg, 180.0, 221, None), hrm=LinkState.DROPOUT,
            battery=80, warnings=ride_warnings(erg, [])),
        "ride_trainer_not_responding": _view(ride, warnings=ride_warnings(
            erg, ["trainer_not_responding"])),
        "ride_control_refused": _view(ride, warnings=ride_warnings(
            erg, ["control_refused"])),
        "ride_clock_unsynced": _view(ride, warnings=ride_warnings(
            erg, [], clock_warning(False))),
        "ride_battery_low": _view(ride, battery=10, warnings=ride_warnings(
            erg, [], battery_warning(10, 20))),
        "ride_erg_cadence": _view(ride_screen(erg, 180.0, 221, 158,
                                              cadence_rpm=91)),
        "history_empty": _view(history_screen([], 31512),
                               LinkState.NOT_FOUND, LinkState.NOT_FOUND,
                               None),
        "settings_defaults": _view(settings_screen(Settings(), False, until,
                                                   None),
                                   LinkState.NOT_FOUND, LinkState.NOT_FOUND,
                                   None),
        "settings_account_saved": _view(settings_screen(chosen, True, until,
                                                        None),
                                        LinkState.NOT_FOUND,
                                        LinkState.NOT_FOUND, None),
        "settings_scan_running": _view(settings_screen(
            chosen, True, until, (DeviceKind.HRM, True, ())),
            LinkState.NOT_FOUND, LinkState.NOT_FOUND, None),
        "settings_scan": _view(settings_screen(
            chosen, True, until, (DeviceKind.HRM, False, found)),
            LinkState.NOT_FOUND, LinkState.NOT_FOUND, None),
    }


def upload_scenes() -> dict[str, dict[str, Any]]:
    metrics = ride_metrics([180] * 3600, [130] * 3600, 250,
                           (55, 75, 90, 105, 120))
    states = {"off": UploadState.OFF, "uploading": UploadState.UPLOADING,
              "done": UploadState.DONE, "retrying": UploadState.RETRYING,
              "failed": UploadState.FAILED,
              "auth_error": UploadState.AUTH_ERROR}
    found = {f"summary_{name}": _view(summary_screen(
        "2026-11-15T071500Z", "Long ride + SS", "2026-11-15T07:15:03.120Z",
        metrics, state)) for name, state in states.items()}
    calibration = {
        f"calibration_{phase}": _view(calibration_screen(
            phase, band, speed, elapsed, last, None), hrm=LinkState.NOT_FOUND,
            battery=None)
        for phase, band, speed, elapsed, last in (
            ("starting", None, 0.0, 0.4, None),
            ("error", (0.0, 40.0), 0.0, 31.0,
             ("2026-11-15T07:40:12.000Z", False)),
            ("timeout", (0.0, 40.0), 12.3, 120.0,
             ("2026-11-15T07:40:12.000Z", False)))}
    return {**found, **calibration}


def garmin_scenes() -> dict[str, dict[str, Any]]:
    metrics = ride_metrics([180] * 3600, [130] * 3600, 250,
                           (55, 75, 90, 105, 120))

    def summary(upload: UploadState, garmin: UploadState
                ) -> dict[str, Any]:
        return _view(summary_screen(
            "2026-11-18T171500Z", "Long ride + SS",
            "2026-11-18T17:15:03.120Z", metrics, upload,
            garmin_upload=garmin))

    until = "2036-11-09T06:27:56.000Z"
    both = Settings(garmin_upload_on=True)
    garmin_only = Settings(upload_on=False, garmin_upload_on=True)
    return {
        "summary_garmin_done": summary(UploadState.OFF, UploadState.DONE),
        "summary_garmin_auth_error": summary(UploadState.DONE,
                                             UploadState.AUTH_ERROR),
        "summary_garmin_not_sent": summary(UploadState.DONE,
                                           UploadState.OFF),
        "history_garmin": _view(history_screen([
            history_entry("2026-11-18T171500Z", "2026-11-18T17:15:03.120Z",
                          "Long ride + SS", metrics, UploadState.OFF,
                          UploadState.DONE),
            history_entry("2026-11-17T171500Z", "2026-11-17T17:15:03.120Z",
                          "Long ride + SS", metrics, UploadState.DONE,
                          UploadState.FAILED),
            history_entry("2026-11-16T171500Z", "2026-11-16T17:15:03.120Z",
                          "ERG check", metrics, UploadState.DONE, None)],
            31512), LinkState.NOT_FOUND, LinkState.NOT_FOUND, None),
        "settings_garmin_both_on": _view(
            settings_screen(both, True, until, None, garmin_signed_in=True),
            LinkState.NOT_FOUND, LinkState.NOT_FOUND, None),
        "settings_garmin_signed_out": _view(
            settings_screen(garmin_only, True, until, None),
            LinkState.NOT_FOUND, LinkState.NOT_FOUND, None),
    }


def sl13_scenes() -> dict[str, dict[str, Any]]:
    plan = make_plan(THIRTY_THIRTY, 250)
    routes = [route_option("lake-loop.gpx", "Lake loop", 24312.4, 312.6),
              route_option("test-climb.gpx", "Test climb", 5000.0, 410.2)]
    metrics = ride_metrics([180] * 3600, [130] * 3600, 250,
                           (55, 75, 90, 105, 120))

    def summary(distance: float | None, ascent: float | None
                ) -> dict[str, Any]:
        return _view(summary_screen(
            "2026-11-17T171500Z", "Long ride + SS",
            "2026-11-17T17:15:03.120Z", metrics, UploadState.PENDING,
            route=ridden_route("Lake loop", distance, ascent)))

    return {
        "pre_ride_routes": _view(pre_ride_screen(
            plan, LinkState.CONNECTED, routes=routes, route="lake-loop.gpx")),
        "summary_route": summary(32456.7, 402.3),
    }


EXAMPLE_ROUTE = ROOT / "deploy" / "routes" / "example-loop.gpx"


def example_route() -> tuple[str, Route]:
    """Return the repository's example route and its route_id."""
    data = EXAMPLE_ROUTE.read_bytes()
    return (f"example-loop.gpx@{len(data)}",
            read_route(data, "example-loop"))


def route_maps() -> dict[str, dict[str, Any]]:
    """Return the route messages of the golden ride states, by route_id,
    for the display's gallery."""
    route_id, route = example_route()
    return {route_id: route_map(route_id, route.name, route)}


def sl14_scenes() -> dict[str, dict[str, Any]]:
    route_id, route = example_route()
    erg = started_ride()
    advance(erg, 180.0)
    paused = started_ride()
    advance(paused, 150.0)
    paused.handle(Pause(), 150.0)
    return {
        "ride_route": _view(ride_screen(
            erg, 180.0, 221, 158, route=route_live(
                route_id, route, 4712.6, 8.47, False))),
        "ride_route_paused": _view(ride_screen(
            paused, 160.0, None, 131, route=route_live(
                route_id, route, 3810.3, 6.2, True))),
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
        **sl10_scenes(),
        **upload_scenes(),
        **garmin_scenes(),
        **sl13_scenes(),
        **sl14_scenes(),
    }
