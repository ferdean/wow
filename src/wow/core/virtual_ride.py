"""Ride a route with the power of a recorded ride.

Route simulation (SL-13; APP-903, APP-905): each ride second's power
moves a rider of the given mass along the route by the road-cycling
power model of Martin et al. (1998), here without wheel inertia and
bearing losses, in still air at sea-level density. A second without
power coasts, a pause stops the rider, and a ride longer than the route
starts it again from the beginning. The trainer reports power at the
hub, so no drivetrain loss is taken off.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final

from wow.core.route import Route, RouteChoice, read_route

GRAVITY: Final[float] = 9.80665
AIR_DENSITY: Final[float] = 1.225
CDA_M2: Final[float] = 0.32
CRR: Final[float] = 0.004
BIKE_KG: Final[float] = 9.0
SUBSTEPS: Final[int] = 4
MIN_PUSH_SPEED: Final[float] = 1.0


@dataclass(frozen=True)
class Rider:
    """The rider and bike as the model sees them."""

    mass_kg: float
    cda_m2: float = CDA_M2
    crr: float = CRR
    air_density: float = AIR_DENSITY


def rider_of(weight_kg: float) -> Rider:
    """Return the model rider for a rider's weight, bike included."""
    return Rider(weight_kg + BIKE_KG)


@dataclass(frozen=True)
class TrackPoint:
    """Where the rider is at the end of a ride second."""

    t: int
    distance_m: float
    speed_mps: float
    lat: float
    lon: float
    altitude_m: float


@dataclass(frozen=True)
class Track:
    """A ride on a route, second by second, with its totals."""

    route_name: str
    points: tuple[TrackPoint, ...]
    ascent_m: float
    descent_m: float

    @property
    def distance_m(self) -> float:
        """Return the distance ridden."""
        return self.points[-1].distance_m if self.points else 0.0

    @property
    def max_speed_mps(self) -> float:
        """Return the highest speed."""
        return max((p.speed_mps for p in self.points), default=0.0)

    def by_second(self) -> dict[int, TrackPoint]:
        """Return the points by ride second."""
        return {p.t: p for p in self.points}


@dataclass
class _State:
    distance: float = 0.0
    speed: float = 0.0
    ascent: float = 0.0
    descent: float = 0.0


def acceleration(rider: Rider, power: float, speed: float,
                 grade: float) -> float:
    """Return the acceleration at a speed, a power and a grade."""
    slope = math.atan(grade)
    push = power / max(speed, MIN_PUSH_SPEED)
    weight = rider.mass_kg * GRAVITY
    resist = (weight * math.sin(slope)
              + weight * rider.crr * math.cos(slope)
              + 0.5 * rider.air_density * rider.cda_m2 * speed * speed)
    return (push - resist) / rider.mass_kg


def _climb(route: Route, state: _State, before: float, after: float) -> None:
    length = route.length_m
    start, end = before % length, after % length
    if after // length > before // length:
        change = (route.ele_at(length) - route.ele_at(start)
                  + route.ele_at(end) - route.ele_at(0.0))
    else:
        change = route.ele_at(end) - route.ele_at(start)
    if change > 0:
        state.ascent += change
    else:
        state.descent -= change


def _second(route: Route, rider: Rider, state: _State, power: float) -> None:
    dt = 1.0 / SUBSTEPS
    for _ in range(SUBSTEPS):
        grade = route.grade_at(state.distance % route.length_m)
        speed = max(0.0, state.speed + acceleration(
            rider, power, state.speed, grade) * dt)
        before = state.distance
        state.distance += (state.speed + speed) / 2 * dt
        state.speed = speed
        _climb(route, state, before, state.distance)


def simulate(route: Route, seconds: Sequence[tuple[int, int | None]],
             stops: Sequence[float], rider: Rider) -> Track:
    """Return the ride of each second's power along the route.

    Seconds are (ride time, power); a stop is the ride time of a pause,
    after which the rider starts again from standstill.
    """
    state = _State()
    waiting = sorted(stops)
    points = []
    for t, power in seconds:
        while waiting and waiting[0] <= t:
            waiting.pop(0)
            state.speed = 0.0
        _second(route, rider, state, float(power or 0))
        place = route.place(state.distance % route.length_m)
        points.append(TrackPoint(t, state.distance, state.speed, place.lat,
                                 place.lon, place.ele))
    return Track(route.name, tuple(points), state.ascent, state.descent)


def track_of(choice: RouteChoice, seconds: Sequence[tuple[int, int | None]],
             stops: Sequence[float], weight_kg: float) -> Track:
    """Return a ride on a chosen route; raise RouteError if it is unusable.

    The track carries the name the rider chose the route by.
    """
    route = replace(read_route(choice.gpx, choice.name), name=choice.name)
    return simulate(route, seconds, stops, rider_of(weight_kg))
