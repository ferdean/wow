import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wow.adapters.clock_stepped import SteppedClock
from wow.adapters.clock_system import (
    TIMESYNC_MARKER, SystemClock, default_sync_marker,
)


@pytest.mark.case("S-INF-02")
@pytest.mark.asyncio
async def test_stepped_clock_wakes_sleepers_in_deadline_order() -> None:
    clock = SteppedClock(start=100.0)
    woke: list[tuple[str, float]] = []

    async def sleeper(name: str, until: float) -> None:
        await clock.sleep_until(until)
        woke.append((name, clock.monotonic()))

    tasks = [asyncio.create_task(sleeper(n, t)) for n, t in
             [("c", 103.0), ("a", 101.0), ("b", 102.0), ("b2", 102.0),
              ("late", 500.0), ("past", 50.0)]]
    await clock.settle()
    assert woke == [("past", 100.0)]
    tasks[4].cancel()
    await clock.run_until(110.0)
    assert woke == [("past", 100.0), ("a", 101.0), ("b", 102.0),
                    ("b2", 102.0), ("c", 103.0)]
    assert clock.monotonic() == 110.0 and clock.sleepers() == 0
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.case("S-INF-02")
@pytest.mark.asyncio
async def test_stepped_clock_drives_work_and_reports_a_deadlock() -> None:
    clock = SteppedClock(start=0.0)

    async def chain() -> float:
        for step in range(1, 5):
            await clock.sleep_until(step * 0.5)
        return clock.monotonic()

    assert await clock.drive(chain()) == 2.0
    with pytest.raises(TimeoutError):
        await clock.drive(asyncio.Event().wait())
    with pytest.raises(TimeoutError):
        await clock.drive(clock.sleep_until(100.0), limit=10.0)


@pytest.mark.case("S-INF-02")
def test_stepped_clock_utc_and_sync_follow_the_steps() -> None:
    start = datetime(2026, 11, 10, 17, 0, tzinfo=UTC)
    clock = SteppedClock(start=10.0, utc_start=start, synchronised=False)
    assert clock.utc() == start and not clock.synchronised()
    asyncio.run(clock.advance(90.5))
    assert clock.utc() == start + timedelta(seconds=90.5)
    clock.set_synchronised(True)
    assert clock.synchronised()


@pytest.mark.case("S-INF-05")
@pytest.mark.asyncio
async def test_system_clock(tmp_path: Path) -> None:
    marker = tmp_path / "synchronized"
    clock = SystemClock(marker)
    assert not clock.synchronised()
    marker.touch()
    assert clock.synchronised()
    assert SystemClock(None).synchronised()
    before = clock.monotonic()
    await clock.sleep_until(before + 0.01)
    assert clock.monotonic() >= before + 0.01
    await clock.sleep_until(before)
    assert abs(clock.utc() - datetime.now(UTC)) < timedelta(seconds=1)
    assert default_sync_marker() in (TIMESYNC_MARKER, None)
