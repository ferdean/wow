"""Simulate the Van Rysel D100 trainer.

Simulated Van Rysel D100, built from the Phase 2 findings (3A,
"Simulated devices").
"""

import asyncio
import math
from dataclasses import dataclass

from wow.adapters.ble_sim.scheduler import SimScheduler
from wow.adapters.ble_sim.server import SimServerBase
from wow.core import ftms_codec as codec
from wow.core import uuids
from wow.core.ftms_codec import ResultCode
from wow.ports.gatt import Advertisement, Uuid
from typing import Final

D100_ADDRESS: Final[str] = "94:05:BB:03:5D:9D"
D100_NAME: Final[str] = "VANRYSEL-HT-9d5d"
D100_SERVICE_DATA: Final[bytes] = bytes.fromhex("012000")
D100_FEATURES: Final[bytes] = bytes.fromhex("014000000ca00000")
D100_POWER_RANGE: Final[bytes] = bytes.fromhex("320058020100")
D100_RESISTANCE_RANGE: Final[bytes] = bytes.fromhex("000064000100")
D100_INCLINATION_RANGE: Final[bytes] = bytes.fromhex("00003c000100")

DATA_INTERVALS: Final[tuple[float, ...]] = (0.21, 0.29)
ANSWER_DELAYS: Final[tuple[float, ...]] = (0.186, 0.25, 0.32, 0.39)
RESET_OFFSETS: Final[tuple[float, ...]] = (0.2, 0.25, 0.3)
ERG_DEAD_TIME: Final[float] = 0.7
ERG_T90: Final[float] = 1.5
ERG_TAU: Final[float] = (ERG_T90 - ERG_DEAD_TIME) / math.log(10)
RESISTANCE_POWER: Final[tuple[tuple[int, float], ...]] = (
    (0, 59.0), (25, 82.0), (50, 138.0), (75, 231.0), (100, 313.0))
RIDER_SPEED_KMH: Final[float] = 28.6


def resistance_power(level_raw: int) -> float:
    """Return the power in watts at a raw resistance level."""
    for (low, low_power), (high, high_power) in zip(
            RESISTANCE_POWER, RESISTANCE_POWER[1:]):
        if level_raw <= high:
            share = (max(level_raw, low) - low) / (high - low)
            return low_power + share * (high_power - low_power)
    return RESISTANCE_POWER[-1][1]


@dataclass(frozen=True)
class _Segment:
    start: float
    start_value: float
    target: float


class ErgResponse:
    """Dead time, then a first-order lag: 90 % of a step in 1.5 s (F-25)."""

    def __init__(self, initial: float) -> None:
        self._segments = [_Segment(-math.inf, initial, initial)]

    def set_target(self, at: float, target: float) -> None:
        """Set a new target at time at."""
        start = at + ERG_DEAD_TIME
        self._segments.append(_Segment(start, self.value(start), target))
        del self._segments[:-4]

    def value(self, at: float) -> float:
        """Return the power at time at."""
        segment = self._segments[0]
        for candidate in self._segments:
            if candidate.start <= at:
                segment = candidate
        if at <= segment.start:
            return segment.start_value
        decay = math.exp(-(at - segment.start) / ERG_TAU)
        return segment.target + (segment.start_value - segment.target) * decay


