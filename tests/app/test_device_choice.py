"""Device scan and choice, idle release, a trainer with cadence (L3;
T-DEV-04, T-DEV-05, T-DEV-11)."""

from pathlib import Path

import pytest
from garmin_fit_sdk import Decoder, Stream

from tests.support.app_rig import AppSession, read_jsonl
from tests.support.rig import make_rig
from wow.adapters.ble_log import BleLogRecord
from wow.adapters.ble_sim import (
    SimAdvertiser, SimD100Server, SimHrm200Server, SimScheduler,
)
from wow.adapters.ble_sim.d100 import CADENCE_FEATURES
from wow.adapters.ble_sim.others import CADENCE_ADDRESS
from wow.adapters.clock_stepped import SteppedClock
from wow.app.device_manager import IDLE_RELEASE
from wow.core import uuids
from wow.core.devices import DeviceKind, Erg, FoundDevice, LinkState
from wow.ports.gatt import Advertisement, GattError
from wow.core.uuids import sig_uuid

CONTROL = uuids.FITNESS_MACHINE_CONTROL_POINT
SPARE = "E0:E2:EF:00:00:01"


def control_writes(log: list[BleLogRecord]) -> list[tuple[float, str]]:
    return [(r.mono_ms / 1000, str(r.hex)) for r in log
            if r.op == "write" and r.uuid == CONTROL]


async def idle_after(rig_open: float, home_at: float,
                     reopen: tuple[float, float] | None = None
                     ) -> tuple[list[LinkState], list[tuple[float, str]],
                                list[BleLogRecord], float]:
    rig = make_rig()
    start = rig.clock.monotonic()
    rig.manager.open_pre_ride()
    await rig.clock.run_until(start + rig_open)
    rig.trainer.set_command(Erg(150))
    await rig.clock.run_until(start + home_at)
    rig.manager.hold(False)
    home = rig.clock.monotonic()
    if reopen is not None:
        await rig.clock.run_until(home + reopen[0])
        rig.manager.open_pre_ride()
        await rig.clock.run_until(home + reopen[1])
        rig.manager.hold(False)
        home = rig.clock.monotonic()
    states = []
    for offset in (IDLE_RELEASE - 1.0, IDLE_RELEASE + 3.0):
        await rig.clock.run_until(home + offset)
        states.append(rig.trainer.link())
    log = list(rig.log)
    await rig.close()
    return states, control_writes(log), log, home


@pytest.mark.case("T-DEV-04")
@pytest.mark.req("APP-110", "APP-320")
@pytest.mark.asyncio
async def test_the_trainer_is_released_after_ten_idle_minutes() -> None:
    states, writes, log, home = await idle_after(20.0, 60.0)
    assert states == [LinkState.CONNECTED, LinkState.NOT_FOUND]
    late = [(t, h) for t, h in writes if t > home + IDLE_RELEASE - 1.0]
    assert late and late[0][1] == "0400"
    assert late[0][0] == pytest.approx(home + IDLE_RELEASE)
    closed = [r.mono_ms / 1000 for r in log
              if r.op == "disconnected" and r.dev == "trainer"]
    assert closed and home + IDLE_RELEASE <= closed[-1] <= (
        home + IDLE_RELEASE + 2.5)
    assert not [r for r in log if r.op == "connect_start"
                and r.mono_ms / 1000 > home + IDLE_RELEASE]
    strap = [r for r in log if r.op == "disconnected" and r.dev == "hrm"]
    assert strap


@pytest.mark.case("T-DEV-04")
@pytest.mark.req("APP-110", "APP-320")
@pytest.mark.asyncio
async def test_reopening_pre_ride_starts_the_ten_minutes_again() -> None:
    states, writes, _, home = await idle_after(20.0, 60.0, (300.0, 310.0))
    assert states == [LinkState.CONNECTED, LinkState.NOT_FOUND]
    assert [h for t, h in writes if t > home - 310.0 and h == "0400"] == [
        "0400"]
    (released,) = [t for t, h in writes if h == "0400"]
    assert released == pytest.approx(home + IDLE_RELEASE)


@pytest.mark.case("T-DEV-04")
@pytest.mark.req("APP-110", "APP-320")
@pytest.mark.asyncio
async def test_pre_ride_during_the_release_connects_afterwards() -> None:
    rig = make_rig()
    start = rig.clock.monotonic()
    rig.manager.open_pre_ride()
    await rig.clock.run_until(start + 20.0)
    rig.manager.hold(False)
    await rig.clock.run_until(start + 20.0 + IDLE_RELEASE + 0.1)
    rig.manager.open_pre_ride()
    rig.manager.hold(True)
    await rig.clock.run_until(start + 20.0 + IDLE_RELEASE + 30.0)
    assert rig.trainer.link() == LinkState.CONNECTED
    assert rig.strap.link() == LinkState.CONNECTED
    await rig.close()


def spare_strap(scheduler: SimScheduler) -> list[SimHrm200Server]:
    return [SimHrm200Server(scheduler, battery_pct=60, address=SPARE,
                            name="HRM200:SPARE")]


