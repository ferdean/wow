"""Scripted faults of the simulated devices (L3)."""

from collections.abc import Callable
from typing import Any

import pytest

from wow.adapters.ble_sim import (
    D100_ADDRESS, HRM_ADDRESS, Fault, FaultKind, Faults, SimConnector,
    SimD100Server, SimHrm200Server, SimScheduler,
)
from wow.adapters.clock_stepped import SteppedClock
from wow.core import uuids
from wow.ports.gatt import GattClient, GattError

START, END = 20.0, 40.0


class Bench:
    """A raw client on one simulated device, with what it received."""

    def __init__(self, kind: FaultKind) -> None:
        self.clock = SteppedClock()
        start = self.clock.monotonic()
        fault = Fault(kind, start + START, start + END)
        self.t0 = start
        self.scheduler = SimScheduler(self.clock)
        self.d100 = SimD100Server(self.scheduler)
        self.hrm = SimHrm200Server(self.scheduler)
        strap = kind in (FaultKind.BATTERY_OUT_OF_RANGE,
                         FaultKind.ABSENT_STRAP)
        adapter = kind == FaultKind.ADAPTER_DOWN
        target = self.hrm if strap else self.d100
        if not adapter:
            target.faults = Faults([fault])
        self.sim = SimConnector(self.clock, [self.d100, self.hrm],
                                Faults([fault] if adapter else []))
        self.address = HRM_ADDRESS if strap else D100_ADDRESS
        self.lost: list[float] = []
        self.got: list[tuple[float, str, bytes]] = []

    def t(self) -> float:
        return self.clock.monotonic() - self.t0

    async def open(self) -> GattClient:
        client = await self.clock.drive(self.sim.connect(
            self.address, 10.0, lambda _g: self.lost.append(self.t())))
        chars = ([uuids.HEART_RATE_MEASUREMENT, uuids.BATTERY_LEVEL]
                 if self.address == HRM_ADDRESS else
                 [uuids.INDOOR_BIKE_DATA, uuids.FITNESS_MACHINE_STATUS,
                  uuids.FITNESS_MACHINE_CONTROL_POINT])
        for char in chars:
            await client.subscribe(char, self._keep(char))
        return client

    def _keep(self, char: str) -> Callable[[bytes], None]:
        return lambda data: self.got.append((self.t(), char, data))

    async def until(self, t: float) -> None:
        await self.clock.run_until(self.t0 + t)

    def times(self, char: str, low: float, high: float) -> list[bytes]:
        return [d for t, c, d in self.got if c == char and low <= t < high]


async def write_at(bench: Bench, client: GattClient, t: float,
                   data: bytes) -> list[bytes]:
    await bench.until(t)
    await bench.clock.drive(client.write(
        uuids.FITNESS_MACHINE_CONTROL_POINT, data))
    await bench.until(t + 1.0)
    return bench.times(uuids.FITNESS_MACHINE_CONTROL_POINT, t, t + 1.0)


async def check(kind: FaultKind, bench: Bench, client: GattClient) -> None:
    status = uuids.FITNESS_MACHINE_STATUS
    if kind in (FaultKind.LINK_LOSS, FaultKind.ABSENT_STRAP):
        await bench.until(30.0)
        server: Any = bench.hrm if bench.address == HRM_ADDRESS else (
            bench.d100)
        assert bench.lost == [pytest.approx(START)]
        assert not server.advertising()
        await bench.until(END + 0.1)
        assert server.advertising()
    elif kind == FaultKind.ADAPTER_DOWN:
        await bench.until(30.0)
        assert bench.lost == [pytest.approx(START)]
        with pytest.raises(GattError):
            await bench.sim.scan([], 1.0)
        await bench.until(END + 0.1)
        assert await bench.clock.drive(bench.sim.scan([], 1.0))
    elif kind == FaultKind.SILENCE:
        await bench.until(45.0)
        data = uuids.INDOOR_BIKE_DATA
        assert bench.times(data, 19.0, START) and bench.times(data, END, 41)
        assert bench.times(data, START + 0.01, END - 0.01) == []
    elif kind == FaultKind.POWER_ZERO:
        await bench.until(45.0)
        data = uuids.INDOOR_BIKE_DATA
        powers = [(t, int.from_bytes(d[4:6], "little")) for t, c, d in
                  bench.got if c == data]
        assert all(p == 0 for t, p in powers if START <= t < END)
        assert all(p > 0 for t, p in powers if t < START or t >= END)
    elif kind == FaultKind.BATTERY_OUT_OF_RANGE:
        await bench.until(45.0)
        battery = [(t, d[0]) for t, c, d in bench.got
                   if c == uuids.BATTERY_LEVEL]
        assert {b for t, b in battery if START <= t < END} == {255}
        assert {b for t, b in battery if t < START or t >= END} == {80}
    elif kind in (FaultKind.PERMISSION_LOST, FaultKind.RESET):
        await bench.until(START + 0.5)
        code = 0xFF if kind == FaultKind.PERMISSION_LOST else 0x01
        assert bench.times(status, START, START + 0.5) == [bytes([code])]
        assert bench.times(status, 5.0, START) == []
    elif kind == FaultKind.REFUSE_CONTROL:
        assert await write_at(bench, client, 25.0, b"\x00") == [
            bytes.fromhex("800005")]
        assert await write_at(bench, client, 41.0, b"\x00") == [
            bytes.fromhex("800001")]
    elif kind == FaultKind.NO_ANSWER:
        assert await write_at(bench, client, 25.0, b"\x00") == []
        assert await write_at(bench, client, 41.0, b"\x00") == [
            bytes.fromhex("800001")]


@pytest.mark.case("T-SIM-03")
@pytest.mark.req("APP-819")
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", list(FaultKind))
async def test_each_fault_starts_and_ends_at_its_time(
        kind: FaultKind) -> None:
    bench = Bench(kind)
    client = await bench.open()
    if bench.address == D100_ADDRESS:
        await bench.clock.drive(client.write(
            uuids.FITNESS_MACHINE_CONTROL_POINT, b"\x00"))
    try:
        await check(kind, bench, client)
    finally:
        await bench.scheduler.close()
