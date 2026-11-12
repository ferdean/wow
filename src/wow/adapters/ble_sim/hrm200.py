"""Simulate the Garmin HRM 200 strap.

Simulated Garmin HRM 200: heart rate at 2 Hz with one RR interval,
Battery Level every 2 s (F-5, F-15, F-46).
"""

import asyncio

from wow.adapters.ble_sim.scheduler import SimScheduler
from wow.adapters.ble_sim.server import SimServerBase
from wow.core import uuids
from wow.ports.gatt import Advertisement, Uuid
from typing import Final

HRM_ADDRESS: Final[str] = "E0:E2:EF:63:14:BC"
HRM_NAME: Final[str] = "HRM200:739158"
HEART_RATE_INTERVAL: Final[float] = 0.5
BATTERY_INTERVAL: Final[float] = 2.0
RR_RESOLUTION: Final[int] = 1024


class SimHrm200Server(SimServerBase):
    """The simulated strap."""

    def __init__(
        self,
        scheduler: SimScheduler,
        *,
        heart_rate_bpm: int = 130,
        battery_pct: int = 80,
    ) -> None:
        super().__init__(
            scheduler,
            Advertisement(
                address=HRM_ADDRESS,
                name=HRM_NAME,
                rssi_dbm=-55,
                service_uuids=(uuids.HEART_RATE_SERVICE,),
                service_data={},
            ),
            frozenset({uuids.HEART_RATE_MEASUREMENT, uuids.BATTERY_LEVEL}),
        )
        self.heart_rate_bpm = heart_rate_bpm
        self.battery_raw = battery_pct
        self._tasks: list[asyncio.Task[None]] = []

    def read_value(self, char: Uuid) -> bytes:
        """Return the value of a characteristic."""
        if char != uuids.BATTERY_LEVEL:
            raise KeyError(char)
        return bytes([self.battery_raw])

    def heart_rate_record(self) -> bytes:
        """Return the current Heart Rate Measurement."""
        rr = round(60 / self.heart_rate_bpm * RR_RESOLUTION)
        return bytes([0x10, self.heart_rate_bpm]) + rr.to_bytes(2, "little")

    def subscribed(self, char: Uuid) -> None:
        """Start the notifications of a characteristic."""
        start = self.scheduler.now()
        if char == uuids.HEART_RATE_MEASUREMENT:
            self._tasks.append(self.scheduler.repeat(
                start + HEART_RATE_INTERVAL, (HEART_RATE_INTERVAL,),
                lambda: self.send(char, self.heart_rate_record())))
        else:
            self._tasks.append(self.scheduler.repeat(
                start + BATTERY_INTERVAL, (BATTERY_INTERVAL,),
                lambda: self.send(char, bytes([self.battery_raw]))))

    def stopped(self) -> None:
        """Stop all timed behaviour."""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
