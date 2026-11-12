"""Check one ride directory.

Ride checks over one ride directory (test plan, section 6).

Reads `events.jsonl` and `ble.jsonl` of the ride, and the system
Bluetooth log for the connection made before the ride began, and prints
one line per check: pass, fail with the worst value, or not applicable.
Slice SL-02 has RR-01 to RR-04; the others follow with the files they
need.

Usage:
    uv run python tools/check_ride.py /var/lib/wow/rides/<ride id>
        [--system-log /var/lib/wow/logs/ble-system.jsonl]
"""

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

CONTROL_POINT: Final[str] = "00002ad9-0000-1000-8000-00805f9b34fb"
LIMIT_MS: Final[float] = 100.0
LIMIT_S: Final[float] = 0.1
TOLERANCE_MS: Final[float] = 1.0
TARGET_OPS: Final[tuple[str, ...]] = ("04", "05")
# A D100 procedure is answered within 0.39 s (F-28); a command replaced
# while one is pending is never written (APP-106).
REPLACE_WINDOW_MS: Final[float] = 1000.0

Record = dict[str, Any]


@dataclass(frozen=True)
class Outcome:
    """Result of one check."""

    check: str
    result: str
    detail: str

    def line(self) -> str:
        """Return the line printed for the check."""
        return f"{self.check} {self.result}: {self.detail}"


