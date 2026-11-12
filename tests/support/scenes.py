"""Scripted view states of the core (test plan 3.1), shared by the view
tests and the golden views in testdata/display/."""

from typing import Any

from wow.core.devices import LinkState, Range, TrainerCapabilities
from wow.core.plan import make_plan
from wow.core.ride import PowerSeen, Ride, Start, Tick, TrainerLink
from wow.core.view import (
    home_screen,
    pre_ride_screen,
    ride_screen,
    ride_warnings,
    view_state,
    workout_card,
)
from wow.core.workout import Block, PowerTarget, PowerUnit, Step, Workout

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


def scenes() -> dict[str, dict[str, Any]]:
    plan = make_plan(THIRTY_THIRTY, 250)
    card = workout_card(THIRTY_THIRTY, plan, "builtin")
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
    }
