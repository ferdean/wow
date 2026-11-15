"""Check one ride directory.

Ride checks over one ride directory (test plan, section 6).

Reads `events.jsonl`, `samples.jsonl`, `ble.jsonl`, `timing.jsonl`,
`meta.json` and `ride.fit` of the ride, and the system Bluetooth log for
the connection made before the ride began, and prints one line per
check: pass, fail with the worst value, or not applicable.

Usage:
    uv run python tools/check_ride.py /var/lib/wow/rides/<ride id>
        [--system-log /var/lib/wow/logs/ble-system.jsonl]
"""

import argparse
import bisect
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from garmin_fit_sdk import Decoder, Stream

if TYPE_CHECKING:
    from garmin_fit_sdk.mesgs import FitMessages

CONTROL_POINT: Final[str] = "00002ad9-0000-1000-8000-00805f9b34fb"
LIMIT_MS: Final[float] = 100.0
LIMIT_S: Final[float] = 0.1
TOLERANCE_MS: Final[float] = 1.0
TARGET_OPS: Final[tuple[str, ...]] = ("04", "05")
# A D100 procedure is answered within 0.39 s (F-28); a command replaced
# while one is pending is never written (APP-106).
REPLACE_WINDOW_MS: Final[float] = 1000.0
INDOOR_BIKE_DATA: Final[str] = "00002ad2-0000-1000-8000-00805f9b34fb"
HEART_RATE: Final[str] = "00002a37-0000-1000-8000-00805f9b34fb"
HOLD_MS: Final[float] = 2000.0
# Samples carry whole ride seconds, so ages are known to within 1 s.
SECOND_MS: Final[float] = 1000.0
FILES_LIMIT_MS: Final[float] = 10000.0
BATTERY_LEVEL: Final[str] = "00002a19-0000-1000-8000-00805f9b34fb"
LOG_FIELDS: Final[frozenset[str]] = frozenset(
    {"utc", "mono_ms", "dev", "addr", "gen", "op", "uuid", "hex"})
# The trainer notifies 4 times a second (F-50); 5 s without a line
# means the log stopped.
LOG_GAP_MS: Final[float] = 5000.0
CHANNELS: Final[tuple[tuple[str, str, str], ...]] = (
    ("power", "trainer", INDOOR_BIKE_DATA), ("hr_bpm", "hrm", HEART_RATE))
TAPS_NEEDED: Final[int] = 100
SPAN_NEEDED_MS: Final[float] = 600000.0
DISPLAY_LIMIT_MS: Final[float] = 250.0
CEILING_MS: Final[float] = 1000.0
SHARE: Final[float] = 0.95

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
        record = next((w for w in writes if w["hex"] == wanted
                       and due - TOLERANCE_MS <= float(w["mono_ms"]) < until),
                      None)
        match = None if record is None else float(record["mono_ms"])
        repeat = index > 0 and command_bytes(commands[index - 1]) == wanted
        replaced = bool(later) and later[0] - due <= REPLACE_WINDOW_MS
        if match is None:
            found.append(_Written(None, None, replaced, repeat))
            continue
        delay = _delay(due, match, earlier, answers)
        ready = _ready_after(record, due, both)
        if ready is not None and match >= ready:
            delay = min(delay, match - ready)
        found.append(_Written(match, delay))
    return found


def _ready_after(write: Record | None, due: float,
                 log: Sequence[Record]) -> float | None:
    """Return when the write's connection got Start or Resume answered.

    A command that falls due before a new connection is ready is
    written after Request Control and Start or Resume (APP-104).
    """
    if write is None:
        return None
    ready = sorted(float(r["mono_ms"]) for r in indications(log)
                   if r.get("gen") == write.get("gen")
                   and r.get("addr") == write.get("addr")
                   and str(r.get("hex", "")).startswith("8007"))
    return next((t for t in ready if t > due), None)


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


def _verdict(check: str, delays: Sequence[float], passed: int,
             what: str) -> Outcome:
    share = passed / len(delays)
    worst = max(delays)
    ok = share >= SHARE and worst <= CEILING_MS
    return Outcome(check, "pass" if ok else "fail",
                   f"{len(delays)} {what}, {share * 100:.1f} % in time, "
                   f"worst {worst:.1f} ms")


