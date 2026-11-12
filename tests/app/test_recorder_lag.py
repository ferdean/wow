"""The recorder's files and the loop-lag monitor (supporting tests)."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wow.adapters.ble_log import BleLogRecord
from wow.adapters.clock_stepped import SteppedClock
from wow.app import recorder as recorder_module
from wow.app.boot import boot_id
from wow.app.loop_lag import LoopLagMonitor
from wow.app.recorder import Recorder


def _ble(op: str) -> BleLogRecord:
    return BleLogRecord("2026-11-12T18:00:00.000Z", 1.0, "trainer", "A", 1,
                        op)


@pytest.mark.case("S-REC-01")
def test_journal_and_logs_go_to_their_files(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path, "boot-1")
    recorder.start()
    recorder.ble(_ble("connected"))
    recorder.journal({"type": "lost"})
    ride = recorder.open_ride("2026-11-12T180000Z")
    recorder.journal({"type": "armed", "t_ride": None})
    recorder.ble(_ble("write"))
    recorder.flush()
    assert (ride / "events.jsonl").read_text("utf-8").endswith("\n")
    recorder.close_ride(ride)
    recorder.ble(_ble("disconnected"))
    recorder.stop()
    assert recorder.ride_dir is None
    events = (ride / "events.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(e)["type"] for e in events] == ["armed"]
    ride_log = (ride / "ble.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(r)["op"] for r in ride_log] == ["write"]
    system = (tmp_path / "logs" / "ble-system.jsonl").read_text("utf-8")
    assert [json.loads(r)["op"] for r in system.splitlines()] == [
        "connected", "disconnected"]


@pytest.mark.case("S-REC-01")
def test_closing_an_old_ride_keeps_the_new_one_open(tmp_path: Path) -> None:
    recorder = Recorder(tmp_path, "boot-1")
    recorder.start()
    old = recorder.open_ride("a")
    new = recorder.open_ride("b")
    recorder.close_ride(old)
    recorder.journal({"type": "armed"})
    recorder.stop()
    assert recorder.ride_dir is None or recorder.ride_dir == new
    assert (new / "events.jsonl").exists()
    assert not (old / "events.jsonl").exists()


@pytest.mark.case("S-REC-01")
def test_a_write_error_is_logged_and_work_goes_on(
        tmp_path: Path, caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(recorder_module, "SYNC_INTERVAL", 0.0)
    blocked = tmp_path / "rides"
    blocked.write_text("not a directory", encoding="utf-8")
    recorder = Recorder(tmp_path, "boot-1")
    recorder.start()
    recorder.open_ride("x")
    recorder.journal({"type": "armed"})
    recorder.ble(_ble("write"))
    recorder.flush()
    recorder.close_ride(tmp_path / "rides" / "x")
    recorder.ble(_ble("connected"))
    recorder.stop()
    assert "recorder: mkdir" in caplog.text
    assert (tmp_path / "logs" / "ble-system.jsonl").exists()


@pytest.mark.case("S-REC-01")
def test_boot_id_from_the_kernel_or_a_fallback(tmp_path: Path) -> None:
    source = tmp_path / "boot_id"
    source.write_text("6f1c-77\n", encoding="ascii")
    assert boot_id(source) == "6f1c-77"
    assert boot_id(tmp_path / "missing").startswith("process-")


class Enough(Exception):
    pass


class LateClock:
    """Wakes every tenth sleeper late, then stops the run after 50."""

    def __init__(self, lag: float) -> None:
        self._now = 0.0
        self._lag = lag
        self._wakes = 0

    def monotonic(self) -> float:
        return self._now

    def utc(self) -> datetime:
        return datetime(2026, 11, 12, tzinfo=UTC)

    def synchronised(self) -> bool:
        return True

    async def sleep_until(self, mono: float) -> None:
        self._wakes += 1
        if self._wakes > 50:
            raise Enough
        self._now = max(self._now, mono)
        if self._wakes % 10 == 0:
            self._now += self._lag
        await asyncio.sleep(0)


@pytest.mark.case("S-LAG-01")
@pytest.mark.asyncio
async def test_loop_lag_over_50_ms_is_counted(
        caplog: pytest.LogCaptureFixture) -> None:
    monitor = LoopLagMonitor(LateClock(lag=0.08))
    with pytest.raises(Enough):
        await monitor.run()
    assert monitor.late == 5
    assert monitor.worst == pytest.approx(0.08)
    assert "event loop 80 ms late" in caplog.text


@pytest.mark.case("S-LAG-01")
@pytest.mark.asyncio
async def test_an_on_time_loop_counts_nothing() -> None:
    clock = SteppedClock()
    monitor = LoopLagMonitor(clock)
    with pytest.raises(TimeoutError):
        await clock.drive(monitor.run(), limit=5.0)
    assert monitor.late == 0 and monitor.worst == 0.0
