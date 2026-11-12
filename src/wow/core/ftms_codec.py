"""Decode and encode Fitness Machine Service payloads.

Fitness Machine Service: decode what the trainer sends, encode what the
app writes (ICD IF-01, 4.1.3 and 4.1.4).
"""

from collections.abc import Iterator
from dataclasses import dataclass, replace
from enum import IntEnum

from wow.core.devices import (
    Erg, Range, Resistance, TrainerCapabilities, TrainerCommand,
    TrainerSample,
)
from typing import Final

REQUEST_CONTROL: Final[int] = 0x00
SET_TARGET_RESISTANCE_LEVEL: Final[int] = 0x04
SET_TARGET_POWER: Final[int] = 0x05
START_OR_RESUME: Final[int] = 0x07
SPIN_DOWN_CONTROL: Final[int] = 0x13
RESPONSE_CODE: Final[int] = 0x80

STATUS_RESET: Final[int] = 0x01
STATUS_SPIN_DOWN: Final[int] = 0x14
STATUS_CONTROL_PERMISSION_LOST: Final[int] = 0xFF

MAX_JOINED_PARTS: Final[int] = 8


class ResultCode(IntEnum):
    """Result code of a control point response."""

    SUCCESS = 0x01
    NOT_SUPPORTED = 0x02
    INVALID_PARAMETER = 0x03
    OPERATION_FAILED = 0x04
    CONTROL_NOT_PERMITTED = 0x05


class SpinDownStatus(IntEnum):
    """Spin-down status the trainer reports."""

    REQUESTED = 0x01
    SUCCESS = 0x02
    ERROR = 0x03
    STOP_PEDALING = 0x04


@dataclass(frozen=True)
class Dropped:
    """A payload that could not be decoded, kept with its reason."""

    reason: str
    data: bytes


@dataclass(frozen=True)
class Features:
    """Raw Fitness Machine Feature flags."""

    machine: int
    target: int

    @property
    def cadence_supported(self) -> bool:
        """Return whether the trainer measures cadence."""
        return bool(self.machine >> 1 & 1)

    @property
    def power_measurement(self) -> bool:
        """Return whether the trainer measures power."""
        return bool(self.machine >> 14 & 1)

    @property
    def resistance_target(self) -> bool:
        """Return whether resistance targets are supported."""
        return bool(self.target >> 2 & 1)

    @property
    def power_target(self) -> bool:
        """Return whether power targets are supported."""
        return bool(self.target >> 3 & 1)

    @property
    def spin_down_control(self) -> bool:
        """Return whether spin-down control is supported."""
        return bool(self.target >> 15 & 1)


@dataclass(frozen=True)
class ResistanceSupport:
    """Resistance level range and the width of its raw value."""

    range: Range
    data_width: int


@dataclass(frozen=True)
class IndoorBikeData:
    """One Indoor Bike Data record."""

    more_data: bool
    speed_kmh: float | None
    cadence_rpm: float | None
    resistance_raw: int | None
    power: int | None
    declared_length: int


@dataclass(frozen=True)
class ControlPointResponse:
    """Response to a control point request."""

    request_op: int
    result: int
    parameter: bytes


@dataclass(frozen=True)
class MachineStatus:
    """Fitness Machine Status notification."""

    code: int
    parameter: bytes


def _uint(data: bytes, start: int, size: int) -> int:
    return int.from_bytes(data[start:start + size], "little")


def _sint(data: bytes, start: int, size: int) -> int:
    return int.from_bytes(data[start:start + size], "little", signed=True)


def decode_features(data: bytes) -> Features | Dropped:
    """Decode the Fitness Machine Feature characteristic."""
    if len(data) < 8:
        return Dropped("feature value shorter than 8 bytes", data)
    return Features(_uint(data, 0, 4), _uint(data, 4, 4))


def _checked(candidate: Range, data: bytes) -> Range | Dropped:
    if candidate.step <= 0 or candidate.maximum < candidate.minimum:
        return Dropped("range with no valid step", data)
    return candidate


def decode_power_range(data: bytes) -> Range | Dropped:
    """Decode the Supported Power Range characteristic."""
    if len(data) != 6:
        return Dropped("power range is not 6 bytes", data)
    return _checked(
        Range(_sint(data, 0, 2), _sint(data, 2, 2), _uint(data, 4, 2)), data)


def decode_inclination_range(data: bytes) -> Range | Dropped:
    """Decode the Supported Inclination Range characteristic."""
    if len(data) != 6:
        return Dropped("inclination range is not 6 bytes", data)
    return _checked(
        Range(_sint(data, 0, 2), _sint(data, 2, 2), _uint(data, 4, 2)), data)


def decode_resistance_range(data: bytes) -> ResistanceSupport | Dropped:
    """Decode the Supported Resistance Level Range characteristic."""
    if len(data) == 6:
        candidate = Range(_sint(data, 0, 2), _sint(data, 2, 2),
                          _uint(data, 4, 2))
        width = 2
    elif len(data) == 3:
        candidate = Range(data[0], data[1], data[2])
        width = 1
    else:
        return Dropped("resistance range is neither 6 nor 3 bytes", data)
    checked = _checked(candidate, data)
    if isinstance(checked, Dropped):
        return checked
    return ResistanceSupport(checked, width)


