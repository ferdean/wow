"""Describe a recorded ride for its output files.

The data a FIT file and `meta.json` are written from (IF-09, IF-12):
the samples, the lap starts and pauses in ride time, and the metrics.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from wow.core.metrics import Metrics


@dataclass(frozen=True)
class RecordedSample:
    """One second of ride time as recorded."""

    t: int
    utc: datetime
    power: int | None
    heart_rate_bpm: int | None
    cadence_rpm: float | None
    target: int | None


@dataclass(frozen=True)
class Pause:
    """A pause, from its ride time, lasting a number of seconds."""

    t_ride: float
    duration: float


@dataclass(frozen=True)
class Activity:
    """A finished ride."""

    title: str
    app_version: str
    ftp: int
    start_utc: datetime
    duration: float
    samples: tuple[RecordedSample, ...]
    lap_starts: tuple[float, ...]
    pauses: tuple[Pause, ...]
    metrics: Metrics

    def utc_at(self, t_ride: float) -> datetime:
        """Return the UTC time of a ride time, pauses counted."""
        paused = sum(p.duration for p in self.pauses if p.t_ride <= t_ride)
        return self.start_utc + timedelta(seconds=t_ride + paused)

    @property
    def end_utc(self) -> datetime:
        """Return the UTC time the ride ended."""
        return self.utc_at(self.duration)

    def laps(self) -> list[tuple[float, float]]:
        """Return each lap's start and end in ride time."""
        starts = sorted({s for s in self.lap_starts if 0 <= s < self.duration}
                        | {0.0})
        return list(zip(starts, [*starts[1:], self.duration]))

    def samples_between(self, start: float, end: float
                        ) -> Sequence[RecordedSample]:
        """Return the samples of ride times in [start, end)."""
        return [s for s in self.samples if start <= s.t < end]
