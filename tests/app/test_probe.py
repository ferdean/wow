import json
from pathlib import Path

import pytest

from wow.adapters.ble_log import BleLogRecord, LoggingConnector
from wow.adapters.ble_sim import (
    D100_ADDRESS, SimConnector, SimD100Server, SimHrm200Server, SimScheduler,
)
from wow.adapters.clock_stepped import SteppedClock
from wow.app import probe


@pytest.mark.case("S-INF-03")
@pytest.mark.asyncio
async def test_probe_passes_on_the_simulator() -> None:
    clock = SteppedClock()
    scheduler = SimScheduler(clock)
    records: list[BleLogRecord] = []
    connector = LoggingConnector(
        SimConnector(clock, [SimD100Server(scheduler),
                             SimHrm200Server(scheduler)]),
        clock, records.append, lambda address: "device")
    lines: list[str] = []
    args = probe.parse_args(["--watts", "200", "--seconds", "10"])
    result = await clock.drive(probe.probe(args, clock, connector,
                                           lines.append))
    await scheduler.close()
    assert result == 0
    assert lines[-1].startswith("PASS")
    assert "200 W" in lines[-2] and "130 bpm" in lines[-2]
    writes = [r.hex for r in records if r.op == "write"]
    assert writes[:3] == ["00", "07", "05c800"] and writes[-1] == "0400"


@pytest.mark.case("S-INF-03")
@pytest.mark.asyncio
async def test_probe_fails_without_a_trainer() -> None:
    clock = SteppedClock()
    lines: list[str] = []
    args = probe.parse_args(["--seconds", "5"])
    result = await clock.drive(probe.probe(args, clock,
                                           SimConnector(clock, []),
                                           lines.append))
    assert result == 1 and lines[-1] == "FAIL: no control of the trainer"


@pytest.mark.case("S-INF-03")
def test_probe_command_on_the_simulator(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    log = tmp_path / "probe.jsonl"
    with pytest.raises(SystemExit) as stopped:
        probe.main(["--simulate", "--seconds", "1", "--log", str(log)])
    assert stopped.value.code == 0
    first = json.loads(log.read_text().splitlines()[0])
    assert first["op"] == "connect_start" and first["addr"] == D100_ADDRESS
    assert "PASS" in capsys.readouterr().out
