"""Samples survive `kill -9` of the app (L6, on the Pi).

20 runs of about 20 s each; set WOW_KILL_RUNS for a shorter look:

    WOW_KILL_RUNS=3 uv run pytest -m "pi and slow" tests/system/test_kill.py
"""

import os
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.support.app_rig import ROOT
from tools.check_ride import of_type, read_lines

AGE_LIMIT = 5.0
STARTED_WITHIN = 60.0


def kill_during_ride(tmp: Path, after: float) -> tuple[Path, float]:
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.support.kill_ride", str(tmp)],
        cwd=ROOT, stdout=subprocess.PIPE, text=True)
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "started"
        time.sleep(after)
        killed = time.monotonic()
        process.kill()
    finally:
        process.kill()
        process.wait(STARTED_WITHIN)
    (ride,) = sorted((tmp / "data" / "rides").iterdir())
    return ride, killed


@pytest.mark.case("T-REC-03")
@pytest.mark.req("APP-808")
@pytest.mark.pi
@pytest.mark.slow
def test_samples_older_than_5_s_survive_kill_9(tmp_path: Path) -> None:
    moments = random.Random(808)
    runs = int(os.environ.get("WOW_KILL_RUNS", "20"))
    for run in range(runs):
        after = moments.uniform(6.0, 30.0)
        ride, killed = kill_during_ride(tmp_path / f"run-{run}", after)
        (started,) = of_type(read_lines(ride / "events.jsonl"),
                             "ride_started")
        seconds = [int(s["t"]) for s in read_lines(ride / "samples.jsonl")]
        older = int(killed - float(started["mono_ms"]) / 1000 - AGE_LIMIT)
        assert seconds[:older + 1] == list(range(older + 1)), (
            f"run {run}, killed {after:.1f} s after start: {seconds}")


@pytest.mark.case("S-REC-02")
def test_a_torn_last_line_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "samples.jsonl"
    path.write_text('{"t": 0, "power": 120}\n{"t": 1, "pow', encoding="utf-8")
    assert read_lines(path) == [{"t": 0, "power": 120}]
