"""Ride controls on the core (L2): pause, skip, intensity, modes,
resistance levels, free ride, end of workout, Finish and Discard."""

from typing import Any

import pytest

from wow.core.devices import Erg, Range, Resistance, TrainerCapabilities
from wow.core.ride import (
    ABANDON_AFTER, Discard, Ended, Finish, FreeRideLevel, FreeRidePowerStep,
    HrmLink, IntensityStep, Journal, Pause, PowerSeen, Refused,
    ResistanceStep, Resume, Ride, RideAction, RideEvent, RidePhase,
    SetTrainer, Skip, Start, SwitchMode, Tick, TrainerLink,
)
from wow.core.view import ride_screen
from wow.core.vocab import Mode, Problem
from wow.core.workout import (
    Block, PowerTarget, PowerUnit, Step, StepKind, Workout, free_ride_workout,
)

D100 = TrainerCapabilities(Range(50, 600, 1), Range(0, 100, 1), True, False)
STARTED = 1.0


def erg(seconds: float, watts: int, end: int | None = None) -> Step:
    return Step(seconds, PowerTarget(watts, PowerUnit.WATTS), None,
                end=None if end is None else PowerTarget(end,
                                                         PowerUnit.WATTS))


def workout(*blocks: Block) -> Workout:
    return Workout("test:controls", "Controls", None, blocks)


def thirty_thirty(reps: int = 3) -> Block:
    return Block("30/30", reps, (erg(30, 330), erg(30, 140)))


class Rider:
    """A ride driven on a mono clock; the first power comes at 1 s."""

    def __init__(self, ride_workout: Workout, **start: Any) -> None:
        self.ride = Ride()
        self.now = 0.0
        self.log: list[tuple[float, RideAction]] = []
        self.ride.handle(TrainerLink(True), 0.0)
        self.ride.handle(HrmLink(True), 0.0)
        self.do(Start(ride_workout, 250, start.pop("caps", D100),
                      start.pop("lead", 1.5), **start))
        self.at(STARTED, PowerSeen(120))

    def at(self, mono: float, event: RideEvent | None = None
           ) -> list[RideAction]:
        deadline = self.ride.next_deadline()
        while deadline is not None and deadline <= mono:
            self.now = deadline
            self.log += [(deadline, a)
                         for a in self.ride.handle(Tick(), deadline)]
            deadline = self.ride.next_deadline()
        self.now = mono
        return [] if event is None else self.do(event)

    def do(self, event: RideEvent) -> list[RideAction]:
        actions = self.ride.handle(event, self.now)
        self.log += [(self.now, a) for a in actions]
        return actions

    def commands(self, since: float = -1.0) -> list[tuple[float, Any]]:
        return [(round(t, 3), a.command) for t, a in self.log
                if isinstance(a, SetTrainer) and t > since]

    def journal(self, event: str) -> list[tuple[float, Journal]]:
        return [(t, a) for t, a in self.log
                if isinstance(a, Journal) and a.event == event]

    def last(self) -> Any:
        return self.commands()[-1][1]


def sent(actions: list[RideAction]) -> list[Any]:
    return [a.command for a in actions if isinstance(a, SetTrainer)]


@pytest.mark.case("T-TGT-04")
@pytest.mark.req("APP-308")
@pytest.mark.parametrize("levels", [Range(0, 100, 1), Range(10, 200, 10)])
def test_five_percent_of_the_range_per_press_inside_the_range(
        levels: Range) -> None:
    caps = TrainerCapabilities(Range(50, 600, 1), levels, True, False)
    rider = Rider(free_ride_workout(), caps=caps)
    ups = [sent(rider.do(ResistanceStep(1)))[0] for _ in range(22)]
    raws = [c.level_raw for c in ups]
    assert raws[0] > levels.minimum and raws[-1] == levels.maximum
    assert raws == sorted(raws) and raws[-2] == levels.maximum
    span = levels.maximum - levels.minimum
    assert all((r - levels.minimum) % levels.step == 0 for r in raws)
    assert all(abs(r - levels.minimum - span * min(100, 5 * (i + 1)) / 100)
               <= levels.step / 2 for i, r in enumerate(raws))
    downs = [sent(rider.do(ResistanceStep(-1)))[0] for _ in range(22)]
    assert downs[-1] == Resistance(levels.minimum)


@pytest.mark.case("T-TGT-05")
@pytest.mark.req("APP-309")
def test_each_target_starts_at_the_level_last_chosen_for_it() -> None:
    rider = Rider(workout(thirty_thirty()), block_modes=(Mode.RESISTANCE,))
    assert rider.last() == Resistance(0)
    rider.at(STARTED + 5)
    for _ in range(12):
        rider.do(ResistanceStep(1))
    rider.at(STARTED + 35)
    assert rider.last() == Resistance(60)
    for _ in range(8):
        rider.do(ResistanceStep(-1))
    rider.at(STARTED + 185)
    starts = {round(t - STARTED): command for t, command in rider.commands()
              if t - STARTED in (58.5, 88.5, 118.5, 148.5)}
    assert starts == {58: Resistance(60), 88: Resistance(20),
                      118: Resistance(60), 148: Resistance(20)}