def trainer_capabilities(
    features: Features,
    power: Range | None,
    resistance: Range | None,
) -> TrainerCapabilities:
    """Combine features and ranges into trainer capabilities."""
    return TrainerCapabilities(
        power=power if features.power_target else None,
        resistance=resistance if features.resistance_target else None,
        spin_down=features.spin_down_control,
        cadence=features.cadence_supported,
    )


def _bike_data_fields(
    flags: int, resistance_width: int
) -> Iterator[tuple[str, int, bool]]:
    if not flags & 1:
        yield "speed", 2, False
    layout = (
        (1, "average_speed", 2, False),
        (2, "cadence", 2, False),
        (3, "average_cadence", 2, False),
        (4, "distance", 3, False),
        (5, "resistance", resistance_width, resistance_width == 2),
        (6, "power", 2, True),
        (7, "average_power", 2, True),
        (8, "energy", 5, False),
        (9, "heart_rate", 1, False),
        (10, "metabolic_equivalent", 1, False),
        (11, "elapsed_time", 2, False),
        (12, "remaining_time", 2, False),
    )
    for bit, name, size, signed in layout:
        if flags >> bit & 1:
            yield name, size, signed


def decode_indoor_bike_data(
    data: bytes, resistance_width: int = 2
) -> IndoorBikeData | Dropped:
    """Decode one Indoor Bike Data notification."""
    if len(data) < 2:
        return Dropped("no flags", data)
    flags = _uint(data, 0, 2)
    values: dict[str, int] = {}
    offset = 2
    for name, size, signed in _bike_data_fields(flags, resistance_width):
        if offset + size > len(data):
            return Dropped(f"shorter than flags 0x{flags:04x} declare", data)
        values[name] = (_sint if signed else _uint)(data, offset, size)
        offset += size
    speed = values.get("speed")
    cadence = values.get("cadence")
    return IndoorBikeData(
        more_data=bool(flags & 1),
        speed_kmh=None if speed is None else speed / 100,
        cadence_rpm=None if cadence is None else cadence / 2,
        resistance_raw=values.get("resistance"),
        power=values.get("power"),
        declared_length=offset,
    )


class BikeDataAssembler:
    """Join a record the trainer split over several notifications."""

    def __init__(self) -> None:
        self._parts: list[IndoorBikeData] = []

    def add(self, part: IndoorBikeData) -> IndoorBikeData | None:
        """Add a part; return the whole record once it is complete."""
        self._parts.append(part)
        if part.more_data:
            if len(self._parts) > MAX_JOINED_PARTS:
                self._parts.clear()
            return None
        parts, self._parts = self._parts, []
        return replace(
            part,
            speed_kmh=_first(p.speed_kmh for p in parts),
            cadence_rpm=_first(p.cadence_rpm for p in parts),
            resistance_raw=_first(p.resistance_raw for p in parts),
            power=_first(p.power for p in parts),
            declared_length=sum(p.declared_length for p in parts),
        )


def _first[T](values: Iterator[T | None]) -> T | None:
    return next((v for v in values if v is not None), None)


def trainer_sample(
    record: IndoorBikeData, capabilities: TrainerCapabilities, mono: float
) -> TrainerSample:
    """Convert a bike data record into a trainer sample."""
    return TrainerSample(
        mono=mono,
        power=record.power,
        speed_kmh=record.speed_kmh,
        cadence_rpm=record.cadence_rpm if capabilities.cadence else None,
    )


def decode_control_point_response(
    data: bytes,
) -> ControlPointResponse | Dropped:
    """Decode a Control Point indication."""
    if len(data) < 3 or data[0] != RESPONSE_CODE:
        return Dropped("not a control point response", data)
    return ControlPointResponse(data[1], data[2], bytes(data[3:]))


def decode_spin_down_band(parameter: bytes) -> tuple[float, float] | Dropped:
    """Decode the speed band of a spin-down response."""
    if len(parameter) < 4:
        return Dropped("spin-down band shorter than 4 bytes", parameter)
    return _uint(parameter, 0, 2) / 100, _uint(parameter, 2, 2) / 100


def decode_status(data: bytes) -> MachineStatus | Dropped:
    """Decode a Fitness Machine Status notification."""
    if not data:
        return Dropped("empty status", data)
    return MachineStatus(data[0], bytes(data[1:]))


def encode_request_control() -> bytes:
    """Encode Request Control."""
    return bytes([REQUEST_CONTROL])


def encode_start_or_resume() -> bytes:
    """Encode Start or Resume."""
    return bytes([START_OR_RESUME])


def encode_target_power(power: int) -> bytes:
    """Encode Set Target Power in watts."""
    return bytes([SET_TARGET_POWER]) + power.to_bytes(2, "little", signed=True)


def encode_target_resistance(level_raw: int) -> bytes:
    """Encode Set Target Resistance Level."""
    return bytes([SET_TARGET_RESISTANCE_LEVEL, level_raw])


def encode_spin_down(start: bool) -> bytes:
    """Encode Spin Down Control; start or stop."""
    return bytes([SPIN_DOWN_CONTROL, 0x01 if start else 0x02])


def encode_command(command: TrainerCommand) -> bytes:
    """Encode a trainer command as a control point write."""
    match command:
        case Erg(power=power):
            return encode_target_power(power)
        case Resistance(level_raw=level):
            return encode_target_resistance(level)
