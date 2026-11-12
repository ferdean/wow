import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.support.timeline import TESTDATA
from wow.adapters.ble_sim import (
    D100_ADDRESS, SimConnector, SimD100Server, SimScheduler,
)
from wow.adapters.ble_sim.d100 import (
    ANSWER_DELAYS, D100_FEATURES, D100_POWER_RANGE, D100_RESISTANCE_RANGE,
)
from wow.adapters.clock_stepped import SteppedClock
from wow.core import uuids
from wow.ports.gatt import GattClient

PHASE2_LOGS = sorted((TESTDATA / "ble").glob("phase2-s[12]-*.jsonl"))
Received = list[tuple[float, str, bytes]]


async def connected_d100(
    clock: SteppedClock, received: Received
) -> tuple[SimD100Server, SimConnector, GattClient, SimScheduler]:
    scheduler = SimScheduler(clock)
    d100 = SimD100Server(scheduler)
    connector = SimConnector(clock, [d100])
    client = await clock.drive(connector.connect(D100_ADDRESS, 10.0, print))
    for char in (uuids.INDOOR_BIKE_DATA, uuids.FITNESS_MACHINE_STATUS,
                 uuids.FITNESS_MACHINE_CONTROL_POINT):
        await client.subscribe(char, collector(clock, char, received))
    return d100, connector, client, scheduler


def collector(clock: SteppedClock, char: str,
              received: Received) -> Callable[[bytes], None]:
    return lambda data: received.append((clock.monotonic(), char, data))


async def write_at(clock: SteppedClock, client: GattClient, hex_text: str,
                   wait: float) -> float:
    start = clock.monotonic()
    await clock.drive(client.write(uuids.FITNESS_MACHINE_CONTROL_POINT,
                                   bytes.fromhex(hex_text)))
    await clock.run_until(start + wait)
    return start


def answers_after(received: Received, start: float) -> float:
    return next(at for at, char, _ in received
                if char == uuids.FITNESS_MACHINE_CONTROL_POINT
                and at > start) - start


@pytest.mark.case("T-SIM-01")
@pytest.mark.req("APP-819")
@pytest.mark.asyncio
async def test_simulated_d100_matches_the_phase2_findings() -> None:
    clock = SteppedClock()
    received: Received = []
    d100, connector, client, scheduler = await connected_d100(
        clock, received)
    reads = [await clock.drive(client.read(char)) for char in (
        uuids.FITNESS_MACHINE_FEATURE, uuids.SUPPORTED_POWER_RANGE,
        uuids.SUPPORTED_RESISTANCE_LEVEL_RANGE)]
    assert reads == [D100_FEATURES, D100_POWER_RANGE, D100_RESISTANCE_RANGE]
    starts = [await write_at(clock, client, data, 2.0)
              for data in ("00", "07", "05c800", "054a01", "058c00", "0432",
                           "0400", "05c800")]
    delays = [round(answers_after(received, start), 6) for start in starts]
    assert all(0.186 <= delay <= 0.390 for delay in delays)
    assert set(delays) == set(ANSWER_DELAYS)
    resets = [at for at, char, data in received
              if char == uuids.FITNESS_MACHINE_STATUS and data == b"\x01"]
    grant = starts[0] + delays[0]
    assert [round(at - grant, 6) for at in resets] == [0.2, 0.25, 0.3]
    bike = [data for _, char, data in received
            if char == uuids.INDOOR_BIKE_DATA]
    assert len(bike) > 50
    assert {len(data) for data in bike} == {16}
    assert {data[:2] for data in bike} == {b"\x40\x00"}
    await client.close()
    assert d100.advertising()
    again = await clock.drive(connector.connect(D100_ADDRESS, 10.0, print))
    await again.subscribe(uuids.FITNESS_MACHINE_STATUS,
                          collector(clock, "second", received))
    await again.subscribe(uuids.FITNESS_MACHINE_CONTROL_POINT,
                          collector(clock, "second-cp", received))
    await write_at(clock, again, "00", 2.0)
    assert [d for _, c, d in received if c == "second"] == [b"\x01"] * 3
    await again.close()
    await scheduler.close()


def log_lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.case("T-SIM-01")
@pytest.mark.req("APP-819")
@pytest.mark.parametrize("path", PHASE2_LOGS or [None],
                         ids=[p.name for p in PHASE2_LOGS] or ["no-logs"])
