"""Decode Heart Rate Measurement and Battery Level.

Heart Rate Measurement and Battery Level (ICD IF-02, 4.2.2).
"""

from dataclasses import dataclass

from wow.core.ftms_codec import Dropped
from typing import Final

RR_RESOLUTION: Final[int] = 1024


@dataclass(frozen=True)
class HeartRate:
    """One decoded heart rate measurement."""

    heart_rate_bpm: int | None
    rr: tuple[float, ...]


@dataclass(frozen=True)
class BatteryLevel:
    """One decoded battery level."""

    battery_pct: int | None
    raw: int


def decode_heart_rate(data: bytes) -> HeartRate | Dropped:
    """Decode a Heart Rate Measurement notification."""
    if len(data) < 2:
        return Dropped("heart rate shorter than 2 bytes", data)
    flags = data[0]
    width = 2 if flags & 0x01 else 1
    offset = 1 + width
    if len(data) < offset:
        return Dropped("heart rate value missing", data)
    value = int.from_bytes(data[1:offset], "little")
    if flags & 0x08:
        offset += 2
    rr: tuple[float, ...] = ()
    if flags & 0x10:
        pairs = (len(data) - offset) // 2
        rr = tuple(
            int.from_bytes(data[offset + 2 * i:offset + 2 * i + 2], "little")
            / RR_RESOLUTION
            for i in range(pairs)
        )
    return HeartRate(value if value > 0 else None, rr)


def decode_battery_level(data: bytes) -> BatteryLevel | Dropped:
    """Decode the Battery Level characteristic."""
    if not data:
        return Dropped("empty battery level", data)
    raw = data[0]
    return BatteryLevel(raw if raw <= 100 else None, raw)
