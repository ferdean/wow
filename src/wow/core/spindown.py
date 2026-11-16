"""Run a spin-down calibration as a state machine.

The trainer's FTMS spin-down (ICD IF-01, S-5; APP-501 to APP-504): the
request, the speed band the trainer answers with, its Stop Pedaling and
result statuses, and the 120 s limit, after which the trainer goes to
its lowest level and the calibration counts as failed.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from wow.core.ftms_codec import STATUS_SPIN_DOWN, ResultCode, SpinDownStatus

SPINDOWN_TIMEOUT: Final[float] = 120.0


class Phase(StrEnum):
    """Phase of a calibration (ICD IF-06, CalibrationScreen)."""

    IDLE = "idle"
    STARTING = "starting"
    SPEED_UP = "speed_up"
    STOP_PEDALING = "stop_pedaling"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


RUNNING: Final[tuple[Phase, ...]] = (
    Phase.STARTING, Phase.SPEED_UP, Phase.STOP_PEDALING)


@dataclass(frozen=True)
class Begin:
    """Event: the rider starts a calibration."""


@dataclass(frozen=True)
class Answered:
    """Event: the trainer answered Spin Down Control."""

    result: int
    band_kmh: tuple[float, float] | None


@dataclass(frozen=True)
class Status:
    """Event: a spin-down status notification arrived."""

    data: bytes


@dataclass(frozen=True)
class Speed:
    """Event: the trainer reported its speed."""

    speed_kmh: float | None


@dataclass(frozen=True)
class Cancel:
    """Event: the rider cancels the calibration."""


@dataclass(frozen=True)
class Tick:
    """Event: the time limit came."""


SpinDownEvent = Begin | Answered | Status | Speed | Cancel | Tick


@dataclass(frozen=True)
class RequestSpinDown:
    """Action: write Spin Down Control (start)."""


@dataclass(frozen=True)
class SetLowest:
    """Action: put the trainer at its lowest level."""


@dataclass(frozen=True)
class Result:
    """Action: log the result with its bytes (APP-503)."""

    ok: bool
    outcome: str
    data: bytes


SpinDownAction = RequestSpinDown | SetLowest | Result


class SpinDownMachine:
    """One calibration at a time."""

    def __init__(self) -> None:
        self.phase = Phase.IDLE
        self.band_kmh: tuple[float, float] | None = None
        self.speed_kmh: float | None = None
        self._started: float | None = None
        self._ended: float | None = None

    def elapsed(self, now: float) -> float:
        """Return the seconds since the start, frozen at the end."""
        if self._started is None:
            return 0.0
        return (self._ended if self._ended is not None else now) - (
            self._started)

    def handle(self, event: SpinDownEvent,
               now: float) -> list[SpinDownAction]:
        """Handle an event and return the actions to carry out."""
        match event:
            case Begin():
                if self.phase in RUNNING:
                    return []
                self.phase, self.band_kmh = Phase.STARTING, None
                self._started, self._ended = now, None
                return [RequestSpinDown()]
            case Speed(speed_kmh=speed):
                self.speed_kmh = speed
            case Answered(result=result, band_kmh=band):
                return self._answered(result, band, now)
            case Status(data=data):
                return self._status(data, now)
            case Cancel():
                if self.phase in RUNNING:
                    self._finish(Phase.IDLE, now)
                    return [SetLowest()]
                self.phase = Phase.IDLE
            case Tick():
                if self.phase in RUNNING and self._started is not None and (
                        now >= self._started + SPINDOWN_TIMEOUT):
                    self._finish(Phase.TIMEOUT, now)
                    return [SetLowest(), Result(False, "timeout", b"")]
        return []

    def next_deadline(self) -> float | None:
        """Return when the time limit comes, if running."""
        if self.phase not in RUNNING or self._started is None:
            return None
        return self._started + SPINDOWN_TIMEOUT

    def _answered(self, result: int, band: tuple[float, float] | None,
                  now: float) -> list[SpinDownAction]:
        if self.phase != Phase.STARTING:
            return []
        if result != ResultCode.SUCCESS:
            self._finish(Phase.ERROR, now)
            return [SetLowest(), Result(False, "refused",
                                        bytes([0x80, 0x13, result]))]
        self.phase, self.band_kmh = Phase.SPEED_UP, band
        return []

    def _status(self, data: bytes, now: float) -> list[SpinDownAction]:
        if len(data) < 2 or data[0] != STATUS_SPIN_DOWN or (
                self.phase not in RUNNING):
            return []
        match data[1]:
            case SpinDownStatus.STOP_PEDALING:
                self.phase = Phase.STOP_PEDALING
            case SpinDownStatus.SUCCESS:
                self._finish(Phase.SUCCESS, now)
                return [SetLowest(), Result(True, "success", data)]
            case SpinDownStatus.ERROR:
                self._finish(Phase.ERROR, now)
                return [SetLowest(), Result(False, "error", data)]
        return []

    def _finish(self, phase: Phase, now: float) -> None:
        self.phase = phase
        self._ended = now
