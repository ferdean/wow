"""A 4-hour plan on the core with late ticks (L2, T-RID-17)."""

import pytest

from wow.core.devices import Range, TrainerCapabilities
from wow.core.ride import (
    Journal, Pause, PowerSeen, Resume, Ride, Start, Tick, TrainerLink,
)
from wow.core.workout import Block, PowerTarget, PowerUnit, Step, Workout

D100 = TrainerCapabilities(Range(50, 600, 1), Range(0, 100, 1), True, False)
STEPS = 480
LATE_MAX = 0.08
PAUSE_AT = 7200.25
PAUSE_FOR = 600.0
FIRST = 10.0
FOUR_HOURS = Workout("test:480", "480 steps of 30 s", None, (
    Block("30/30", STEPS // 2, (
        Step(30.0, PowerTarget(330, PowerUnit.WATTS), None),
        Step(30.0, PowerTarget(140, PowerUnit.WATTS), None))),))


def late(index: int) -> float:
    """Return the delay of the index-th tick: 0 to 80 ms, spread evenly."""
    return (index * 37 % 81) / 1000


def ride_with_late_ticks() -> tuple[list[tuple[float, float, float]],
                                    float]:
    ride = Ride()
    ride.handle(TrainerLink(True), 0.0)
    ride.handle(Start(FOUR_HOURS, 250, D100, 1.0), 0.0)
    ride.handle(PowerSeen(150), FIRST)
    starts: list[tuple[float, float, float]] = []
    ticks, paused = 0, False
    while True:
        deadline = ride.next_deadline()
        if deadline is None:
            break
        if not paused and deadline > FIRST + PAUSE_AT:
            ride.handle(Pause(), FIRST + PAUSE_AT)
            ride.handle(Resume(), FIRST + PAUSE_AT + PAUSE_FOR)
            paused = True
            continue
        delay = late(ticks)
        ticks += 1
        now = deadline + delay
        ride.handle(PowerSeen(150), now)
        for action in ride.handle(Tick(), now):
            if isinstance(action, Journal) and action.event == "step_started":
                scheduled = float(str(action.data["scheduled"]))
                pause = PAUSE_FOR if scheduled > PAUSE_AT else 0.0
                starts.append((now - (FIRST + scheduled + pause), delay,
                               scheduled))
        if ride.phase == "workout_done":
            break
    return starts, ride.ride_time(FIRST + 4 * 3600 + PAUSE_FOR)


@pytest.mark.case("T-RID-17")
@pytest.mark.req("APP-804")
def test_480_steps_start_on_time_without_drift() -> None:
    starts, ride_time = ride_with_late_ticks()
    assert len(starts) == STEPS - 1
    assert [s[2] for s in starts] == [30.0 * k for k in range(1, STEPS)]
    assert max(abs(lateness) for lateness, _, _ in starts) <= 0.1
    assert max(late(k) for k in range(2 * STEPS)) <= LATE_MAX
    first, last = starts[0], starts[-1]
    assert last[0] - last[1] <= first[0] - first[1] + 1e-6
    assert all(abs(lateness - delay) < 1e-6 for lateness, delay, _ in starts)
    assert ride_time == pytest.approx(4 * 3600.0, abs=1e-6)
