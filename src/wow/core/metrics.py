"""Compute the ride metrics of table M.

Table M of the requirements (3A, core/metrics; APP-606): averages,
normalized power, intensity factor, training stress score, work, time
in zone and heart rate, from the samples of one ride.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import Final

from wow.core.numbers import DEFAULT_ZONES_PCT, zone_of

NP_WINDOW: Final[int] = 30
SECONDS_PER_HOUR: Final[int] = 3600


@dataclass(frozen=True)
class Metrics:
    """The metrics of one ride."""

    duration: int
    avg_power: float | None
    max_power: int | None
    np: float | None
    intensity_factor: float | None
    tss: float | None
    work_kj: float
    time_in_zone: tuple[int, ...]
    avg_hr_bpm: float | None
    max_hr_bpm: int | None


def normalized_power(power: Sequence[int]) -> float | None:
    """Return NP over the power samples present, or None under 30."""
    if len(power) < NP_WINDOW:
        return None
    window = sum(power[:NP_WINDOW])
    fourth = [(window / NP_WINDOW) ** 4]
    for index in range(NP_WINDOW, len(power)):
        window += power[index] - power[index - NP_WINDOW]
        fourth.append((window / NP_WINDOW) ** 4)
    return float(math.pow(fmean(fourth), 0.25))


def ride_metrics(power: Sequence[int | None], hr: Sequence[int | None],
                 ftp: int,
                 zones_pct: Sequence[int] = DEFAULT_ZONES_PCT) -> Metrics:
    """Return the metrics of samples in ride-time order."""
    watts = [p for p in power if p is not None]
    beats = [h for h in hr if h is not None]
    duration = len(power)
    np = normalized_power(watts)
    factor = None if np is None else np / ftp
    tss = (None if np is None or factor is None
           else duration * np * factor / (ftp * SECONDS_PER_HOUR) * 100)
    zones = [0] * (len(zones_pct) + 1)
    for value in watts:
        zones[zone_of(value, ftp, zones_pct) - 1] += 1
    return Metrics(
        duration=duration,
        avg_power=fmean(watts) if watts else None,
        max_power=max(watts) if watts else None,
        np=np, intensity_factor=factor, tss=tss,
        work_kj=sum(watts) / 1000,
        time_in_zone=tuple(zones),
        avg_hr_bpm=fmean(beats) if beats else None,
        max_hr_bpm=max(beats) if beats else None,
    )
