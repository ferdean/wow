"""Take one sample per second of ride time.

The sampler (3A, core/sampler; APP-602 to APP-604): each whole second of
ride time gets the latest power, cadence and heart rate received in the
2 s before it, or no value. Paused time gets no samples, and ride time
continues after a pause without a hole.
"""

from collections import deque
from dataclasses import dataclass
from typing import Final

from wow.core.jsonform import Registry

HOLD: Final[float] = 2.0
EPSILON: Final[float] = 1e-6


@dataclass(frozen=True)
class Began:
    """Event: the ride clock started at mono."""

    mono: float


@dataclass(frozen=True)
class TrainerValue:
    """Event: a trainer record arrived."""

    mono: float
    power: int | None
    cadence_rpm: float | None = None


@dataclass(frozen=True)
class HrValue:
    """Event: a heart-rate record arrived."""

    mono: float
    heart_rate_bpm: int | None


@dataclass(frozen=True)
class Paused:
    """Event: the ride clock stopped at mono."""

    mono: float


@dataclass(frozen=True)
class Resumed:
    """Event: the ride clock went on at mono."""

    mono: float


@dataclass(frozen=True)
class Stopped:
    """Event: the ride ended at mono; due samples are taken."""

    mono: float


@dataclass(frozen=True)
class Tick:
    """Event: the next sample is due."""


SamplerEvent = (Began | TrainerValue | HrValue | Paused | Resumed | Stopped
                | Tick)


@dataclass(frozen=True)
class Sample:
    """Action: the sample of one second of ride time."""

    t: int
    mono: float
    power: int | None
    heart_rate_bpm: int | None
    cadence_rpm: float | None


SAMPLER_FORMS: Final[Registry] = Registry(
    Began, TrainerValue, HrValue, Paused, Resumed, Stopped, Tick, Sample)


class _Channel:
    def __init__(self) -> None:
        self._values: deque[tuple[float, int | float | None]] = deque()

    def add(self, mono: float, value: int | float | None) -> None:
        self._values.append((mono, value))

    def at(self, instant: float) -> int | float | None:
        found: int | float | None = None
        stamp: float | None = None
        for mono, value in self._values:
            if mono > instant + EPSILON:
                break
            found, stamp = value, mono
        if stamp is None or instant - stamp > HOLD + EPSILON:
            return None
        return found

    def forget_before(self, instant: float) -> None:
        while len(self._values) > 1 and self._values[1][0] <= instant:
            self._values.popleft()


class Sampler:
    """One sample per second of ride time."""

    def __init__(self) -> None:
        self._origin: float | None = None
        self._paused_at: float | None = None
        self._next = 0
        self._stopped = False
        self._power = _Channel()
        self._cadence = _Channel()
        self._hr = _Channel()

    def handle(self, event: SamplerEvent, now: float) -> list[Sample]:
        """Handle an event and return the samples taken."""
        match event:
            case Began(mono=mono):
                self._origin, self._next = mono, 0
                return self._due(now)
            case TrainerValue(mono=mono, power=power, cadence_rpm=cadence):
                self._power.add(mono, power)
                self._cadence.add(mono, cadence)
            case HrValue(mono=mono, heart_rate_bpm=bpm):
                self._hr.add(mono, bpm if bpm else None)
            case Paused(mono=mono):
                samples = self._due(mono)
                self._paused_at = mono
                return samples
            case Resumed(mono=mono):
                if self._paused_at is not None and self._origin is not None:
                    self._origin += mono - self._paused_at
                self._paused_at = None
            case Stopped(mono=mono):
                samples = self._due(mono)
                self._stopped = True
                return samples
            case Tick():
                return self._due(now)
        return []

    def next_deadline(self) -> float | None:
        """Return when the next sample is due, if any."""
        if self._origin is None or self._paused_at is not None:
            return None
        return None if self._stopped else self._origin + self._next

    def _due(self, until: float) -> list[Sample]:
        samples: list[Sample] = []
        if self._origin is None or self._stopped:
            return samples
        while self._paused_at is None:
            instant = self._origin + self._next
            if instant > until + EPSILON:
                break
            power, cadence = self._power.at(instant), self._cadence.at(instant)
            hr = self._hr.at(instant)
            samples.append(Sample(
                self._next, round(instant, 6),
                None if power is None else int(power),
                None if hr is None else int(hr),
                None if cadence is None else float(cadence)))
            self._next += 1
            for channel in (self._power, self._cadence, self._hr):
                channel.forget_before(instant - HOLD)
        return samples
