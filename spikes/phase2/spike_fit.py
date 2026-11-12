"""Turn one evening's spike logs into one FIT activity. Throwaway."""

from __future__ import annotations

import argparse
import json
import sys
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean
from typing import Any
from zoneinfo import ZoneInfo

from garmin_fit_sdk import Encoder, Profile

import ftms_codec as codec

HOLD = timedelta(seconds=2)
SECOND = timedelta(seconds=1)
MESG = Profile["mesg_num"]
FIT_EPOCH = datetime.fromisoformat("1989-12-31T00:00:00+00:00")

Message = dict[str, Any]


@dataclass
class Series:
    stamps: list[datetime] = field(default_factory=list)
    values: list[int] = field(default_factory=list)

    def add(self, stamp: datetime, value: int) -> None:
        self.stamps.append(stamp)
        self.values.append(value)

    def latest(self, at: datetime) -> int | None:
        index = bisect_right(self.stamps, at) - 1
        if index < 0 or at - self.stamps[index] > HOLD:
            return None
        return self.values[index]


@dataclass(frozen=True)
class Sample:
    time: datetime
    power: int | None
    heart_rate: int | None


@dataclass
class Run:
    power: Series = field(default_factory=Series)
    heart_rate: Series = field(default_factory=Series)
    step_starts: list[datetime] = field(default_factory=list)


def parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def step_starts(start: datetime, steps: list[list[float]]) -> list[datetime]:
    starts, offset = [], 0.0
    for seconds, _watts in steps:
        starts.append(start + timedelta(seconds=offset))
        offset += seconds
    starts.append(start + timedelta(seconds=offset))
    return starts


def read_run(lines: list[str]) -> Run:
    run, steps = Run(), None
    for line in lines:
        record = json.loads(line)
        uuid, kind = record.get("uuid"), record["kind"]
        stamp = parse_utc(record["utc"])
        if kind == "rx" and uuid == "2ad2":
            values = codec.decode_indoor_bike(bytes.fromhex(record["hex"]))
            if "power_w" in values:
                run.power.add(stamp, int(values["power_w"]))
        elif kind == "rx" and uuid == "2a37":
            values = codec.decode_heart_rate(bytes.fromhex(record["hex"]))
            run.heart_rate.add(stamp, int(values["hr_bpm"]))
        elif record.get("name") == "profile":
            steps = record["steps"]
        elif record.get("name") == "profile_start" and steps:
            run.step_starts = step_starts(stamp, steps)
    return run


def resample(run: Run) -> list[Sample]:
    stamps = run.power.stamps + run.heart_rate.stamps
    if not stamps:
        return []
    samples, at, last = [], min(stamps).replace(microsecond=0), max(stamps)
    while at <= last:
        at += SECOND
        sample = Sample(at, run.power.latest(at), run.heart_rate.latest(at))
        if sample.power is not None or sample.heart_rate is not None:
            samples.append(sample)
    return samples


def lap_bounds(samples: list[Sample],
               starts: list[datetime]) -> list[datetime]:
    first, last = samples[0].time, samples[-1].time + SECOND
    inner = [stamp for stamp in starts if first < stamp < last]
    return [first, *inner, last]


def split(samples: list[Sample],
          bounds: list[datetime]) -> list[list[Sample]]:
    laps = [[s for s in samples if low <= s.time < high]
            for low, high in zip(bounds, bounds[1:])]
    return [lap for lap in laps if lap]


def span(samples: list[Sample]) -> float:
    return (samples[-1].time + SECOND - samples[0].time).total_seconds()


def summary(samples: list[Sample], timer_seconds: float) -> Message:
    values: Message = {
        "timestamp": samples[-1].time + SECOND,
        "start_time": samples[0].time,
        "total_elapsed_time": span(samples),
        "total_timer_time": timer_seconds,
    }
    power = [s.power for s in samples if s.power is not None]
    heart = [s.heart_rate for s in samples if s.heart_rate is not None]
    if power:
        values |= {"avg_power": round(fmean(power)),
                   "max_power": max(power),
                   "total_work": sum(power)}
    if heart:
        values |= {"avg_heart_rate": round(fmean(heart)),
                   "max_heart_rate": max(heart)}
    return values


