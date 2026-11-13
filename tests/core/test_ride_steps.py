"""Ramps, free-ride steps and dropouts in the ride state machine (L2)."""

from typing import Any

import pytest

from wow.core.devices import Erg, Range, Resistance, TrainerCapabilities
from wow.core.ride import (
    HrmLink, Journal, PowerSeen, Ride, SetTrainer, Start, Tick, TrainerLink,
)
from wow.core.target_policy import level_raw
from wow.core.workout import Block, PowerTarget, PowerUnit, Step, StepKind
from wow.core.workout import Workout

D100 = TrainerCapabilities(Range(50, 600, 1), Range(0, 100, 1), True, False)
WATTS = PowerUnit.WATTS


def ride_of(steps: tuple[Step, ...], lead: float = 1.5,
            free_pct: int = 0, until: float = 400.0
            ) -> list[tuple[float, Any]]:
    ride = Ride()
    workout = Workout("test:steps", "Steps", None, (Block(None, 1, steps),))
    out: list[tuple[float, Any]] = []
    ride.handle(TrainerLink(True), 0.0)
    out += [(0.0, a) for a in ride.handle(Start(
        workout, 250, D100, lead, free_ride_level_pct=free_pct), 0.0)]
    out += [(1.0, a) for a in ride.handle(PowerSeen(100), 1.0)]
    while (deadline := ride.next_deadline()) is not None and deadline < until:
        out += [(deadline, a) for a in ride.handle(Tick(), deadline)]
    return out


def commands(timeline: list[tuple[float, Any]]) -> list[tuple[float, Any]]:
    return [(round(at, 6), a.command) for at, a in timeline
            if isinstance(a, SetTrainer)]


@pytest.mark.case("T-TGT-03")
@pytest.mark.req("APP-305")
def test_a_ramp_sends_the_value_one_lead_time_ahead_every_second() -> None:
    ramp = Step(300.0, PowerTarget(125, WATTS), None,
                end=PowerTarget(187.5, WATTS))
    sent = commands(ride_of((ramp,)))
    during = [(at, c) for at, c in sent
              if 1.0 < at < 1.0 + 300.0 and isinstance(c, Erg)]
    times = [at for at, _ in during]
    assert max(b - a for a, b in zip([1.0, *times], times)) <= 1.0 + 1e-6
    for at, command in during[:-1]:
        ahead = min(at - 1.0 + 1.5, 300.0)
        assert command == Erg(round(125 + 62.5 * ahead / 300 + 1e-9))
    assert during[-1][1] == Erg(188)


@pytest.mark.case("T-TGT-03")
@pytest.mark.req("APP-305")
def test_a_ramp_down_followed_by_a_step_hands_over_at_the_lead_time() -> None:
    steps = (Step(10.0, PowerTarget(170, WATTS), None,
                  end=PowerTarget(120, WATTS)),
             Step(10.0, PowerTarget(200, WATTS), None))
    sent = commands(ride_of(steps, until=30.0))
    assert (round(1.0 + 10.0 - 1.5, 6), Erg(200)) in sent
    assert [c for _, c in sent][:3] == [Erg(170), Erg(158), Erg(153)]


@pytest.mark.case("T-RID-07")
@pytest.mark.req("APP-306", "APP-206", "APP-415")
@pytest.mark.parametrize("kind", [StepKind.FREE_RIDE, StepKind.UNSUPPORTED])
def test_free_ride_and_unsupported_steps_ride_at_the_free_ride_level(
        kind: StepKind) -> None:
    steps = (Step(10.0, PowerTarget(200, WATTS), None),
             Step(10.0, None, None, kind=kind))
    sent = commands(ride_of(steps, free_pct=35, until=15.0))
    assert sent[-1] == (round(1.0 + 10.0 - 1.5, 6), Resistance(35))
    assert level_raw(35, Range(10, 200, 10)) == 80


@pytest.mark.case("S-RID-02")
def test_dropouts_are_journaled_while_riding_only() -> None:
    ride = Ride()
    workout = Workout("test:d", "D", None, (Block(None, 1, (
        Step(60.0, PowerTarget(150, WATTS), None),)),))
    ride.handle(TrainerLink(True), 0.0)
    ride.handle(HrmLink(True), 0.0)
    ride.handle(Start(workout, 250, D100, 1.5), 0.0)
    assert ride.handle(HrmLink(False), 0.5) == []
    ride.handle(HrmLink(True), 0.6)
    ride.handle(PowerSeen(100), 1.0)
    lost = ride.handle(TrainerLink(False), 5.0)
    again = ride.handle(TrainerLink(False), 6.0)
    back = ride.handle(TrainerLink(True), 9.0)
    assert lost == [Journal("dropout_start", 4.0, {"device": "trainer"})]
    assert again == []
    assert back == [Journal("dropout_end", 8.0, {"device": "trainer"})]


@pytest.mark.case("S-RID-02")
def test_step_started_names_its_target_and_kind() -> None:
    steps = (Step(5.0, PowerTarget(150, WATTS), None),
             Step(5.0, None, None, kind=StepKind.FREE_RIDE))
    started = [a.data for _, a in ride_of(steps, until=20.0)
               if isinstance(a, Journal) and a.event == "step_started"]
    assert [(d["target"], d["kind"]) for d in started] == [
        (150, StepKind.ERG), (None, StepKind.FREE_RIDE)]