class SimD100Server(SimServerBase):
    """The simulated D100."""

    def __init__(
        self,
        scheduler: SimScheduler,
        *,
        features: bytes = D100_FEATURES,
        power_range: bytes | None = D100_POWER_RANGE,
        resistance_range: bytes | None = D100_RESISTANCE_RANGE,
        rider_speed_kmh: float = RIDER_SPEED_KMH,
        pedal_after_erg: float | None = None,
    ) -> None:
        super().__init__(
            scheduler,
            Advertisement(
                address=D100_ADDRESS,
                name=D100_NAME,
                rssi_dbm=-60,
                service_uuids=(uuids.FITNESS_MACHINE_SERVICE,),
                service_data={uuids.FITNESS_MACHINE_SERVICE:
                              D100_SERVICE_DATA},
            ),
            frozenset({uuids.INDOOR_BIKE_DATA,
                       uuids.FITNESS_MACHINE_CONTROL_POINT,
                       uuids.FITNESS_MACHINE_STATUS}),
        )
        values = {
            uuids.FITNESS_MACHINE_FEATURE: features,
            uuids.SUPPORTED_POWER_RANGE: power_range,
            uuids.SUPPORTED_RESISTANCE_LEVEL_RANGE: resistance_range,
            uuids.SUPPORTED_INCLINATION_RANGE: D100_INCLINATION_RANGE,
        }
        self._values = {k: v for k, v in values.items() if v is not None}
        self.pedal_after_erg = pedal_after_erg
        self.rider_speed_kmh = (rider_speed_kmh if pedal_after_erg is None
                                else 0.0)
        self._riding_speed_kmh = rider_speed_kmh
        self._clipping_in = False
        self.in_control = False
        self.level_raw = 0
        self.response = ErgResponse(resistance_power(0))
        self.answer_times: list[float] = []
        self._answers = 0
        self._data_task: asyncio.Task[None] | None = None

    def advertising(self) -> bool:
        """Return whether the trainer advertises."""
        return not self.linked()

    def read_value(self, char: Uuid) -> bytes:
        """Return the value of a characteristic."""
        return self._values[char]

    def power_now(self) -> int:
        """Return the current power in watts."""
        if self.rider_speed_kmh <= 0:
            return 0
        return round(self.response.value(self.scheduler.now()))

    def indoor_bike_record(self) -> bytes:
        """Return the current Indoor Bike Data record."""
        speed_raw = round(self.rider_speed_kmh * 100)
        vendor = (speed_raw // 3, self.level_raw * 30, self.level_raw * 30,
                  1000 - self.level_raw * 5, 28)
        return (
            (0x0040).to_bytes(2, "little")
            + speed_raw.to_bytes(2, "little")
            + self.power_now().to_bytes(2, "little", signed=True)
            + b"".join(v.to_bytes(2, "little") for v in vendor)
        )

    def subscribed(self, char: Uuid) -> None:
        """Start the notifications of a characteristic."""
        if char == uuids.INDOOR_BIKE_DATA and self._data_task is None:
            self._data_task = self.scheduler.repeat(
                self.scheduler.now() + DATA_INTERVALS[0], DATA_INTERVALS,
                lambda: self.send(uuids.INDOOR_BIKE_DATA,
                                  self.indoor_bike_record()))

    def stopped(self) -> None:
        """Stop all timed behaviour."""
        self.in_control = False
        if self._data_task is not None:
            self._data_task.cancel()
            self._data_task = None

    def written(self, char: Uuid, data: bytes) -> None:
        """Handle a write to a characteristic."""
        if char != uuids.FITNESS_MACHINE_CONTROL_POINT or not data:
            raise KeyError(char)
        now = self.scheduler.now()
        result = self._carry_out(data, now)
        answer_at = now + ANSWER_DELAYS[self._answers % len(ANSWER_DELAYS)]
        self._answers += 1
        self.scheduler.call_at(
            answer_at, lambda: self._answer(data[0], result))
        if data[0] == codec.REQUEST_CONTROL and result == ResultCode.SUCCESS:
            for offset in RESET_OFFSETS:
                self.scheduler.call_at(
                    answer_at + offset,
                    lambda: self.send(uuids.FITNESS_MACHINE_STATUS,
                                      bytes([codec.STATUS_RESET])))

    def _answer(self, op: int, result: ResultCode) -> None:
        self.answer_times.append(self.scheduler.now())
        self.send(uuids.FITNESS_MACHINE_CONTROL_POINT,
                  bytes([codec.RESPONSE_CODE, op, result]))

    def _carry_out(self, data: bytes, now: float) -> ResultCode:
        op = data[0]
        if op == codec.REQUEST_CONTROL:
            self.in_control = True
            return ResultCode.SUCCESS
        if op not in (codec.START_OR_RESUME, codec.SET_TARGET_POWER,
                      codec.SET_TARGET_RESISTANCE_LEVEL):
            return ResultCode.NOT_SUPPORTED
        if not self.in_control:
            return ResultCode.CONTROL_NOT_PERMITTED
        if op == codec.SET_TARGET_POWER and len(data) == 3:
            power = int.from_bytes(data[1:3], "little", signed=True)
            if not 50 <= power <= 600:
                return ResultCode.INVALID_PARAMETER
            self.response.set_target(now, power)
            self._rider_clips_in(now)
        elif op == codec.SET_TARGET_RESISTANCE_LEVEL and len(data) == 2:
            if data[1] > 100:
                return ResultCode.INVALID_PARAMETER
            self.level_raw = data[1]
            self.response.set_target(now, resistance_power(data[1]))
            if self.pedal_after_erg is not None:
                self.rider_speed_kmh = 0.0
                self._clipping_in = False
        elif op != codec.START_OR_RESUME:
            return ResultCode.INVALID_PARAMETER
        return ResultCode.SUCCESS

    def _rider_clips_in(self, now: float) -> None:
        delay = self.pedal_after_erg
        if delay is None or self.rider_speed_kmh > 0 or self._clipping_in:
            return
        self._clipping_in = True
        self.scheduler.call_at(now + delay, self._pedal)

    def _pedal(self) -> None:
        if self._clipping_in:
            self._clipping_in = False
            self.rider_speed_kmh = self._riding_speed_kmh
