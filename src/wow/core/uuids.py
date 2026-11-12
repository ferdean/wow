"""Name the Bluetooth SIG UUIDs the app uses.

Bluetooth SIG UUIDs the app uses (ICD 4.1.2, 4.2.2), full lower case.
"""
from typing import Final


def sig_uuid(short: int) -> str:
    """Return the full lower case UUID of a 16-bit SIG number."""
    return f"0000{short:04x}-0000-1000-8000-00805f9b34fb"


FITNESS_MACHINE_SERVICE: Final[str] = sig_uuid(0x1826)
FITNESS_MACHINE_FEATURE: Final[str] = sig_uuid(0x2ACC)
INDOOR_BIKE_DATA: Final[str] = sig_uuid(0x2AD2)
SUPPORTED_INCLINATION_RANGE: Final[str] = sig_uuid(0x2AD5)
SUPPORTED_RESISTANCE_LEVEL_RANGE: Final[str] = sig_uuid(0x2AD6)
SUPPORTED_POWER_RANGE: Final[str] = sig_uuid(0x2AD8)
FITNESS_MACHINE_CONTROL_POINT: Final[str] = sig_uuid(0x2AD9)
FITNESS_MACHINE_STATUS: Final[str] = sig_uuid(0x2ADA)

HEART_RATE_SERVICE: Final[str] = sig_uuid(0x180D)
HEART_RATE_MEASUREMENT: Final[str] = sig_uuid(0x2A37)
BATTERY_LEVEL: Final[str] = sig_uuid(0x2A19)

CYCLING_SPEED_AND_CADENCE_SERVICE: Final[str] = sig_uuid(0x1816)