def test_simulated_d100_against_the_s1_and_s2_logs(path: Path | None) -> None:
    if path is None:
        pytest.skip("Phase 2 S1 and S2 logs not imported yet: "
                    "run tools/import_spike_log.py (testdata/README.md)")
    lines = [line for line in log_lines(path) if line["dev"] == "trainer"]
    read_values = {line["uuid"]: bytes.fromhex(line["hex"])
                   for line in lines if line["op"] == "read"}
    expected = {uuids.FITNESS_MACHINE_FEATURE: D100_FEATURES,
                uuids.SUPPORTED_POWER_RANGE: D100_POWER_RANGE,
                uuids.SUPPORTED_RESISTANCE_LEVEL_RANGE: D100_RESISTANCE_RANGE}
    assert {k: read_values[k] for k in expected if k in read_values} == {
        k: v for k, v in expected.items() if k in read_values}
    bike = [bytes.fromhex(line["hex"]) for line in lines
            if line["op"] == "notify"
            and line["uuid"] == uuids.INDOOR_BIKE_DATA]
    assert bike and {len(b) for b in bike} == {16}
    assert {b[:2] for b in bike} == {b"\x40\x00"}
    for grant in [line["mono_ms"] for line in lines
                  if line["op"] == "indicate" and line["hex"] == "800001"]:
        resets = [line["mono_ms"] for line in lines
                  if line["op"] == "notify" and line["hex"] == "01"
                  and 0 < line["mono_ms"] - grant <= 1000]
        assert resets and max(resets) - min(resets) < 500


@pytest.mark.case("T-SIM-01")
@pytest.mark.req("APP-819")
def test_simulated_answer_delays_lie_within_the_logged_ones() -> None:
    if not PHASE2_LOGS:
        pytest.skip("Phase 2 S1 and S2 logs not imported yet: "
                    "run tools/import_spike_log.py (testdata/README.md)")
    delays = [delay for path in PHASE2_LOGS for delay in log_answer_delays(
        [line for line in log_lines(path) if line["dev"] == "trainer"])]
    assert min(delays) <= min(ANSWER_DELAYS)
    assert max(ANSWER_DELAYS) <= max(delays)


def log_answer_delays(lines: list[dict[str, Any]]) -> list[float]:
    delays: list[float] = []
    pending: float | None = None
    for line in lines:
        if line["uuid"] != uuids.FITNESS_MACHINE_CONTROL_POINT:
            continue
        if line["op"] == "write":
            pending = line["mono_ms"]
        elif line["op"] == "indicate" and pending is not None:
            delays.append((line["mono_ms"] - pending) / 1000)
            pending = None
    return delays


def t90(samples: list[tuple[float, int]], start: float, before: float,
        after: float) -> float:
    level = before + 0.9 * (after - before)
    rising = after > before
    previous = (start, before)
    for at, power in samples:
        if at <= start:
            continue
        crossed = power >= level if rising else power <= level
        if crossed:
            (t0, p0), (t1, p1) = previous, (at, power)
            return t0 + (level - p0) / (p1 - p0) * (t1 - t0) - start
        previous = (at, power)
    raise AssertionError("step never reached 90 %")


@pytest.mark.case("T-SIM-02")
@pytest.mark.req("APP-819")
@pytest.mark.asyncio
async def test_simulated_erg_reaches_ninety_percent_in_one_and_a_half_s(
) -> None:
    clock = SteppedClock()
    received: Received = []
    _, _, client, scheduler = await connected_d100(clock, received)
    await write_at(clock, client, "00", 1.0)
    await write_at(clock, client, "07", 1.0)
    await write_at(clock, client, "058c00", 10.0)
    steps: list[tuple[float, int, int]] = []
    power = 140
    for target in [330, 140] * 6:
        start = await write_at(
            clock, client, "05" + target.to_bytes(2, "little").hex(), 30.0)
        steps.append((start, power, target))
        power = target
    samples = [(at, int.from_bytes(data[4:6], "little", signed=True))
               for at, char, data in received
               if char == uuids.INDOOR_BIKE_DATA]
    for start, before, after in steps:
        assert abs(t90(samples, start, before, after) - 1.5) <= 0.2
    assert samples[-1][1] == 140
    await client.close()
    await scheduler.close()