@pytest.mark.case("T-TGT-06")
@pytest.mark.req("APP-705")
def test_the_free_ride_level_is_kept_for_later() -> None:
    cooldown = Block(None, 1, (
        Step(60.0, None, None, kind=StepKind.FREE_RIDE),))
    plan = workout(Block(None, 1, (erg(60, 200),)), cooldown,
                   Block(None, 1, (erg(60, 150),)), cooldown)
    rider = Rider(plan)
    rider.at(STARTED + 70)
    assert rider.last() == Resistance(0)
    kept = [a for _ in range(7) for a in rider.do(ResistanceStep(1))
            if isinstance(a, FreeRideLevel)]
    assert kept[-1] == FreeRideLevel(35)
    rider.at(STARTED + 190)
    assert rider.last() == Resistance(35)
    later = Rider(plan, free_ride_level_pct=35)
    later.at(STARTED + 70)
    assert later.last() == Resistance(35)


@pytest.mark.case("T-RID-08")
@pytest.mark.req("APP-307", "APP-415")
def test_a_switch_holds_for_the_rest_of_the_block_only() -> None:
    rider = Rider(workout(thirty_thirty(6), Block(None, 1, (erg(60, 200),))))
    rider.at(STARTED + 40, SwitchMode(Mode.RESISTANCE))
    assert rider.last() == Resistance(0)
    rider.at(STARTED + 359)
    block_one = [c for t, c in rider.commands(STARTED + 40)
                 if t < STARTED + 358]
    assert all(isinstance(c, Resistance) for c in block_one)
    assert rider.last() == Erg(200)
    assert [d.data["mode"] for _, d in rider.journal("step_started")][
        1:12] == ["erg"] + ["resistance"] * 10
    again = Rider(workout(thirty_thirty(6)))
    again.at(STARTED + 40, SwitchMode(Mode.RESISTANCE))
    back = again.at(STARTED + 50, SwitchMode(Mode.ERG))
    assert sent(back) == [Erg(140)]


@pytest.mark.case("T-RID-09")
@pytest.mark.req("APP-311", "APP-604")
def test_pause_stops_the_clock_at_the_lowest_level() -> None:
    plan = workout(Block(None, 1, (erg(120, 200), erg(120, 250))))
    rider = Rider(plan)
    paused = rider.at(STARTED + 100, Pause())
    assert sent(paused) == [Resistance(0)]
    assert rider.ride.ride_time(STARTED + 150) == 100.0
    assert rider.ride.next_deadline() == STARTED + ABANDON_AFTER
    resumed = rider.at(STARTED + 160, Resume())
    assert sent(resumed) == [Erg(200)]
    assert rider.ride.next_deadline() == pytest.approx(STARTED + 60 + 118.5)
    rider.at(STARTED + 300)
    assert [round(t - STARTED, 3) for t, _ in rider.journal(
        "step_started")] == [0.0, 180.0]
    assert [d.t_ride for _, d in rider.journal("paused")] == [100.0]
    assert [d.t_ride for _, d in rider.journal("resumed")] == [100.0]
    window = Rider(plan)
    window.at(STARTED + 119, Pause())
    assert sent(window.at(STARTED + 130, Resume())) == [Erg(250)]


@pytest.mark.case("T-RID-10")
@pytest.mark.req("APP-312", "APP-605")
def test_skip_starts_the_next_step_at_once() -> None:
    plan = workout(Block(None, 1, (erg(120, 120, end=200), erg(120, 250),
                                   erg(60, 180))))
    rider = Rider(plan)
    skipped = rider.at(STARTED + 60.5, Skip())
    assert sent(skipped) == [Erg(250)]
    (_, started), = [s for s in rider.journal("step_started")
                     if s[1].data["cause"] == "skip"]
    assert started.t_ride == 60.5 and started.data["scheduled"] == 60.5
    rider.at(STARTED + 170)
    assert not any(isinstance(c, Erg) and 200 < c.power < 250
                   for _, c in rider.commands(STARTED + 60.5))
    assert rider.ride.step == 1
    rider.at(STARTED + 179.5)
    assert rider.last() == Erg(180)
    rider.at(STARTED + 181)
    assert rider.ride.step == 2
    done = rider.at(STARTED + 190, Skip())
    assert rider.ride.phase == RidePhase.WORKOUT_DONE
    assert any(isinstance(a, Journal) and a.event == "workout_done"
               for a in done)


