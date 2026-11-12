"""Device value types shared by the core and the shell (ICD IF-05)."""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class Range:
    """Inclusive range with a step, as the trainer reports it."""

    minimum: int
    maximum: int
    step: int


@dataclass(frozen=True)
class TrainerCapabilities:
    """Control modes and measurements the trainer supports."""

    power: Range | None
    resistance: Range | None
    spin_down: bool
    cadence: bool


@dataclass(frozen=True)
class Erg:
    """Command: hold a target power in watts."""

    power: int


@dataclass(frozen=True)
class Resistance:
    """Command: hold a raw resistance level."""

    level_raw: int


TrainerCommand = Erg | Resistance


class LinkState(StrEnum):
    """Connection state of a device."""

    NOT_CONFIGURED = "not_configured"
    SEARCHING = "searching"
    CONNECTED = "connected"
    NOT_FOUND = "not_found"
    DROPOUT = "dropout"


class DeviceKind(StrEnum):
    """Role of a Bluetooth device."""

    TRAINER = "trainer"
    HRM = "hrm"
    OTHER = "other"


@dataclass(frozen=True)
class TrainerSample:
    """One trainer reading; fields the trainer omits are None."""

    mono: float
    power: int | None
    speed_kmh: float | None
    cadence_rpm: float | None


@dataclass(frozen=True)
class HrSample:
    """One heart-rate reading with its RR intervals."""

    mono: float
    heart_rate_bpm: int | None
    rr: tuple[float, ...]
