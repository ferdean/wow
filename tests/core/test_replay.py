"""A ride rebuilt from its journal (L2, T-RID-19)."""

from typing import Any

import pytest

from tests.core.test_ride_controls import (
    D100, STARTED, Rider, erg, thirty_thirty, workout,
)
from wow.core.replay import rebuild, tick_until
from wow.core.ride import (
    IntensityStep, Journal, Pause, ResistanceStep, Resume, Ride, SetTrainer,
    Skip, SwitchMode, TrainerLink,
)
from wow.core.vocab import Mode
from wow.core.workout import Block, free_ride_workout

PLAN = workout(Block(None, 1, (erg(120, 150),)), thirty_thirty(8),
               Block(None, 1, (erg(300, 200),)))


def records(rider: Rider) -> list[dict[str, Any]]:
    return [{"type": a.event, "t_ride": a.t_ride, "mono_ms": t * 1000,
             **a.data} for t, a in rider.log if isinstance(a, Journal)]


def state(ride: Ride, now: float) -> tuple[Any, ...]:
    return (ride.phase, ride.step, ride.intensity_pct, ride.shown_mode,
            ride.resistance_pct, ride.command, ride.free_ride_target,
            round(ride.plan_time(now), 6), round(ride.ride_time(now), 6))


def commands_after(ride: Ride, start: float, until: float) -> list[Any]:
    return [a.command for a in tick_until(ride, until)
            if isinstance(a, SetTrainer)] if start <= until else []


@pytest.mark.case("T-RID-19")
@pytest.mark.req("APP-809")
def test_the_journal_rebuilds_the_same_ride() -> None:
    rider = Rider(PLAN)
    rider.at(STARTED + 60, IntensityStep(1))
    rider.at(STARTED + 130, SwitchMode(Mode.RESISTANCE))
    rider.do(ResistanceStep(1))
    rider.do(ResistanceStep(1))
    rider.at(STARTED + 152, ResistanceStep(-1))
    rider.at(STARTED + 200, Pause())
    rider.at(STARTED + 230, Resume())
    rider.at(STARTED + 250, TrainerLink(False))
    rider.at(STARTED + 262, TrainerLink(True))
    rider.at(STARTED + 300, Skip())
    rider.at(STARTED + 330)
    now = rider.now
    rebuilt = rebuild(records(rider), PLAN, until=now)
    assert state(rebuilt, now) == state(rider.ride, now)
    later = now + 400
    assert commands_after(rebuilt, now, later) == commands_after(
        rider.ride, now, later)


@pytest.mark.case("T-RID-19")
@pytest.mark.req("APP-809")
def test_a_shifted_free_ride_keeps_its_power_and_pause() -> None:
    rider = Rider(free_ride_workout(), caps=D100)
    rider.at(STARTED + 20, SwitchMode(Mode.ERG, 183))
    rider.do(IntensityStep(1))
    rider.at(STARTED + 40, Pause())
    now = rider.now + 5
    shift = 5000.0
    rebuilt = rebuild(records(rider), free_ride_workout(), shift,
                      now + shift)
    assert state(rebuilt, now + shift) == state(rider.ride, now)