@pytest.mark.case("T-RID-11")
@pytest.mark.req("APP-313")
def test_intensity_moves_in_five_point_steps_between_50_and_150() -> None:
    rider = Rider(workout(Block(None, 1, (erg(600, 200),))))
    assert sent(rider.at(STARTED + 10, IntensityStep(1))) == [Erg(210)]
    assert sent(rider.do(IntensityStep(-1))) == [Erg(200)]
    for _ in range(11):
        rider.do(IntensityStep(-1))
    assert rider.ride.intensity_pct == 50 and rider.last() == Erg(100)
    for _ in range(22):
        rider.do(IntensityStep(1))
    assert rider.ride.intensity_pct == 150 and rider.last() == Erg(300)
    levels = Rider(workout(thirty_thirty()), block_modes=(Mode.RESISTANCE,))
    assert sent(levels.at(STARTED + 5, IntensityStep(1))) == []
    assert Rider(workout(thirty_thirty())).ride.intensity_pct == 100


@pytest.mark.case("T-RID-12")
@pytest.mark.req("APP-314")
def test_after_the_last_step_the_trainer_goes_to_the_free_ride_level(
) -> None:
    rider = Rider(workout(Block(None, 1, (erg(60, 200),))),
                  free_ride_level_pct=30)
    rider.at(STARTED + 61)
    assert rider.ride.phase == RidePhase.WORKOUT_DONE
    assert rider.last() == Resistance(30)
    assert rider.journal("workout_done")[0][1].t_ride == 60.0
    assert rider.ride.ride_time(STARTED + 300) == 300.0


@pytest.mark.case("T-RID-13")
@pytest.mark.req("APP-315", "APP-320")
@pytest.mark.parametrize("before", ["running", "paused", "workout_done"])
def test_finish_from_every_riding_phase(before: str) -> None:
    rider = Rider(workout(Block(None, 1, (erg(60, 200),))))
    if before == "paused":
        rider.at(STARTED + 10, Pause())
    rider.at(STARTED + (100 if before == "workout_done" else 20))
    actions = rider.do(Finish())
    assert sent(actions) == [Resistance(0)]
    assert actions[-1] == Ended(RidePhase.FINISHED)


@pytest.mark.case("T-RID-14")
@pytest.mark.req("APP-316")
@pytest.mark.parametrize("before", ["running", "paused", "workout_done"])
def test_discard_from_every_riding_phase(before: str) -> None:
    rider = Rider(workout(Block(None, 1, (erg(60, 200),))))
    if before == "paused":
        rider.at(STARTED + 10, Pause())
    rider.at(STARTED + (100 if before == "workout_done" else 20))
    actions = rider.do(Discard())
    assert actions[-1] == Ended(RidePhase.DISCARDED)
    assert rider.journal("discarded")[0][1].data == {"cause": "rider"}
    armed = Ride()
    armed.handle(TrainerLink(True), 0.0)
    armed.handle(Start(workout(Block(None, 1, (erg(60, 200),))), 250, D100,
                       1.5), 0.0)
    assert armed.handle(Pause(), 0.5) == [Refused(Problem.NOT_RIDING)]
    assert armed.handle(Discard(), 0.5) == [Refused(Problem.NOT_RIDING)]


@pytest.mark.case("T-RID-15")
@pytest.mark.req("APP-317")
def test_free_ride_by_level_and_by_power() -> None:
    rider = Rider(free_ride_workout())
    assert rider.commands()[0][1] == Resistance(0)
    assert sent(rider.at(STARTED + 10, ResistanceStep(1))) == [
        Resistance(5)]
    assert sent(rider.do(SwitchMode(Mode.ERG, 183))) == [Erg(185)]
    for _ in range(3):
        rider.do(FreeRidePowerStep(1))
    assert rider.last() == Erg(200)
    assert sent(rider.do(SwitchMode(Mode.RESISTANCE))) == [Resistance(5)]
    unknown = Rider(free_ride_workout())
    assert sent(unknown.do(SwitchMode(Mode.ERG))) == [Erg(50)]
    assert rider.journal("ride_started") and rider.ride.free


@pytest.mark.case("T-VIEW-04")
@pytest.mark.req("APP-415")
def test_the_view_mode_follows_the_trainer() -> None:
    cooldown = Block(None, 1, (
        Step(60.0, None, None, kind=StepKind.FREE_RIDE),))
    rider = Rider(workout(thirty_thirty(), cooldown))
    modes = []
    for at, event in ((STARTED + 10, None), (STARTED + 20,
                      SwitchMode(Mode.RESISTANCE)),
                      (STARTED + 30, SwitchMode(Mode.ERG)),
                      (STARTED + 200, None), (STARTED + 300, None)):
        rider.at(at, event)
        last = rider.last()
        expected = Mode.ERG if isinstance(last, Erg) else Mode.RESISTANCE
        modes.append(ride_screen(rider.ride, rider.now, 150, 130)["mode"]
                     == expected)
    assert all(modes)
    switched = Rider(workout(thirty_thirty()))
    switched.at(STARTED + 10, SwitchMode(Mode.RESISTANCE))
    switched.do(ResistanceStep(1))
    switched.do(Pause())
    paused = ride_screen(switched.ride, switched.now, 150, 130)
    assert (paused["mode"], paused["resistance_pct"]) == (
        Mode.RESISTANCE, 5)
    free = Rider(free_ride_workout())
    free.at(STARTED + 10, SwitchMode(Mode.ERG, 183))
    free.do(Pause())
    paused = ride_screen(free.ride, free.now, 150, 130)
    assert (paused["mode"], paused["target"]) == (Mode.ERG, 185)


