import asyncio

import pytest

from tests.support.rig import make_rig
from wow.adapters.ble_sim import D100_ADDRESS, HRM_ADDRESS, SimD100Server
from wow.app.device_manager import CONNECT_TIMEOUT, DeviceChoice
from wow.core import uuids
from wow.core.devices import Range


@pytest.mark.case("T-DEV-01")
@pytest.mark.req("APP-102")
@pytest.mark.asyncio
async def test_pre_ride_connects_and_reports_an_absent_strap() -> None:
    rig = make_rig(with_hrm=False)
    assert (rig.trainer.link(), rig.strap.link()) == ("not_found",
                                                      "not_found")
    opened = rig.clock.monotonic()
    rig.manager.open_pre_ride()
    await rig.clock.settle()
    assert (rig.trainer.link(), rig.strap.link()) == ("searching",
                                                      "searching")
    await rig.clock.run_until(opened + 3.0)
    assert rig.trainer.link() == "connected"
    assert rig.trainer.in_control()
    await rig.clock.run_until(opened + CONNECT_TIMEOUT - 0.01)
    assert rig.strap.link() == "searching"
    await rig.clock.run_until(opened + CONNECT_TIMEOUT)
    assert rig.strap.link() == "not_found"
    await rig.clock.run_until(opened + 30.0)
    assert rig.strap.link() == "not_found"
    assert rig.trainer.link() == "connected"
    await rig.close()


@pytest.mark.case("T-DEV-01")
@pytest.mark.req("APP-102")
@pytest.mark.asyncio
async def test_unconfigured_devices_stay_unconfigured() -> None:
    rig = make_rig(choice=DeviceChoice(None, None))
    rig.manager.open_pre_ride()
    await rig.clock.advance(15.0)
    assert (rig.trainer.link(), rig.strap.link()) == ("not_configured",
                                                      "not_configured")
    assert rig.trainer.capabilities() is None
    assert rig.log == []
    await rig.close()


@pytest.mark.case("T-DEV-02")
@pytest.mark.req("APP-103")
@pytest.mark.asyncio
@pytest.mark.parametrize("features, power, resistance, spin_down", [
    ("014000000ca00000", True, True, True),
    ("0140000004a00000", False, True, True),
    ("0140000008a00000", True, False, True),
    ("014000000c200000", True, True, False),
], ids=["d100", "no-power-target", "no-resistance-target", "no-spin-down"])
async def test_undeclared_modes_are_not_offered(
    features: str, power: bool, resistance: bool, spin_down: bool,
) -> None:
    rig = make_rig(with_hrm=False, features=bytes.fromhex(features))
    rig.manager.open_pre_ride()
    await rig.clock.advance(5.0)
    capabilities = rig.trainer.capabilities()
    assert capabilities is not None
    assert (capabilities.power == Range(50, 600, 1)) is power
    assert (capabilities.resistance == Range(0, 100, 1)) is resistance
    assert capabilities.spin_down is spin_down
    assert capabilities.cadence is False
    await rig.close()


@pytest.mark.case("T-DEV-03")
@pytest.mark.req("APP-111")
@pytest.mark.asyncio
async def test_strap_battery_read_once_and_both_subscribed() -> None:
    rig = make_rig(with_d100=False)
    rig.manager.open_pre_ride()
    await rig.clock.advance(20.0)
    assert rig.hrm is not None
    traffic = rig.hrm.traffic
    assert traffic.reads == [(uuids.BATTERY_LEVEL, bytes([80]))]
    assert sorted(traffic.subscribed) == sorted(
        [uuids.HEART_RATE_MEASUREMENT, uuids.BATTERY_LEVEL])
    assert rig.strap.link() == "connected"
    assert rig.strap.battery_pct() == 80
    assert len(rig.hr_samples) >= 30
    assert {s.heart_rate_bpm for s in rig.hr_samples} == {130}
    await rig.close()


@pytest.mark.case("T-DEV-02")
@pytest.mark.req("APP-103")
@pytest.mark.asyncio
async def test_missing_power_range_hides_erg() -> None:
    rig = make_rig(with_hrm=False, power_range=None)
    rig.manager.open_pre_ride()
    await rig.clock.advance(5.0)
    capabilities = rig.trainer.capabilities()
    assert capabilities is not None and capabilities.power is None
    assert capabilities.resistance == Range(0, 100, 1)
    await rig.close()


