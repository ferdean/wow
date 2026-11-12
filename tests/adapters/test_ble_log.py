import json
import re

import pytest

from tests.support.rig import make_rig
from wow.adapters.ble_log import (
    BleLogRecord, LoggingConnector, device_kind, record_line,
)
from wow.adapters.ble_sim import (
    D100_ADDRESS, HRM_ADDRESS, SimConnector, SimD100Server, SimScheduler,
    Traffic,
)
from wow.adapters.clock_stepped import SteppedClock
from wow.core import uuids
from wow.core.devices import Erg, Resistance
from wow.ports.gatt import Advertisement, GattError

UTC_FORM = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
FIELDS = ["utc", "mono_ms", "dev", "addr", "gen", "op", "uuid", "hex"]


def logged(lines: list[dict[str, object]], dev: str,
           *ops: str) -> list[tuple[object, bytes]]:
    return [(line["uuid"], bytes.fromhex(str(line["hex"])))
            for line in lines if line["dev"] == dev and line["op"] in ops]


def check_device(lines: list[dict[str, object]], dev: str,
                 traffic: Traffic) -> None:
    assert logged(lines, dev, "read") == traffic.reads
    assert logged(lines, dev, "write") == traffic.writes
    assert logged(lines, dev, "notify", "indicate") == traffic.sent


@pytest.mark.case("T-LOG-01")
@pytest.mark.req("APP-813")
@pytest.mark.asyncio
async def test_every_gatt_operation_logged_once() -> None:
    rig = make_rig()
    rig.manager.open_pre_ride()
    await rig.clock.advance(5.0)
    rig.trainer.set_command(Erg(150))
    await rig.clock.advance(30.0)
    rig.trainer.set_command(Resistance(40))
    await rig.clock.advance(30.0)
    await rig.close()
    assert rig.d100 is not None and rig.hrm is not None
    lines = [json.loads(record_line(record)) for record in rig.log]
    for line in lines:
        assert list(line)[:8] == FIELDS
        assert UTC_FORM.match(str(line["utc"]))
        assert isinstance(line["mono_ms"], float)
    check_device(lines, "trainer", rig.d100.traffic)
    check_device(lines, "hrm", rig.hrm.traffic)
    assert len(rig.d100.traffic.sent) > 200
    indicated = {line["uuid"] for line in lines if line["op"] == "indicate"}
    assert indicated == {uuids.FITNESS_MACHINE_CONTROL_POINT}
    assert rig.d100.traffic.writes[-1] == (
        uuids.FITNESS_MACHINE_CONTROL_POINT, bytes.fromhex("0400"))
    links = [(line["dev"], line["op"]) for line in lines
             if line["op"] in ("connect_start", "connected", "disconnected")]
    assert sorted(links) == sorted([
        ("trainer", "connect_start"), ("trainer", "connected"),
        ("trainer", "disconnected"), ("hrm", "connect_start"),
        ("hrm", "connected"), ("hrm", "disconnected")])


@pytest.mark.case("T-LOG-01")
@pytest.mark.req("APP-813")
def test_extra_fields_follow_the_common_ones() -> None:
    record = BleLogRecord("2026-11-10T17:40:48.123Z", 123456.7, "trainer",
                          "94:05:BB:03:5D:9D", None, "scan_result",
                          extra={"rssi_dbm": -60})
    assert json.loads(record_line(record)) == {
        "utc": "2026-11-10T17:40:48.123Z", "mono_ms": 123456.7,
        "dev": "trainer", "addr": "94:05:BB:03:5D:9D", "gen": None,
        "op": "scan_result", "uuid": None, "hex": None, "rssi_dbm": -60}


@pytest.mark.case("T-LOG-01")
@pytest.mark.req("APP-813")
@pytest.mark.asyncio
async def test_scan_failures_and_stale_release_are_logged() -> None:
    clock = SteppedClock()
    scheduler = SimScheduler(clock)
    records: list[BleLogRecord] = []
    connector = LoggingConnector(
        SimConnector(clock, [SimD100Server(scheduler)]), clock,
        records.append, lambda address: "trainer")
    found = await clock.drive(
        connector.scan([uuids.FITNESS_MACHINE_SERVICE], 5.0))
    assert [a.address for a in found] == [D100_ADDRESS]
    with pytest.raises(GattError):
        await clock.drive(connector.connect(HRM_ADDRESS, 10.0, print))
    client = await clock.drive(connector.connect(D100_ADDRESS, 10.0, print))
    with pytest.raises(GattError):
        await clock.drive(client.write(uuids.BATTERY_LEVEL, b"\x01"))
    connector.stale_release(D100_ADDRESS, "not connected")
    await client.close()
    await client.close()
    await scheduler.close()
    ops = [(r.op, r.hex) for r in records]
    assert ops == [
        ("scan_result", None), ("connect_start", None),
        ("connect_failed", None), ("connect_start", None),
        ("connected", None), ("write", "01"), ("write_failed", "01"),
        ("released_stale", None), ("disconnected", None)]
    assert records[0].extra == {
        "rssi_dbm": -60,
        "service_data": {uuids.FITNESS_MACHINE_SERVICE: "012000"}}
    assert records[7].extra == {"outcome": "not connected"}
    assert device_kind(found[0]) == "trainer"


@pytest.mark.case("T-LOG-01")
@pytest.mark.req("APP-813")
def test_device_kinds_by_service() -> None:
    def advert(*services: str) -> Advertisement:
        return Advertisement("AA", None, -50, services, {})

    assert device_kind(advert(uuids.HEART_RATE_SERVICE)) == "hrm"
    assert device_kind(advert(uuids.CYCLING_SPEED_AND_CADENCE_SERVICE)) == (
        "other")
