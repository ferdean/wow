"""Pure decoders, encoders and timing helpers for the Phase 2 spikes."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from itertools import accumulate

Values = dict[str, float]

REQUEST_CONTROL = 0x00
SET_RESISTANCE = 0x04
SET_POWER = 0x05
START_RESUME = 0x07
SPIN_DOWN = 0x13
SPIN_DOWN_START = 0x01
RESPONSE = 0x80

SUCCESS = 0x01
INVALID_PARAMETER = 0x03
NO_RESPONSE = -1

RESULTS = {
    0x01: "success",
    0x02: "op code not supported",
    0x03: "invalid parameter",
    0x04: "operation failed",
    0x05: "control not permitted",
    NO_RESPONSE: "no response",
}

STATUS_SPIN_DOWN = 0x14
SPIN_DOWN_STATUS = {
    0x01: "requested",
    0x02: "success",
    0x03: "error",
    0x04: "stop pedaling",
}
STATUS = {
    0x01: "reset",
    0x02: "stopped or paused by user",
    0x03: "stopped by safety key",
    0x04: "started or resumed by user",
    0x05: "target speed changed",
    0x06: "target incline changed",
    0x07: "target resistance changed",
    0x08: "target power changed",
    0x12: "simulation parameters changed",
    STATUS_SPIN_DOWN: "spin down status",
    0xFF: "control permission lost",
}

SIG_BASE = "-0000-1000-8000-00805f9b34fb"


def sig_uuid(short: int) -> str:
    return f"0000{short:04x}{SIG_BASE}"


def short_uuid(uuid: str) -> str:
    uuid = uuid.lower()
    if uuid.startswith("0000") and uuid.endswith(SIG_BASE):
        return uuid[4:8]
    return uuid


@dataclass(frozen=True)
class Field:
    bit: int
    name: str
    size: int
    signed: bool = False
    scale: float = 1.0
    present_when_clear: bool = False

    def present(self, flags: int) -> bool:
        is_set = bool(flags >> self.bit & 1)
        return is_set != self.present_when_clear


def indoor_bike_fields(resistance_size: int) -> tuple[Field, ...]:
    return (
        Field(0, "speed_kmh", 2, scale=0.01, present_when_clear=True),
        Field(1, "speed_avg_kmh", 2, scale=0.01),
        Field(2, "cadence_rpm", 2, scale=0.5),
        Field(3, "cadence_avg_rpm", 2, scale=0.5),
        Field(4, "distance_m", 3),
        Field(5, "resistance", resistance_size, signed=resistance_size == 2),
        Field(6, "power_w", 2, signed=True),
        Field(7, "power_avg_w", 2, signed=True),
        Field(8, "energy_kcal", 2),
        Field(8, "energy_per_hour_kcal", 2),
        Field(8, "energy_per_minute_kcal", 1),
        Field(9, "hr_bpm", 1),
        Field(10, "met", 1, scale=0.1),
        Field(11, "elapsed_s", 2),
        Field(12, "remaining_s", 2),
    )


CYCLING_POWER_FIELDS = (
    Field(0, "balance_pct", 1, scale=0.5),
    Field(2, "torque_acc_nm", 2, scale=1 / 32),
    Field(4, "wheel_revs", 4),
    Field(4, "wheel_time_s", 2, scale=1 / 2048),
    Field(5, "crank_revs", 2),
    Field(5, "crank_time_s", 2, scale=1 / 1024),
    Field(6, "force_max_n", 2, signed=True),
    Field(6, "force_min_n", 2, signed=True),
    Field(7, "torque_max_nm", 2, signed=True, scale=1 / 32),
    Field(7, "torque_min_nm", 2, signed=True, scale=1 / 32),
    Field(8, "angles_raw", 3),
    Field(9, "top_dead_spot_deg", 2),
    Field(10, "bottom_dead_spot_deg", 2),
    Field(11, "energy_kj", 2),
)


def record_length(flags: int, fields: tuple[Field, ...], start: int) -> int:
    return start + sum(f.size for f in fields if f.present(flags))


def read_fields(
    data: bytes, start: int, flags: int, fields: tuple[Field, ...]
) -> Values:
    values: Values = {}
    offset = start
    for field in fields:
        if not field.present(flags):
            continue
        chunk = data[offset:offset + field.size]
        raw = int.from_bytes(chunk, "little", signed=field.signed)
        values[field.name] = raw * field.scale
        offset += field.size
    return values


def decode_indoor_bike(data: bytes, resistance_size: int = 2) -> Values:
    """Fields follow the flags. The D100 appends 10 bytes the flags don't
    declare, so bytes past the declared fields are counted, not decoded."""
    flags = int.from_bytes(data[:2], "little")
    fields = indoor_bike_fields(resistance_size)
    declared = record_length(flags, fields, 2)
    if declared > len(data):
        raise ValueError(
            f"Indoor Bike Data: flags {flags:#06x} declare {declared} "
            f"bytes, got {len(data)}"
        )
    values = read_fields(data, 2, flags, fields)
    values["flags"] = flags
    values["more_data"] = flags & 1
    values["extra_bytes"] = len(data) - declared
    return values


def resistance_field_size(range_length: int) -> int:
    """A 6-byte resistance range is the FTMS 1.0 layout, whose Indoor Bike
    Data resistance field is sint16; the current 3-byte layout uses uint8."""
    return 2 if range_length == 6 else 1


def decode_cycling_power(data: bytes) -> Values:
    flags, power = struct.unpack_from("<Hh", data)
    values = read_fields(data, 4, flags, CYCLING_POWER_FIELDS)
    values["power_w"] = power
    values["flags"] = flags
    return values


def decode_heart_rate(data: bytes) -> Values:
    flags = data[0]
    size = 2 if flags & 0x01 else 1
    values: Values = {
        "hr_bpm": int.from_bytes(data[1:1 + size], "little"),
        "contact": flags >> 1 & 0x03,
    }
    offset = 1 + size + (2 if flags & 0x08 else 0)
    if flags & 0x10:
        values["rr_count"] = (len(data) - offset) // 2
    return values


def decode_response(data: bytes) -> tuple[int, int, bytes]:
    if len(data) < 3 or data[0] != RESPONSE:
        raise ValueError(f"not a control point response: {data.hex()}")
    return data[1], data[2], bytes(data[3:])


def decode_spin_down_band(params: bytes) -> tuple[float, float]:
    low, high = struct.unpack_from("<HH", params)
    return low / 100, high / 100


def describe_status(data: bytes) -> str:
    code, params = data[0], bytes(data[1:])
    name = STATUS.get(code, f"status {code:#04x}")
    if code == STATUS_SPIN_DOWN and params:
        return f"{name}: {SPIN_DOWN_STATUS.get(params[0], hex(params[0]))}"
    if code == 0x08 and len(params) >= 2:
        watts = int.from_bytes(params[:2], "little", signed=True)
        return f"{name}: {watts} W"
    return f"{name} {params.hex(' ')}".rstrip()


def decode_range(data: bytes) -> tuple[int, int, int]:
    if len(data) == 6:
        return struct.unpack("<hhH", data)
    if len(data) == 3:
        return struct.unpack("<BBB", data)
    raise ValueError(f"range of {len(data)} bytes: {data.hex()}")


def decode_features(data: bytes) -> tuple[int, int]:
    if len(data) < 8:
        raise ValueError(f"feature of {len(data)} bytes: {data.hex()}")
    return struct.unpack_from("<II", data)


def power_command(watts: int) -> bytes:
    return bytes([SET_POWER]) + watts.to_bytes(2, "little", signed=True)


def resistance_command(raw: int, size: int) -> bytes:
    return bytes([SET_RESISTANCE]) + raw.to_bytes(
        size, "little", signed=size == 2
    )


@dataclass(frozen=True)
class Step:
    seconds: float
    watts: int


def step_profile(warmup_minutes: float, reps: int = 6) -> list[Step]:
    steps = [Step(warmup_minutes * 60, 150)] if warmup_minutes > 0 else []
    steps += [Step(30, 330), Step(30, 140)] * reps
    steps += [Step(120, 220), Step(60, 325), Step(120, 220), Step(180, 140)]
    return steps


def step_starts(steps: list[Step]) -> list[float]:
    return [0.0, *accumulate(s.seconds for s in steps)][:-1]


def total_seconds(steps: list[Step]) -> float:
    return sum(s.seconds for s in steps)


def target_plan(steps: list[Step], lead: float) -> list[tuple[float, int]]:
    plan: list[tuple[float, int]] = []
    for start, step in zip(step_starts(steps), steps):
        if not plan or plan[-1][1] != step.watts:
            plan.append((max(0.0, start - lead), step.watts))
    return plan


def current_step(steps: list[Step], elapsed: float) -> int | None:
    for index, start in reversed(list(enumerate(step_starts(steps)))):
        if elapsed >= start:
            return index if elapsed < total_seconds(steps) else None
    return None


def sweep_levels(low: int, high: int, count: int = 5) -> list[int]:
    return [round(low + (high - low) * i / (count - 1)) for i in range(count)]