@pytest.mark.case("T-RID-16")
@pytest.mark.req("APP-318", "APP-319")
def test_a_dropout_changes_nothing_but_the_journal() -> None:
    rider = Rider(workout(Block(None, 1, (erg(60, 200), erg(60, 250)))))
    rider.at(STARTED + 50, TrainerLink(False))
    rider.do(HrmLink(False))
    rider.at(STARTED + 70)
    assert rider.ride.step == 1 and rider.ride.phase == RidePhase.RUNNING
    back = rider.do(TrainerLink(True))
    assert sent(back) == [Erg(250)]
    rider.do(HrmLink(True))
    assert [(round(t - STARTED), j.data["device"]) for name in
            ("dropout_start", "dropout_end") for t, j in
            rider.journal(name)] == [(50, "trainer"), (50, "hrm"),
                                     (70, "trainer"), (70, "hrm")]
    assert [round(t - STARTED, 3) for t, _ in rider.journal(
        "step_started")] == [0.0, 60.0]


ERG_ONLY = TrainerCapabilities(Range(50, 600, 1), None, True, False)


def refusal(rider: Rider, event: RideEvent) -> Problem | None:
    actions = rider.do(event)
    refused = [a for a in actions if isinstance(a, Refused)]
    return refused[0].reason if refused else None


@pytest.mark.case("T-RID-08")
@pytest.mark.req("APP-307")
def test_controls_are_refused_where_they_do_not_apply() -> None:
    cooldown = Block(None, 1, (
        Step(60.0, None, None, kind=StepKind.FREE_RIDE),))
    rider = Rider(workout(thirty_thirty(), cooldown))
    assert refusal(rider, Resume()) == Problem.NOT_RIDING
    assert refusal(rider, ResistanceStep(1)) == Problem.INVALID_STATE
    assert refusal(rider, FreeRidePowerStep(1)) == Problem.INVALID_STATE
    rider.do(Pause())
    assert refusal(rider, Skip()) == Problem.NOT_RIDING
    assert refusal(rider, SwitchMode(Mode.RESISTANCE)) == Problem.NOT_RIDING
    rider.at(rider.now + 1.0, Resume())
    rider.at(STARTED + 200)
    assert refusal(rider, SwitchMode(Mode.ERG)) == Problem.INVALID_STATE
    free = Rider(free_ride_workout())
    assert refusal(free, IntensityStep(1)) == Problem.NOT_RIDING
    assert refusal(free, Skip()) == Problem.NOT_RIDING
    erg_only = Rider(workout(thirty_thirty()), caps=ERG_ONLY)
    assert refusal(erg_only, SwitchMode(Mode.RESISTANCE)) == (
        Problem.INVALID_STATE)


@pytest.mark.case("T-RID-09")
@pytest.mark.req("APP-311")
def test_a_trainer_without_levels_pauses_at_its_lowest_power() -> None:
    rider = Rider(workout(Block(None, 1, (erg(60, 200),))), caps=ERG_ONLY)
    assert sent(rider.at(STARTED + 10, Pause())) == [Erg(50)]
    rider.at(STARTED + 20, Resume())
    rider.at(STARTED + 80)
    assert rider.last() == Erg(200)
    assert rider.ride.resistance_pct is None


@pytest.mark.case("T-RID-16")
@pytest.mark.req("APP-318")
def test_link_up_resends_the_level_while_paused_or_done() -> None:
    rider = Rider(workout(Block(None, 1, (erg(60, 200),))))
    rider.at(STARTED + 10, Pause())
    rider.do(TrainerLink(False))
    assert sent(rider.do(TrainerLink(True))) == [Resistance(0)]
    rider.at(STARTED + 20, Resume())
    rider.at(STARTED + 80)
    rider.do(TrainerLink(False))
    assert sent(rider.do(TrainerLink(True))) == [Resistance(0)]
    single = TrainerCapabilities(Range(50, 600, 1), Range(10, 10, 1), True,
                                 False)
    one_level = Rider(free_ride_workout(), caps=single)
    assert one_level.ride.resistance_pct == 0