@pytest.mark.case("T-DEV-02")
@pytest.mark.req("APP-103")
@pytest.mark.asyncio
async def test_unreadable_features_offer_nothing_and_retry() -> None:
    rig = make_rig(with_hrm=False, features=b"\x01")
    rig.manager.open_pre_ride()
    await rig.clock.advance(20.0)
    assert rig.trainer.capabilities() is None
    assert rig.trainer.link() == "not_found"
    assert rig.d100 is not None and not rig.d100.linked()
    attempts = [r for r in rig.log if r.op == "connected"]
    assert len(attempts) >= 3
    assert {r.op for r in rig.log if r.gen == 1} >= {"read", "disconnected"}
    await rig.close()


@pytest.mark.case("T-COD-06")
@pytest.mark.req("APP-103")
@pytest.mark.asyncio
async def test_odd_resistance_range_disables_resistance_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = make_rig(with_hrm=False,
                   resistance_range=bytes.fromhex("00640100"))
    rig.manager.open_pre_ride()
    await rig.clock.advance(5.0)
    capabilities = rig.trainer.capabilities()
    assert capabilities is not None and capabilities.resistance is None
    assert capabilities.power == Range(50, 600, 1)
    assert "00640100" in caplog.text
    await rig.close()


class ShortRecordD100(SimD100Server):
    def indoor_bike_record(self) -> bytes:
        return bytes.fromhex("40002c0b")


@pytest.mark.case("T-COD-03")
@pytest.mark.req("APP-108")
@pytest.mark.asyncio
async def test_short_records_from_the_trainer_are_dropped_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = make_rig(with_hrm=False, d100_type=ShortRecordD100)
    rig.manager.open_pre_ride()
    await rig.clock.advance(10.0)
    assert rig.trainer.in_control()
    assert rig.trainer_samples == []
    assert "indoor bike data dropped" in caplog.text
    assert "40002c0b" in caplog.text
    await rig.close()


@pytest.mark.case("T-COD-11")
@pytest.mark.req("APP-113")
@pytest.mark.asyncio
async def test_strap_battery_out_of_range_is_unknown_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = make_rig(with_d100=False, battery_pct=101)
    rig.manager.open_pre_ride()
    await rig.clock.advance(15.0)
    assert rig.strap.link() == "connected"
    assert rig.strap.battery_pct() is None
    assert "raw 101" in caplog.text
    await rig.close()


@pytest.mark.case("S-INF-06")
@pytest.mark.asyncio
async def test_loss_reports_of_the_current_link_only() -> None:
    rig = make_rig()
    rig.manager.open_pre_ride()
    await rig.clock.advance(5.0)
    rig.sim.lose_link(D100_ADDRESS)
    assert rig.trainer.link() == "dropout"
    assert rig.trainer.capabilities() is None
    assert rig.strap.link() == "connected"
    rig.sim.lose_link(HRM_ADDRESS)
    rig.sim.lose_link(HRM_ADDRESS)
    assert rig.strap.link() == "dropout"
    await rig.close()
    assert [r.op for r in rig.log if r.op == "disconnected"] == [
        "disconnected", "disconnected"]


@pytest.mark.case("S-INF-06")
@pytest.mark.asyncio
async def test_link_lost_during_release_ends_the_release() -> None:
    rig = make_rig(with_hrm=False)
    rig.manager.open_pre_ride()
    await rig.clock.advance(5.0)
    release = asyncio.ensure_future(rig.trainer.release())
    await rig.clock.settle()
    rig.sim.lose_link(D100_ADDRESS)
    await rig.clock.drive(release, limit=1.0)
    await rig.close()


@pytest.mark.case("S-INF-06")
@pytest.mark.asyncio
async def test_shutdown_during_set_up_closes_the_link() -> None:
    rig = make_rig(with_hrm=False)
    rig.manager.open_pre_ride()
    await rig.clock.run_until(rig.clock.monotonic() + 2.31)
    assert rig.d100 is not None and rig.d100.linked()
    await rig.close()
    assert not rig.d100.linked()
    assert rig.trainer.link() == "searching"