def read_lines(path: Path) -> list[Record]:
    """Read the records of a JSON Lines file."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    return [json.loads(line) for line in lines[:-1] if line.strip()]


def control_writes(log: Iterable[Record]) -> list[Record]:
    """Return the control point writes of a log."""
    return [r for r in log if r.get("op") == "write"
            and r.get("uuid") == CONTROL_POINT and r.get("dev") == "trainer"]


def indications(log: Iterable[Record]) -> list[Record]:
    """Return the control point indications of a log."""
    return [r for r in log if r.get("op") == "indicate"
            and r.get("uuid") == CONTROL_POINT]


def command_bytes(record: Record) -> str:
    """Return the written bytes of a record as hex."""
    if record.get("mode") == "erg":
        return "05" + int(record["power"]).to_bytes(
            2, "little", signed=True).hex()
    return "04" + int(record["level_raw"]).to_bytes(1, "little").hex()


def of_type(events: Iterable[Record], kind: str) -> list[Record]:
    """Return the journal records of one event type."""
    return [e for e in events if e.get("type") == kind]


def rr01(ride_log: Sequence[Record], system_log: Sequence[Record]) -> Outcome:
    """Check RR-01: the ride began with control held."""
    used = {(r["addr"], r["gen"]) for r in control_writes(ride_log)}
    if not used:
        return Outcome("RR-01", "not applicable", "no control point writes")
    writes = sorted(control_writes([*system_log, *ride_log]),
                    key=lambda r: float(r["mono_ms"]))
    bad = []
    for link in sorted(used):
        ops = [str(r["hex"])[:2] for r in writes
               if (r["addr"], r["gen"]) == link]
        first = ops[:3]
        expected = first[:2] == ["00", "07"] and all(
            op in TARGET_OPS for op in first[2:])
        if not expected:
            bad.append(f"{link[0]} generation {link[1]}: {' '.join(first)}")
    if bad:
        return Outcome("RR-01", "fail", "; ".join(bad))
    return Outcome("RR-01", "pass",
                   f"{len(used)} connection(s) began 00, 07, then targets")


@dataclass(frozen=True)
class _Written:
    write_ms: float | None
    delay_ms: float | None
    replaced: bool = False
    unchanged: bool = False


def _find_writes(commands: Sequence[Record], ride_log: Sequence[Record],
                 system_log: Sequence[Record] = ()) -> list[_Written]:
    both = [*system_log, *ride_log]
    writes = sorted(control_writes(ride_log),
                    key=lambda r: float(r["mono_ms"]))
    earlier = sorted(control_writes(both), key=lambda r: float(r["mono_ms"]))
    answers = sorted(float(r["mono_ms"]) for r in indications(both))
    found = []
    for index, command in enumerate(commands):
        due = float(command["due_mono_ms"])
        later = [float(c["due_mono_ms"]) for c in commands[index + 1:]]
        until = later[0] if later else float("inf")
        wanted = command_bytes(command)
        match = next((float(w["mono_ms"]) for w in writes
                      if w["hex"] == wanted
                      and due - TOLERANCE_MS <= float(w["mono_ms"]) < until),
                     None)
        repeat = index > 0 and command_bytes(commands[index - 1]) == wanted
        replaced = bool(later) and later[0] - due <= REPLACE_WINDOW_MS
        if match is None:
            found.append(_Written(None, None, replaced, repeat))
            continue
        found.append(_Written(match, _delay(due, match, earlier, answers)))
    return found


def _delay(due: float, written: float, writes: Sequence[Record],
           answers: Sequence[float]) -> float:
    delay = written - due
    if delay <= LIMIT_MS:
        return delay
    before = [float(w["mono_ms"]) for w in writes
              if float(w["mono_ms"]) < due - TOLERANCE_MS]
    if not before:
        return delay
    answer = next((a for a in answers if a > before[-1]), None)
    if answer is not None and answer > due:
        return written - answer
    return delay


def rr02(events: Sequence[Record], ride_log: Sequence[Record],
         system_log: Sequence[Record] = ()) -> Outcome:
    """Check RR-02: each target was written in time."""
    commands = of_type(events, "trainer_command")
    if not commands:
        return Outcome("RR-02", "not applicable", "no trainer commands")
    found = _find_writes(commands, ride_log, system_log)
    missing = [i for i, w in enumerate(found) if w.write_ms is None
               and not w.replaced and not w.unchanged]
    delays = [w.delay_ms for w in found if w.delay_ms is not None]
    replaced = sum(w.replaced for w in found)
    unchanged = sum(w.unchanged and not w.replaced for w in found)
    worst = max(delays, default=0.0)
    detail = (f"{len(delays)} commands written, worst {worst:.1f} ms, "
              f"{replaced} replaced before writing, {unchanged} equal to "
              "the command before")
    if missing:
        return Outcome("RR-02", "fail",
                       f"commands {missing} never written; {detail}")
    if worst > LIMIT_MS:
        return Outcome("RR-02", "fail", detail)
    return Outcome("RR-02", "pass", detail)


def _ride_start(events: Sequence[Record]) -> float | None:
    started = of_type(events, "ride_started")
    return float(started[0]["mono_ms"]) if started else None


def rr03(events: Sequence[Record]) -> Outcome:
    """Check RR-03: the journal is complete."""
    start = _ride_start(events)
    steps = of_type(events, "step_started")
    if start is None or not steps:
        return Outcome("RR-03", "not applicable", "the ride never started")
    offsets = [(float(s["mono_ms"]) - start) / 1000 - float(s["scheduled"])
               for s in steps]
    worst = max(offsets, key=abs)
    detail = f"{len(steps)} steps, worst {worst * 1000:+.1f} ms"
    return Outcome("RR-03", "pass" if abs(worst) <= LIMIT_S else "fail",
                   detail)


def rr04(events: Sequence[Record], ride_log: Sequence[Record],
         system_log: Sequence[Record] = ()) -> Outcome:
    """Check RR-04: no target was lost or repeated."""
    start = _ride_start(events)
    armed = of_type(events, "armed")
    steps = sorted(of_type(events, "step_started"),
                   key=lambda s: int(s["index"]))
    if start is None or not armed or len(steps) < 2:
        return Outcome("RR-04", "not applicable", "no step boundary")
    lead = float(armed[0]["lead_time"])
    commands = [c for c in of_type(events, "trainer_command")
                if c.get("mode") == "erg" and c.get("t_ride") is not None]
    sent = list(zip(commands, _find_writes(commands, ride_log, system_log)))
    offsets, unchanged, unwritten = [], 0, []
    for previous, step in zip(steps, steps[1:]):
        boundary = float(step["scheduled"])
        send = max(float(previous["scheduled"]), boundary - lead)
        written = next((w for c, w in sent if send - LIMIT_S
                        <= float(c["t_ride"]) < boundary + LIMIT_S), None)
        if written is None:
            unchanged += 1
            continue
        write = written.write_ms
        if write is None:
            unwritten.append(int(step["index"]))
            continue
        offsets.append(write - (start + send * 1000))
    worst = max(offsets, key=abs, default=0.0)
    detail = (f"{len(offsets)} target changes, worst {worst:+.1f} ms from "
              f"one lead time ({lead} s) before the boundary; {unchanged} "
              "boundaries without a change")
    if unwritten:
        return Outcome("RR-04", "fail",
                       f"steps {unwritten} not written; {detail}")
    return Outcome("RR-04", "pass" if abs(worst) <= LIMIT_MS else "fail",
                   detail)


def check(ride: Path, system_log: Path) -> list[Outcome]:
    """Run all checks on a ride directory."""
    events = read_lines(ride / "events.jsonl")
    ride_log = read_lines(ride / "ble.jsonl")
    system = read_lines(system_log)
    return [rr01(ride_log, system), rr02(events, ride_log, system),
            rr03(events), rr04(events, ride_log, system)]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the checks from the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ride", type=Path)
    parser.add_argument("--system-log", type=Path)
    args = parser.parse_args(argv)
    system_log = args.system_log or (
        args.ride.parent.parent / "logs" / "ble-system.jsonl")
    outcomes = check(args.ride, system_log)
    print(f"Ride {args.ride.name}")
    for outcome in outcomes:
        print(outcome.line())
    return 1 if any(o.result == "fail" for o in outcomes) else 0


if __name__ == "__main__":
    sys.exit(main())
