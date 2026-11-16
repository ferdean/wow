"""Reconnect for the whole ride, on the simulated devices (L3)."""

import pytest

from tests.support.rig import Rig, make_rig
from wow.adapters.ble_sim import Fault, FaultKind
from wow.adapters.clock_stepped import DEFAULT_START
from wow.core import uuids
from wow.core.devices import Erg, LinkState

CONTROL = uuids.FITNESS_MACHINE_CONTROL_POINT


def fault(kind: FaultKind, start: float, end: float) -> Fault:
    return Fault(kind, DEFAULT_START + start, DEFAULT_START + end)


def writes(rig: Rig, generation: int) -> list[tuple[float, str | None]]:
    return [(r.mono_ms / 1000, r.hex) for r in rig.log
            if r.op == "write" and r.uuid == CONTROL and r.gen == generation]


async def connected(rig: Rig, at: float) -> float:
    start = rig.clock.monotonic()
    rig.manager.open_pre_ride()
    await rig.clock.run_until(start + at)
    rig.trainer.set_command(Erg(200))
    await rig.clock.advance(1.0)
    assert rig.trainer.link() == LinkState.CONNECTED
    return start


@pytest.mark.case("T-DEV-06")
@pytest.mark.req("APP-318", "APP-805")
@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [0.0, 0.6, 1.2, 1.9, 2.4])
async def test_the_trainer_comes_back_within_ten_seconds(
        offset: float) -> None:
    rig = make_rig(trainer_faults=[fault(FaultKind.LINK_LOSS, 100.0,
                                         120.0 + offset)])
    start = await connected(rig, 20.0)
    await rig.clock.run_until(start + 100.5)
    assert rig.trainer.link() == LinkState.DROPOUT
    await rig.clock.run_until(start + 135.0 + offset)
    back = [(t - start, h) for t, h in writes(rig, 2)]
    assert [h for _, h in back[:3]] == ["00", "07", "05c800"]
    assert back[2][0] <= 120.0 + offset + 10.0
    assert rig.trainer.link() == LinkState.CONNECTED
    rig.manager._lost(rig.manager._trainer, 1)
    assert rig.trainer.link() == LinkState.CONNECTED
    await rig.close()


@pytest.mark.case("T-DEV-07")
@pytest.mark.req("APP-319", "APP-806")
@pytest.mark.asyncio
async def test_the_strap_comes_back_without_control_steps() -> None:
    rig = make_rig(strap_faults=[fault(FaultKind.LINK_LOSS, 100.0, 120.0)])
    start = await connected(rig, 20.0)
    await rig.clock.run_until(start + 101.0)
    assert rig.strap.link() == LinkState.DROPOUT
    await rig.clock.run_until(start + 130.0)
    assert rig.strap.link() == LinkState.CONNECTED
    links = [r.mono_ms / 1000 - start for r in rig.log
             if r.dev == "hrm" and r.op == "connected"]
    assert links[-1] <= 130.0 and links[-1] > 120.0
    assert not [r for r in rig.log if r.dev == "hrm" and r.op == "write"]
    await rig.close()


@pytest.mark.case("T-DEV-08")
@pytest.mark.req("APP-318")
@pytest.mark.asyncio
async def test_a_silent_trainer_is_dropped_and_reconnected() -> None:
    rig = make_rig(trainer_faults=[fault(FaultKind.SILENCE, 100.0, 109.0)])
    start = await connected(rig, 20.0)
    await rig.clock.run_until(start + 103.5)
    assert rig.trainer.link() == LinkState.DROPOUT
    await rig.clock.run_until(start + 109.5)
    assert rig.trainer.link() == LinkState.CONNECTED
    assert writes(rig, 2) == []
    long = make_rig(trainer_faults=[fault(FaultKind.SILENCE, 100.0, 111.0)])
    start = await connected(long, 20.0)
    await long.clock.run_until(start + 125.0)
    assert [h for _, h in writes(long, 2)][:3] == ["00", "07", "05c800"]
    assert long.trainer.link() == LinkState.CONNECTED
    await rig.close()
    await long.close()


@pytest.mark.case("T-DEV-09")
@pytest.mark.req("APP-318")
@pytest.mark.asyncio
async def test_attempts_go_on_while_the_trainer_is_gone() -> None:
    rig = make_rig(trainer_faults=[fault(FaultKind.LINK_LOSS, 100.0,
                                         3700.0)])
    start = await connected(rig, 20.0)
    await rig.clock.run_until(start + 3715.0)
    attempts = [r.mono_ms / 1000 - start for r in rig.log
                if r.dev == "trainer" and r.op == "connect_start"]
    during = [t for t in attempts if 100.0 < t < 3700.0]
    assert len(during) > 200
    assert max(b - a for a, b in zip(during, during[1:])) <= 12.5
    assert rig.trainer.link() == LinkState.CONNECTED
    await rig.close()


@pytest.mark.case("T-DEV-10")
@pytest.mark.req("APP-318", "APP-319")
@pytest.mark.asyncio
async def test_both_devices_return_after_the_adapter_fails() -> None:
    rig = make_rig(adapter_faults=[fault(FaultKind.ADAPTER_DOWN, 100.0,
                                         120.0)])
    start = await connected(rig, 20.0)
    await rig.clock.run_until(start + 110.0)
    assert rig.trainer.link() == LinkState.DROPOUT
    assert rig.strap.link() == LinkState.DROPOUT
    await rig.clock.run_until(start + 135.0)
    assert rig.trainer.link() == LinkState.CONNECTED
    assert rig.strap.link() == LinkState.CONNECTED
    failed = [r for r in rig.log if r.op == "connect_failed"
              and 100.0 < r.mono_ms / 1000 - start < 120.0]
    assert failed
    await rig.close()