def rr07(timing: Sequence[Record], ride_log: Sequence[Record]) -> Outcome:
    """Tap to the start of the write (APP-802).

    Half the round trip the page's clock offset came from counts against
    the app; a tap made while a procedure was pending passes within
    100 ms of that procedure's answer.
    """
    taps = [t for t in timing if t.get("kind") == "tap"
            and t.get("write_mono_ms") is not None]
    if len(taps) < TAPS_NEEDED:
        return Outcome("RR-07", "not applicable",
                       f"{len(taps)} taps with a write, fewer than "
                       f"{TAPS_NEEDED}")
    answers = sorted(float(r["mono_ms"]) for r in indications(ride_log))
    delays, passed = [], 0
    for tap in taps:
        written = float(tap["write_mono_ms"])
        delay = written - float(tap["tap_mono_ms"]) + float(
            tap.get("rtt_ms") or 0.0) / 2
        delays.append(delay)
        index = bisect.bisect_left(answers, float(tap["recv_mono_ms"]))
        answered = answers[index] if index < len(answers) else None
        if delay <= DISPLAY_LIMIT_MS or (
                tap.get("pending") and answered is not None
                and written - answered <= LIMIT_MS):
            passed += 1
    return _verdict("RR-07", delays, passed, "taps")


def rr08(timing: Sequence[Record], ride_log: Sequence[Record],
         events: Sequence[Record]) -> Outcome:
    """Arrival of each value to the paint that showed it (APP-803)."""
    paints = sorted(((float(p["data_mono_ms"]), float(p["paint_mono_ms"])
                      + float(p.get("rtt_ms") or 0.0) / 2)
                     for p in timing if p.get("kind") == "paint"))
    start = _ride_start(events)
    ends = [float(e["mono_ms"]) for e in events
            if e.get("type") in ("finished", "discarded")]
    end = ends[0] if ends else float("inf")
    shown = [p[0] for p in paints]
    arrivals = [float(r["mono_ms"]) for r in ride_log
                if r.get("op") == "notify"
                and r.get("uuid") in (INDOOR_BIKE_DATA, HEART_RATE)
                and start is not None and start <= float(r["mono_ms"]) < end
                and shown and float(r["mono_ms"]) <= shown[-1] + TOLERANCE_MS]
    if not arrivals or arrivals[-1] - arrivals[0] < SPAN_NEEDED_MS:
        return Outcome("RR-08", "not applicable",
                       "less than 10 min of painted values")
    delays, passed = [], 0
    for arrival in arrivals:
        index = bisect.bisect_left(shown, arrival - TOLERANCE_MS)
        delay = paints[index][1] - arrival
        delays.append(delay)
        passed += delay <= DISPLAY_LIMIT_MS
    return _verdict("RR-08", delays, passed, "values")


def trainer_dropouts(events: Sequence[Record]) -> list[tuple[float, float]]:
    """Return the trainer's dropouts in the journal, in mono ms."""
    windows, since = [], None
    for event in events:
        if event.get("device") != "trainer" or "mono_ms" not in event:
            continue
        if event["type"] == "dropout_start":
            since = float(event["mono_ms"])
        elif event["type"] == "dropout_end" and since is not None:
            windows.append((since, float(event["mono_ms"])))
            since = None
    if since is not None:
        windows.append((since, float("inf")))
    return windows


def _reachable(events: Sequence[Record]) -> list[Record]:
    windows = trainer_dropouts(events)
    return [c for c in of_type(events, "trainer_command")
            if not any(a <= float(c["due_mono_ms"]) < b for a, b in windows)]


