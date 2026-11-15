"""Keep a real ride as a replay case.

Copies what a replay needs from a ride directory on the Pi into
`testdata/rides/<ride id>/` (test plan 5.13, T-LOG-05; APP-820):
`events.jsonl` as recorded, `ble.jsonl` with the system log's lines of
the connections the ride used, and `workout.json` reduced to the
reference, the name and the steps, so no intervals.icu answer (athlete,
calendar) lands in the repository. Read the result before committing it.

Usage:
    uv run python tools/keep_ride.py /var/lib/wow/rides/<ride id>
        [--system-log /var/lib/wow/logs/ble-system.jsonl]
        [--out testdata/rides]
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
FREE_RIDE: Final[str] = "free_ride"


def read_lines(path: Path) -> list[dict[str, Any]]:
    """Read the complete lines of a JSON Lines file."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").split("\n")
    return [json.loads(line) for line in lines[:-1] if line.strip()]


def connections(ride_log: Sequence[dict[str, Any]]) -> set[tuple[str, int]]:
    """Return the (address, generation) pairs the ride's log shows."""
    return {(str(r["addr"]).upper(), int(r["gen"])) for r in ride_log
            if r.get("gen") is not None}


def links_before(system_log: Sequence[dict[str, Any]],
                 ride_log: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the system log's lines of the ride's connections.

    Generations restart at 1 with every run of the app, so only the
    last run before the ride counts: the lines from the last connect of
    each pair before the ride's first line.
    """
    if not ride_log:
        return []
    first = float(ride_log[0]["mono_ms"])
    wanted = connections(ride_log)
    before = [r for r in system_log if float(r["mono_ms"]) < first]
    kept: list[dict[str, Any]] = []
    for address, generation in sorted(wanted):
        starts = [i for i, r in enumerate(before)
                  if str(r.get("addr", "")).upper() == address
                  and r.get("op") == "connect_start"]
        if not starts:
            continue
        kept += [r for r in before[starts[-1]:]
                 if str(r.get("addr", "")).upper() == address
                 and r.get("gen") in (None, generation)]
    return kept


def workout_form(ride: Path, ref: str) -> dict[str, Any] | None:
    """Return the ride's workout as reference, name and steps only."""
    if ref == FREE_RIDE:
        return None
    raw = json.loads((ride / "workout.json").read_text(encoding="utf-8"))
    return {"ref": ref, "name": str(raw.get("name") or "Workout"),
            "workout_doc": raw["workout_doc"]}


def keep(ride: Path, system_log: Path, out: Path) -> Path:
    """Copy one ride into the replay cases; return its directory."""
    events = read_lines(ride / "events.jsonl")
    ride_log = read_lines(ride / "ble.jsonl")
    (armed,) = [e for e in events if e.get("type") == "armed"]
    target = out / ride.name
    target.mkdir(parents=True, exist_ok=True)
    lines = sorted(links_before(read_lines(system_log), ride_log) + ride_log,
                   key=lambda r: float(r["mono_ms"]))
    (target / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    (target / "ble.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    form = workout_form(ride, str(armed["workout_ref"]))
    if form is not None:
        (target / "workout.json").write_text(
            json.dumps(form, indent=1) + "\n", encoding="utf-8")
    return target


def main(argv: Sequence[str] | None = None) -> int:
    """Keep a ride from the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ride", type=Path)
    parser.add_argument("--system-log", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "testdata" /
                        "rides")
    args = parser.parse_args(argv)
    system_log = args.system_log or (
        args.ride.parent.parent / "logs" / "ble-system.jsonl")
    target = keep(args.ride, system_log, args.out)
    print(f"kept {args.ride.name} in {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