def record(sample: Sample) -> Message:
    values: Message = {"mesg_num": MESG["RECORD"], "timestamp": sample.time}
    if sample.power is not None:
        values["power"] = sample.power
    if sample.heart_rate is not None:
        values["heart_rate"] = sample.heart_rate
    return values


def timer(at: datetime, event_type: str) -> Message:
    return {"mesg_num": MESG["EVENT"], "timestamp": at, "event": "timer",
            "event_type": event_type}


def header(start: datetime) -> list[Message]:
    return [
        {"mesg_num": MESG["FILE_ID"], "type": "activity",
         "manufacturer": "development", "product": 0,
         "serial_number": 1, "time_created": start},
        {"mesg_num": MESG["DEVICE_INFO"], "timestamp": start,
         "device_index": "creator", "manufacturer": "development",
         "product": 0, "product_name": "WitchesOnWheels spike"},
    ]


def local_fit_time(at: datetime, zone: ZoneInfo) -> int:
    offset = at.astimezone(zone).utcoffset() or timedelta()
    return int((at - FIT_EPOCH + offset).total_seconds())


def messages(runs: list[list[Sample]], laps: list[list[Sample]],
             zone: ZoneInfo) -> list[Message]:
    every = [s for run in runs for s in run]
    out = header(every[0].time)
    for run in runs:
        out.append(timer(run[0].time, "start"))
        out.extend(record(s) for s in run)
        out.append(timer(run[-1].time + SECOND, "stop_all"))
    for index, lap in enumerate(laps):
        out.append({"mesg_num": MESG["LAP"], "message_index": index,
                    "event": "lap", "event_type": "stop",
                    "lap_trigger": "manual", "sport": "cycling",
                    "sub_sport": "indoor_cycling",
                    **summary(lap, span(lap))})
    session = summary(every, sum(span(run) for run in runs))
    out.append({"mesg_num": MESG["SESSION"], "message_index": 0,
                "event": "session", "event_type": "stop",
                "trigger": "activity_end", "sport": "cycling",
                "sub_sport": "indoor_cycling", "first_lap_index": 0,
                "num_laps": len(laps), **session})
    out.append({"mesg_num": MESG["ACTIVITY"],
                "timestamp": session["timestamp"],
                "total_timer_time": session["total_timer_time"],
                "num_sessions": 1, "type": "manual", "event": "activity",
                "event_type": "stop",
                "local_timestamp": local_fit_time(session["timestamp"], zone)})
    return out


def encode(all_messages: list[Message]) -> bytes:
    encoder = Encoder()
    for message in all_messages:
        encoder.write_mesg(message)
    return encoder.close()


def build(paths: list[Path], zone: ZoneInfo) -> bytes:
    runs, laps = [], []
    for path in paths:
        run = read_run(path.read_text(encoding="utf-8").splitlines())
        samples = resample(run)
        if samples:
            runs.append(samples)
            laps += split(samples, lap_bounds(samples, run.step_starts))
    if not runs:
        raise ValueError("no power or heart-rate data in the logs")
    order = sorted(range(len(runs)), key=lambda i: runs[i][0].time)
    runs = [runs[i] for i in order]
    laps.sort(key=lambda lap: lap[0].time)
    return encode(messages(runs, laps, zone))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("ride.fit"))
    parser.add_argument("--tz", default="Europe/Zurich")
    args = parser.parse_args()
    try:
        data = build(args.logs, ZoneInfo(args.tz))
    except ValueError as error:
        sys.exit(f"spike_fit: {error}")
    args.output.write_bytes(data)
    print(f"Wrote {args.output} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
