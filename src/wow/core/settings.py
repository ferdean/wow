"""Check the rider's settings against table S.

The settings of table S (Phase 1, revision 7, with the lead time of
IM-41) and their JSON form in `settings.json` (ICD IF-10; APP-701 to
APP-708, APP-114): defaults, ranges and steps; a value outside its range
is rejected with the field and the range.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from fractions import Fraction
from typing import Any, Final

from wow.core.numbers import DEFAULT_ZONES_PCT, exact

SCHEMA: Final[int] = 1
ZONE_COUNT: Final[int] = 5
ADDRESS: Final[re.Pattern[str]] = re.compile(
    r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


class SettingKey(StrEnum):
    """A field of settings.json."""

    FTP = "ftp"
    ZONES_PCT = "zones_pct"
    LEAD_TIME = "lead_time"
    BATTERY_WARN_PCT = "battery_warn_pct"
    FREE_RIDE_LEVEL_PCT = "free_ride_level_pct"
    UPLOAD_ON = "upload_on"
    TRAINER = "trainer"
    HRM = "hrm"


@dataclass(frozen=True)
class DeviceRef:
    """A chosen Bluetooth device (APP-114)."""

    address: str
    name: str | None


@dataclass(frozen=True)
class Settings:
    """The rider's settings, at the defaults of table S."""

    ftp: int = 250
    zones_pct: tuple[int, ...] = DEFAULT_ZONES_PCT
    lead_time: float = 1.0
    battery_warn_pct: int = 20
    free_ride_level_pct: int = 0
    upload_on: bool = True
    trainer: DeviceRef | None = None
    hrm: DeviceRef | None = None


@dataclass(frozen=True)
class Span:
    """The range and step a number has to keep."""

    minimum: int
    maximum: int
    step: Fraction
    unit: str

    def holds(self, value: Fraction) -> bool:
        """Return whether a value lies on the range's steps."""
        steps = (value - self.minimum) / self.step
        return (self.minimum <= value <= self.maximum
                and steps.denominator == 1)

    def text(self) -> str:
        """Return the range in words."""
        step = (str(self.step.numerator) if self.step.denominator == 1
                else str(float(self.step)))
        return (f"{self.minimum} to {self.maximum} {self.unit} "
                f"in steps of {step}")


SPANS: Final[Mapping[SettingKey, Span]] = {
    SettingKey.FTP: Span(100, 500, Fraction(1), "W"),
    SettingKey.ZONES_PCT: Span(1, 200, Fraction(1), "% of FTP"),
    SettingKey.LEAD_TIME: Span(0, 5, Fraction(1, 2), "s"),
    SettingKey.BATTERY_WARN_PCT: Span(5, 50, Fraction(5), "%"),
    SettingKey.FREE_RIDE_LEVEL_PCT: Span(0, 100, Fraction(5), "%"),
}
ZONES_RULE: Final[str] = (
    f"{ZONE_COUNT} increasing upper bounds, "
    f"{SPANS[SettingKey.ZONES_PCT].text()}")
SWITCH_RULE: Final[str] = "true or false"
DEVICE_RULE: Final[str] = "an object with a Bluetooth address and a name"


@dataclass(frozen=True)
class Rejected:
    """A value a setting can't take."""

    key: str
    allowed: str

    def text(self) -> str:
        """Return the rejection in words."""
        return f"{self.key}: {self.allowed}"


def _number(value: object, span: Span) -> Fraction | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = exact(value)
    return number if span.holds(number) else None


def _zones(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, (list, tuple)) or len(value) != ZONE_COUNT:
        return None
    span = SPANS[SettingKey.ZONES_PCT]
    zones = [_number(item, span) for item in value]
    if any(zone is None for zone in zones):
        return None
    whole = tuple(int(zone) for zone in zones if zone is not None)
    if any(a >= b for a, b in zip(whole, whole[1:])):
        return None
    return whole


def device_ref(value: object) -> DeviceRef | None:
    """Return the device a JSON value names, if it is one."""
    if not isinstance(value, Mapping):
        return None
    address, name = value.get("address"), value.get("name")
    if not isinstance(address, str) or not ADDRESS.match(address):
        return None
    if name is not None and not isinstance(name, str):
        return None
    return DeviceRef(address.upper(), name)


def _device(settings: Settings, key: SettingKey,
            value: object) -> Settings | Rejected:
    device = None if value is None else device_ref(value)
    if value is not None and device is None:
        return Rejected(key, DEVICE_RULE)
    if key == SettingKey.TRAINER:
        return replace(settings, trainer=device)
    return replace(settings, hrm=device)


def _numeric(settings: Settings, key: SettingKey,
             value: object) -> Settings | Rejected:
    span = SPANS[key]
    number = _number(value, span)
    if number is None:
        return Rejected(key, span.text())
    match key:
        case SettingKey.FTP:
            return replace(settings, ftp=int(number))
        case SettingKey.LEAD_TIME:
            return replace(settings, lead_time=float(number))
        case SettingKey.BATTERY_WARN_PCT:
            return replace(settings, battery_warn_pct=int(number))
    return replace(settings, free_ride_level_pct=int(number))


def with_value(settings: Settings, key: str,
               value: object) -> Settings | Rejected:
    """Return the settings with one value changed, or the rejection."""
    if key not in set(SettingKey):
        return Rejected(key, "not a setting")
    setting = SettingKey(key)
    if setting == SettingKey.ZONES_PCT:
        zones = _zones(value)
        return (Rejected(key, ZONES_RULE) if zones is None
                else replace(settings, zones_pct=zones))
    if setting == SettingKey.UPLOAD_ON:
        return (replace(settings, upload_on=value)
                if isinstance(value, bool) else Rejected(key, SWITCH_RULE))
    if setting in (SettingKey.TRAINER, SettingKey.HRM):
        return _device(settings, setting, value)
    return _numeric(settings, setting, value)


def settings_of(raw: Mapping[str, Any]) -> tuple[Settings, list[Rejected]]:
    """Return the settings of a settings.json object, defaults for the rest.

    A value that can't be used keeps its default and is reported.
    """
    settings, rejected = Settings(), []
    for key in SettingKey:
        if key not in raw:
            continue
        changed = with_value(settings, key, raw[key])
        if isinstance(changed, Rejected):
            rejected.append(changed)
        else:
            settings = changed
    return settings, rejected


def settings_json(settings: Settings) -> dict[str, Any]:
    """Return the settings.json object of the settings."""
    def device(ref: DeviceRef | None) -> dict[str, Any] | None:
        return None if ref is None else {"address": ref.address,
                                         "name": ref.name}

    return {
        "schema": SCHEMA, "ftp": settings.ftp,
        "zones_pct": list(settings.zones_pct),
        "lead_time": settings.lead_time,
        "battery_warn_pct": settings.battery_warn_pct,
        "free_ride_level_pct": settings.free_ride_level_pct,
        "upload_on": settings.upload_on,
        "trainer": device(settings.trainer), "hrm": device(settings.hrm),
    }
