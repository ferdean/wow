import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from garmin_fit_sdk import Decoder, Stream

import spike_fit

START = datetime(2026, 11, 6, 19, 0, 0, tzinfo=timezone.utc)
ZURICH = ZoneInfo("Europe/Zurich")


def utc(seconds: float) -> str:
    stamp = START + timedelta(seconds=seconds)
    return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def line(seconds: float, **fields: object) -> str:
    return json.dumps({"utc": utc(seconds), **fields})


def ibd(seconds: float, watts: int) -> str:
    payload = bytes.fromhex("4000c409") + watts.to_bytes(2, "little")
    return line(seconds, kind="rx", uuid="2ad2", hex=payload.hex())


def heart(seconds: float, bpm: int) -> str:
    return line(seconds, kind="rx", uuid="2a37", hex=f"00{bpm:02x}")


def steps_log(offset: float) -> list[str]:
    lines = [
        line(offset, kind="event", name="profile",
             steps=[[10, 150], [10, 330]]),
        line(offset + 1, kind="event", name="profile_start"),
    ]
    for tick in range(80):
        at = offset + tick * 0.28
        lines.append(ibd(at, 150 if at < offset + 11 else 330))
        if tick % 2 == 0:
            lines.append(heart(at, 120))
    return lines


def decode(data: bytes) -> dict[str, list[dict[str, object]]]:
    assert Decoder(Stream.from_byte_array(bytearray(data))).check_integrity()
    messages, errors = Decoder(Stream.from_byte_array(bytearray(data))).read()
    assert errors == []
    return messages


def write(tmp_path: Path, name: str, lines: list[str]) -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_steps_run_becomes_an_indoor_ride_with_a_lap_per_step(
        tmp_path: Path) -> None:
    log = write(tmp_path, "steps.jsonl", steps_log(0))
    messages = decode(spike_fit.build([log], ZURICH))
    session = messages["session_mesgs"][0]
    assert session["sport"] == "cycling"
    assert session["sub_sport"] == "indoor_cycling"
    assert messages["file_id_mesgs"][0]["type"] == "activity"
    assert len(messages["lap_mesgs"]) == 3
    assert {r["power"] for r in messages["record_mesgs"]} == {150, 330}
    assert all(r["heart_rate"] == 120 for r in messages["record_mesgs"])


def test_two_runs_are_one_activity_with_timer_stops(tmp_path: Path) -> None:
    first = write(tmp_path, "a.jsonl", steps_log(0))
    later = [ibd(600 + t, 170) for t in range(30)]
    second = write(tmp_path, "b.jsonl", later)
    messages = decode(spike_fit.build([second, first], ZURICH))
    events = [(e["event"], e["event_type"]) for e in messages["event_mesgs"]]
    assert events == [("timer", "start"), ("timer", "stop_all")] * 2
    session = messages["session_mesgs"][0]
    assert session["total_timer_time"] < session["total_elapsed_time"]
    assert len(messages["activity_mesgs"]) == 1


def test_values_older_than_two_seconds_are_missing() -> None:
    series = spike_fit.Series()
    series.add(START, 200)
    assert series.latest(START + timedelta(seconds=2)) == 200
    assert series.latest(START + timedelta(seconds=3)) is None


def test_local_timestamp_carries_the_zurich_offset() -> None:
    local = spike_fit.local_fit_time(START, ZURICH)
    utc_only = spike_fit.local_fit_time(START, ZoneInfo("UTC"))
    assert local - utc_only == 3600
