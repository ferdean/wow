"""tools/check_ride.py over the files of a simulated ride (test plan,
section 6: the same script runs over simulated rides)."""

import json
from pathlib import Path

import pytest

from tests.support.app_rig import read_jsonl, ride_erg_check
from tools import check_ride


def _rewrite(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records),
                    encoding="utf-8")


def _results(ride: Path, system: Path) -> dict[str, str]:
    return {o.check: o.result for o in check_ride.check(ride, system)}


@pytest.mark.case("S-RR-01")
@pytest.mark.asyncio
async def test_a_simulated_ride_passes_every_check(tmp_path: Path) -> None:
    app, ride = await ride_erg_check(tmp_path)
    system = app.config.data / "logs" / "ble-system.jsonl"
    assert _results(ride, system) == {
        check: "pass" for check in ("RR-01", "RR-02", "RR-03", "RR-04",
                                    "RR-05", "RR-12", "RR-13", "RR-14")}
    assert check_ride.main([str(ride)]) == 0


@pytest.mark.case("S-RR-01")
@pytest.mark.asyncio
async def test_samples_files_and_versions_that_do_not_hold_fail(
        tmp_path: Path) -> None:
    app, ride = await ride_erg_check(tmp_path)
    system = app.config.data / "logs" / "ble-system.jsonl"
    samples = read_jsonl(ride / "samples.jsonl")
    samples[100]["power"] = None
    _rewrite(ride / "samples.jsonl", samples[:-1])
    meta = json.loads((ride / "meta.json").read_text("utf-8"))
    meta["files_mono_ms"] += 11000.0
    meta["app_version"] = "9.9.9"
    (ride / "meta.json").write_text(json.dumps(meta), "utf-8")
    results = _results(ride, system)
    assert [results[c] for c in ("RR-05", "RR-12", "RR-13", "RR-14")] == [
        "fail"] * 4


@pytest.mark.case("S-RR-01")
@pytest.mark.asyncio
async def test_missing_values_pass_inside_a_dropout_only(
        tmp_path: Path) -> None:
    app, ride = await ride_erg_check(tmp_path)
    system = app.config.data / "logs" / "ble-system.jsonl"
    samples = read_jsonl(ride / "samples.jsonl")
    for sample in samples[100:110]:
        sample["power"] = None
    _rewrite(ride / "samples.jsonl", samples)
    started = next(e for e in read_jsonl(ride / "events.jsonl")
                   if e["type"] == "ride_started")["mono_ms"]
    log = [r for r in read_jsonl(ride / "ble.jsonl")
           if not (r["op"] == "notify" and r["dev"] == "trainer"
                   and 99_000 < r["mono_ms"] - started < 110_000)]
    _rewrite(ride / "ble.jsonl", log)
    assert _results(ride, system)["RR-05"] == "fail"
    events = read_jsonl(ride / "events.jsonl")
    events += [{"type": "dropout_start", "device": "trainer", "t_ride": 99.5},
               {"type": "dropout_end", "device": "trainer", "t_ride": 109.5}]
    _rewrite(ride / "events.jsonl", events)
    assert _results(ride, system)["RR-05"] == "pass"
    samples[105]["power"] = 0
    _rewrite(ride / "samples.jsonl", samples)
    assert _results(ride, system)["RR-05"] == "fail"


@pytest.mark.case("S-RR-01")
@pytest.mark.asyncio
async def test_late_writes_and_late_steps_fail(tmp_path: Path) -> None:
    app, ride = await ride_erg_check(tmp_path)
    log = read_jsonl(ride / "ble.jsonl")
    for record in log:
        if record["op"] == "write" and record["hex"] == "05dc00":
            record["mono_ms"] += 150.0
    _rewrite(ride / "ble.jsonl", log)
    events = read_jsonl(ride / "events.jsonl")
    for event in events:
        if event["type"] == "step_started" and event["index"] == 3:
            event["mono_ms"] += 150.0
    _rewrite(ride / "events.jsonl", events)
    system = app.config.data / "logs" / "ble-system.jsonl"
    results = _results(ride, system)
    assert results["RR-02"] == "fail"
    assert results["RR-03"] == "fail"
    assert results["RR-04"] == "fail"
    assert check_ride.main([str(ride)]) == 1


@pytest.mark.case("S-RR-01")
@pytest.mark.asyncio
async def test_a_connection_without_start_or_resume_fails_rr01(
        tmp_path: Path) -> None:
    app, ride = await ride_erg_check(tmp_path)
    system_path = app.config.data / "logs" / "ble-system.jsonl"
    system = [r for r in read_jsonl(system_path)
              if not (r["op"] == "write" and r["hex"] == "07")]
    _rewrite(system_path, system)
    assert _results(ride, system_path)["RR-01"] == "fail"


@pytest.mark.case("S-RR-01")
def test_an_empty_ride_is_not_applicable(tmp_path: Path) -> None:
    (tmp_path / "events.jsonl").write_text('{"type": "armed"', "utf-8")
    results = _results(tmp_path, tmp_path / "missing.jsonl")
    assert set(results.values()) == {"not applicable"}


@pytest.mark.case("S-RR-01")
def test_a_command_replaced_while_pending_is_not_a_failure() -> None:
    commands = [
        {"mode": "erg", "power": 330, "due_mono_ms": 1000.0},
        {"mode": "erg", "power": 335, "due_mono_ms": 1100.0},
        {"mode": "erg", "power": 340, "due_mono_ms": 1150.0},
    ]

    def write(at: float, hex_: str) -> dict[str, object]:
        return {"op": "write", "dev": "trainer", "addr": "A", "gen": 1,
                "uuid": check_ride.CONTROL_POINT, "mono_ms": at, "hex": hex_}
    log = [write(1001.0, "054a01"),
           {"op": "indicate", "uuid": check_ride.CONTROL_POINT,
            "mono_ms": 1300.0, "hex": "800501"},
           write(1320.0, "055401")]
    events = [{"type": "trainer_command", **c} for c in commands]
    outcome = check_ride.rr02(events, log)
    assert outcome.result == "pass"
    assert "1 replaced" in outcome.detail


@pytest.mark.case("S-RR-01")
def test_a_procedure_pending_from_before_the_ride_counts() -> None:
    def line(op: str, at: float, hex_: str) -> dict[str, object]:
        return {"op": op, "dev": "trainer", "addr": "A", "gen": 1,
                "uuid": check_ride.CONTROL_POINT, "mono_ms": at, "hex": hex_}
    system = [line("write", 990.0, "07"), line("indicate", 1200.0, "800701")]
    ride = [line("write", 1201.0, "054a01")]
    events = [{"type": "trainer_command", "mode": "erg", "power": 330,
               "due_mono_ms": 1000.0}]
    assert check_ride.rr02(events, ride).result == "fail"
    assert check_ride.rr02(events, ride, system).result == "pass"