@pytest.mark.case("T-DEV-05")
@pytest.mark.req("APP-114")
@pytest.mark.asyncio
async def test_the_scan_lists_fitness_devices_and_the_choice_stays(
        tmp_path: Path) -> None:
    first = AppSession(tmp_path, sim_devices=spare_strap)
    assert first.command("open_settings") is None
    assert first.command("device_choose", kind="hrm",
                         address=SPARE) == "invalid_state"
    assert first.command("device_scan", kind="cadence") == "bad_request"
    assert first.command("device_scan", kind="hrm") is None
    assert first.command("device_scan", kind="hrm") == "invalid_state"
    running = first.app.console.view()["screen"]["scan"]
    assert (running["kind"], running["running"]) == ("hrm", True)
    await first.clock.advance(6.0)
    scan = first.app.console.view()["screen"]["scan"]
    assert scan["running"] is False
    assert [(f["kind"], f["name"]) for f in scan["found"]] == [
        ("trainer", "VANRYSEL-HT-9d5d"), ("hrm", "HRM200:739158"),
        ("hrm", "HRM200:SPARE"), ("cadence", "CADENCE-1816")]
    assert first.command("device_choose", kind="hrm",
                         address=CADENCE_ADDRESS) == "bad_request"
    assert first.command("device_choose", kind="trainer",
                         address=SPARE) == "invalid_state"
    assert first.command("device_choose", kind="hrm", address=SPARE) is None
    await first.clock.advance(1.0)
    assert first.app.devices.address(DeviceKind.HRM) == SPARE
    assert first.app.console.view()["screen"]["hrm"] == {
        "address": SPARE, "name": "HRM200:SPARE"}
    await first.close()
    second = AppSession(tmp_path, sim_devices=spare_strap)
    assert second.app.devices.address(DeviceKind.HRM) == SPARE
    assert second.command("open_free_ride") is None
    await second.clock.advance(15.0)
    assert second.app.console.view()["hrm_battery_pct"] == 60
    await second.close()
    lines = read_jsonl(second.app.config.data / "logs" / "ble-system.jsonl")
    assert {line["dev"] for line in lines if line["addr"] == SPARE} == {
        "hrm"}


class Everything:
    """A connector whose scan returns whatever advertises."""

    def __init__(self, seen: list[Advertisement], fail: bool = False
                 ) -> None:
        self.seen, self.fail = seen, fail
        self.asked: list[tuple[str, ...]] = []

    async def scan(self, service_uuids: tuple[str, ...], duration: float
                   ) -> list[Advertisement]:
        self.asked.append(tuple(service_uuids))
        if self.fail:
            raise GattError("adapter down")
        return self.seen


@pytest.mark.case("T-DEV-05")
@pytest.mark.req("APP-114")
@pytest.mark.asyncio
async def test_other_devices_are_hidden_whatever_the_adapter_returns(
        ) -> None:
    def advert(address: str, rssi: int, *services: str) -> Advertisement:
        return Advertisement(address, None, rssi, services, {})

    rig = make_rig()
    seen = [advert("aa:00:00:00:00:01", -70, uuids.FITNESS_MACHINE_SERVICE),
            advert("AA:00:00:00:00:01", -50, uuids.FITNESS_MACHINE_SERVICE),
            advert("AA:00:00:00:00:01", -90, uuids.FITNESS_MACHINE_SERVICE),
            advert("AA:00:00:00:00:02", -40, sig_uuid(0x180F)),
            advert("AA:00:00:00:00:03", -60, sig_uuid(0x180A))]
    connector = Everything(seen)
    rig.manager._connector = connector  # type: ignore[assignment]
    found = await rig.clock.drive(rig.manager.scan(1.0))
    assert found == [FoundDevice("AA:00:00:00:00:01", None, -50,
                                 DeviceKind.TRAINER)]
    assert connector.asked == [(uuids.FITNESS_MACHINE_SERVICE,
                                uuids.HEART_RATE_SERVICE,
                                uuids.CYCLING_SPEED_AND_CADENCE_SERVICE)]
    connector.fail = True
    assert await rig.clock.drive(rig.manager.scan(1.0)) == []
    await rig.close()


def cadence_trainer(scheduler: SimScheduler) -> SimD100Server:
    return SimD100Server(scheduler, features=CADENCE_FEATURES,
                         pedal_after=3.0, cadence_rpm=88.0)


@pytest.mark.case("T-DEV-11")
@pytest.mark.req("APP-115")
@pytest.mark.asyncio
async def test_a_trainer_with_cadence_shows_and_records_it(
        tmp_path: Path) -> None:
    session = AppSession(tmp_path, sim_trainer=cadence_trainer)
    await session.begin("builtin:erg-check")
    await session.until(30.0)
    assert session.app.console.view()["screen"]["cadence_rpm"] == 88
    assert session.command("finish") is None
    session.app.recorder.flush()
    ride = await session.close()
    samples = read_jsonl(ride / "samples.jsonl")
    assert samples and {s["cadence_rpm"] for s in samples[2:]} == {88.0}
    data = bytearray((ride / "ride.fit").read_bytes())
    messages, errors = Decoder(Stream.from_byte_array(data)).read()
    assert not errors
    records = messages["record_mesgs"]
    assert {r.get("cadence") for r in records[2:]} == {88}


@pytest.mark.case("T-DEV-11")
@pytest.mark.req("APP-115")
@pytest.mark.asyncio
async def test_the_d100_shows_no_cadence(tmp_path: Path) -> None:
    session = AppSession(tmp_path)
    await session.begin("builtin:erg-check")
    await session.until(10.0)
    assert session.app.console.view()["screen"]["cadence_rpm"] is None
    await session.close()


@pytest.mark.case("S-SIM-04")
def test_bystanders_only_advertise() -> None:
    scheduler = SimScheduler(SteppedClock())
    tv = SimAdvertiser(scheduler, "AA:00:00:00:00:09", "TV",
                       (sig_uuid(0x180A),), -50)
    assert tv.advertising() and tv.advertisement().name == "TV"
    with pytest.raises(KeyError):
        tv.on_read(uuids.BATTERY_LEVEL)