def rr02(events: Sequence[Record], ride_log: Sequence[Record],
         system_log: Sequence[Record] = ()) -> Outcome:
    """Check RR-02: each target was written in time.

    Commands that fall due while the trainer is in a dropout can't be
    written; the command at the reconnect counts instead.
    """
    commands = _reachable(events)
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
    pauses = _pauses(events)
    offsets = [
        (float(s["mono_ms"])
         - _sample_ms(float(s["scheduled"]), start, pauses)) / 1000
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
    commands = [c for c in _reachable(events)
                if c.get("mode") == "erg" and c.get("t_ride") is not None]
    sent = list(zip(commands, _find_writes(commands, ride_log, system_log)))
    offsets, unchanged, unwritten = [], 0, []
    pauses = _pauses(events)
    for previous, step in zip(steps, steps[1:]):
        if step.get("cause") == "skip":
            continue
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
        offsets.append(write - _sample_ms(send, start, pauses))
    worst = max(offsets, key=abs, default=0.0)
    detail = (f"{len(offsets)} target changes, worst {worst:+.1f} ms from "
              f"one lead time ({lead} s) before the boundary; {unchanged} "
              "boundaries without a change")
    if unwritten:
        return Outcome("RR-04", "fail",
                       f"steps {unwritten} not written; {detail}")
    return Outcome("RR-04", "pass" if abs(worst) <= LIMIT_MS else "fail",
                   detail)


def _pauses(events: Sequence[Record]) -> list[tuple[float, float]]:
    paused = of_type(events, "paused")
    resumed = of_type(events, "resumed")
    return [(float(p["t_ride"]), float(r["mono_ms"]) - float(p["mono_ms"]))
            for p, r in zip(paused, resumed)]


def _sample_ms(t: float, start: float,
               pauses: Sequence[tuple[float, float]]) -> float:
    return start + t * 1000 + sum(d for at, d in pauses if at <= t)


def _dropouts(events: Sequence[Record], device: str,
              end: float) -> list[tuple[float, float]]:
    windows, since = [], None
    for event in events:
        if event.get("device") != device:
            continue
        if event["type"] == "dropout_start":
            since = float(event["t_ride"])
        elif event["type"] == "dropout_end" and since is not None:
            windows.append((since, float(event["t_ride"])))
            since = None
    if since is not None:
        windows.append((since, end))
    return windows


def _channel_faults(samples: Sequence[Record], key: str,
                    arrivals: Sequence[float],
                    mono_of: Callable[[float], float],
                    windows: Sequence[tuple[float, float]]) -> list[str]:
    hold = HOLD_MS / 1000
    first = next((i for i, s in enumerate(samples)
                  if s.get(key) is not None), len(samples))
    faults = []
    for sample in samples[first:]:
        t, value = float(sample["t"]), sample.get(key)
        inside = any(a <= t <= b + hold + 1 for a, b in windows)
        stale = any(a + hold + 1 <= t < b for a, b in windows)
        if value is None and not inside:
            faults.append(f"{key} missing at {t:g} s outside a dropout")
        elif value is not None and stale:
            faults.append(f"{key} {value} at {t:g} s inside a dropout")
        elif value is not None and arrivals:
            at = mono_of(t)
            index = bisect.bisect_right(arrivals, at + SECOND_MS)
            newest = arrivals[index - 1] if index else None
            if newest is None or at - newest > HOLD_MS + SECOND_MS:
                faults.append(f"{key} at {t:g} s older than 2 s")
    return faults


def rr05(events: Sequence[Record], samples: Sequence[Record],
         ride_log: Sequence[Record]) -> Outcome:
    """Check RR-05: one sample per second, missing only in dropouts."""
    start = _ride_start(events)
    if start is None or not samples:
        return Outcome("RR-05", "not applicable", "no samples")
    seconds = [int(s["t"]) for s in samples]
    if seconds != list(range(len(samples))):
        return Outcome("RR-05", "fail", "ride seconds missing or repeated")
    pauses = _pauses(events)

    def mono_of(t: float) -> float:
        return _sample_ms(t, start, pauses)

    faults, missing = [], []
    for key, device, uuid in CHANNELS:
        arrivals = sorted(float(r["mono_ms"]) for r in ride_log
                          if r.get("op") == "notify"
                          and r.get("dev") == device and r.get("uuid") == uuid)
        windows = _dropouts(events, device, float(len(samples)))
        faults += _channel_faults(samples, key, arrivals, mono_of, windows)
        missing.append(f"{sum(s.get(key) is None for s in samples)} "
                       f"without {key}")
    detail = f"{len(samples)} samples, {', '.join(missing)}"
    if faults:
        return Outcome("RR-05", "fail", f"{faults[0]} ({len(faults)} "
                       f"faults); {detail}")
    return Outcome("RR-05", "pass", detail)


def read_meta(ride: Path) -> Record | None:
    """Read the ride's meta.json, if any."""
    try:
        meta: Record = json.loads((ride / "meta.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    return meta


def read_fit(ride: Path) -> "FitMessages | None":
    """Decode the ride's FIT file, if any."""
    path = ride / "ride.fit"
    if not path.exists():
        return None
    messages, errors = Decoder(Stream.from_byte_array(
        bytearray(path.read_bytes()))).read()
    return None if errors else messages


def rr12(events: Sequence[Record], meta: Record | None) -> Outcome:
    """Check RR-12: FIT and meta.json written within 10 s of Finish."""
    finished = of_type(events, "finished")
    if not finished or meta is None or meta.get("state") != "finished":
        return Outcome("RR-12", "not applicable", "the ride was not finished")
    written = meta.get("files_mono_ms")
    if written is None:
        return Outcome("RR-12", "fail", "meta.json has no files_mono_ms")
    delay = float(written) - float(finished[0]["mono_ms"])
    return Outcome("RR-12", "pass" if delay <= FILES_LIMIT_MS else "fail",
                   f"files written {delay / 1000:.2f} s after finished")


def rr13(events: Sequence[Record], meta: Record | None,
         fit: "FitMessages | None") -> Outcome:
    """Check RR-13: the app version is in the files of the ride."""
    armed = of_type(events, "armed")
    if meta is None or fit is None or not armed:
        return Outcome("RR-13", "not applicable", "no FIT or meta.json")
    version = str(meta.get("app_version"))
    devices = fit.get("device_info_mesgs", [])
    found = {
        "journal": armed[0].get("app_version") == version,
        "fit": any(d.get("product_name") == f"WitchesOnWheels {version}"
                   for d in devices),
    }
    missing = [where for where, ok in found.items() if not ok]
    if missing:
        return Outcome("RR-13", "fail",
                       f"{version} missing in {', '.join(missing)}")
    return Outcome("RR-13", "pass", f"{version} in meta.json, journal, FIT")


def rr14(events: Sequence[Record], samples: Sequence[Record],
         fit: "FitMessages | None") -> Outcome:
    """Check RR-14: FIT records per second, laps per step, pauses."""
    if fit is None:
        return Outcome("RR-14", "not applicable", "no FIT file")
    records = fit.get("record_mesgs", [])
    laps = fit.get("lap_mesgs", [])
    timer = [str(e.get("event_type")) for e in fit.get("event_mesgs", [])
             if e.get("event") == "timer"]
    steps = len(of_type(events, "step_started")) + len(
        of_type(events, "workout_done"))
    pauses = len(of_type(events, "paused"))
    faults = []
    if len(records) != len(samples):
        faults.append(f"{len(records)} records for {len(samples)} samples")
    if len(laps) != steps:
        faults.append(f"{len(laps)} laps for {steps} steps started")
    if timer.count("stop_all") != pauses + 1 or (
            timer.count("start") != pauses + 1):
        faults.append(f"timer events {timer} for {pauses} pauses")
    detail = (f"{len(records)} records, {len(laps)} laps, "
              f"{pauses} pauses")
    if faults:
        return Outcome("RR-14", "fail", f"{'; '.join(faults)}")
    return Outcome("RR-14", "pass", detail)


def rr06(ride_log: Sequence[Record],
         system_log: Sequence[Record]) -> Outcome:
    """Check RR-06: one battery read, heart rate and battery notified."""
    links = {r["gen"] for r in [*system_log, *ride_log]
             if r.get("dev") == "hrm" and r.get("op") == "connected"}
    if not links:
        return Outcome("RR-06", "not applicable", "no strap connected")
    reads = Counter(r["gen"] for r in [*system_log, *ride_log]
                    if r.get("dev") == "hrm" and r.get("op") == "read"
                    and r.get("uuid") == BATTERY_LEVEL)
    notified = {r["uuid"] for r in ride_log
                if r.get("dev") == "hrm" and r.get("op") == "notify"}
    bad = [g for g in sorted(links) if reads.get(g) != 1]
    missing = {HEART_RATE, BATTERY_LEVEL} - notified
    detail = (f"{len(links)} connection(s), battery reads "
              f"{dict(sorted(reads.items()))}")
    if bad or missing:
        return Outcome("RR-06", "fail",
                       f"{detail}; not notified: {sorted(missing)}")
    return Outcome("RR-06", "pass", detail)


def rr09(events: Sequence[Record], ride_log: Sequence[Record]) -> Outcome:
    """Check RR-09: back within 10 s after each dropout.

    The connect path logs no advertisement, so the time counts from the
    start of the connect attempt that succeeded, which comes no earlier
    than the device advertising again plus the retry pause.
    """
    ends = [e for e in events
            if e.get("type") == "dropout_end" and "mono_ms" in e]
    if not ends:
        return Outcome("RR-09", "not applicable", "no dropout")
    worst, faults = 0.0, []
    for end in ends:
        device = end["device"]
        lines = [r for r in ride_log if r.get("dev") == device
                 and float(r["mono_ms"]) <= float(end["mono_ms"]) + 15000]
        connected = [r for r in lines if r.get("op") == "connected"]
        if not connected:
            faults.append(f"{device}: no reconnect logged")
            continue
        link = connected[-1]
        starts = [float(r["mono_ms"]) for r in lines
                  if r.get("op") == "connect_start"
                  and float(r["mono_ms"]) <= float(link["mono_ms"])]
        begin = starts[-1] if starts else float(link["mono_ms"])
        done = float(link["mono_ms"])
        if device == "trainer":
            targets = [float(r["mono_ms"]) for r in ride_log
                       if r.get("gen") == link["gen"]
                       and r.get("op") == "write"
                       and str(r.get("hex", ""))[:2] in TARGET_OPS]
            done = targets[0] if targets else float("inf")
        worst = max(worst, (done - begin) / 1000)
    detail = f"{len(ends)} dropout(s), worst {worst:.1f} s back"
    if faults or worst > 10.0:
        return Outcome("RR-09", "fail", "; ".join([*faults, detail]))
    return Outcome("RR-09", "pass", detail)


def rr10(events: Sequence[Record], ride_log: Sequence[Record]) -> Outcome:
    """Check RR-10: the last write of the ride is the lowest level."""
    ended = [e for e in events if e.get("type") in ("finished", "discarded")]
    writes = control_writes(ride_log)
    if not ended or not writes:
        return Outcome("RR-10", "not applicable", "the ride did not end")
    after = [c for c in of_type(events, "trainer_command")
             if float(c["mono_ms"]) >= float(ended[-1]["mono_ms"])]
    last = max(writes, key=lambda r: float(r["mono_ms"]))
    if not after or after[-1].get("mode") != "resistance":
        return Outcome("RR-10", "fail", "no lowest level sent at the end")
    wanted = command_bytes(after[-1])
    ok = last["hex"] == wanted
    detail = f"last write {last['hex']}, lowest level {wanted}"
    return Outcome("RR-10", "pass" if ok else "fail", detail)


def rr11(events: Sequence[Record], ride_log: Sequence[Record]) -> Outcome:
    """Check RR-11: every line complete, no stretch without lines."""
    if not ride_log:
        return Outcome("RR-11", "not applicable", "no Bluetooth log")
    incomplete = [i for i, r in enumerate(ride_log)
                  if not LOG_FIELDS <= r.keys()]
    times = sorted(float(r["mono_ms"]) for r in ride_log)
    windows = [(float(a.get("mono_ms", 0.0)),
                float(b.get("mono_ms", float("inf"))))
               for a, b in zip(of_type(events, "dropout_start"),
                               of_type(events, "dropout_end"))]
    gaps = [(a, b) for a, b in zip(times, times[1:])
            if b - a > LOG_GAP_MS and not any(
                s <= b and a <= e for s, e in windows)]
    detail = (f"{len(ride_log)} lines, {len(incomplete)} incomplete, "
              f"{len(gaps)} gaps over {LOG_GAP_MS / 1000:.0f} s")
    return Outcome("RR-11", "fail" if incomplete or gaps else "pass", detail)


def this_run(system_log: Sequence[Record],
             ride_log: Sequence[Record]) -> list[Record]:
    """Return the system log from the ride's connection to its start.

    Generations restart at 1 with every run of the app, and monotonic
    time with every boot, so earlier runs are cut off by file order:
    the system log is only ever appended to.
    """
    writes = control_writes(ride_log)
    if not writes:
        return list(system_log)
    first = min(writes, key=lambda r: float(r["mono_ms"]))
    link, start = (first["addr"], first["gen"]), str(first["utc"])
    before = [r for r in system_log if str(r.get("utc", "")) <= start]
    connected = [i for i, r in enumerate(before)
                 if r.get("op") == "connected"
                 and (r.get("addr"), r.get("gen")) == link]
    return before[connected[-1]:] if connected else before


def check(ride: Path, system_log: Path) -> list[Outcome]:
    """Run all checks on a ride directory."""
    events = read_lines(ride / "events.jsonl")
    samples = read_lines(ride / "samples.jsonl")
    ride_log = read_lines(ride / "ble.jsonl")
    timing = read_lines(ride / "timing.jsonl")
    system = this_run(read_lines(system_log), ride_log)
    meta, fit = read_meta(ride), read_fit(ride)
    return [rr01(ride_log, system), rr02(events, ride_log, system),
            rr03(events), rr04(events, ride_log, system),
            rr05(events, samples, ride_log), rr06(ride_log, system),
            rr07(timing, ride_log), rr08(timing, ride_log, events),
            rr09(events, ride_log), rr10(events, ride_log),
            rr11(events, ride_log), rr12(events, meta),
            rr13(events, meta, fit), rr14(events, samples, fit)]


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
