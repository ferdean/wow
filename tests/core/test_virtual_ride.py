"""Riding a route with the recorded power (SL-13)."""

import math
from collections.abc import Callable

import pytest

from tests.support.routes import climb, gpx, loop
from wow.core.route import Route, RouteChoice, RouteError, read_route
from wow.core.virtual_ride import (
    AIR_DENSITY, BIKE_KG, CDA_M2, CRR, GRAVITY, Rider, acceleration,
    rider_of, simulate, track_of,
)

RIDER = rider_of(75)


def steady(power: float, grade: float, rider: Rider = RIDER) -> float:
    """Return the speed at which power balances the resistance."""
    def surplus(v: float) -> float:
        return acceleration(rider, power, v, grade)

    return _root(surplus, 0.0, 40.0)


def _root(f: Callable[[float], float], low: float, high: float) -> float:
    for _ in range(200):
        middle = (low + high) / 2
        if f(middle) > 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def long_climb(grade: float, length: float = 30_000.0) -> Route:
    return read_route(gpx(climb(length, grade, step_m=100.0)), "climb")


@pytest.mark.case("T-VRD-01")
@pytest.mark.req("APP-903")
def test_the_model_balances_power_and_resistance() -> None:
    assert RIDER.mass_kg == 75 + BIKE_KG
    v = 9.0
    drag = 0.5 * AIR_DENSITY * CDA_M2 * v * v
    roll = RIDER.mass_kg * GRAVITY * CRR
    assert acceleration(RIDER, (drag + roll) * v, v, 0.0) == pytest.approx(
        0.0, abs=1e-12)
    slope = math.atan(0.05)
    hill = RIDER.mass_kg * GRAVITY * (math.sin(slope) + CRR * math.cos(slope))
    assert acceleration(RIDER, 0.0, 0.0, 0.05) == pytest.approx(
        -hill / RIDER.mass_kg)


@pytest.mark.case("T-VRD-01")
@pytest.mark.req("APP-903")
@pytest.mark.parametrize(("power", "grade"), [(200, 0.0), (250, 0.06),
                                              (300, 0.02)])
def test_steady_power_reaches_the_steady_speed(power: int,
                                               grade: float) -> None:
    track = simulate(long_climb(grade), [(t, power) for t in range(600)],
                     [], RIDER)
    assert track.points[-1].speed_mps == pytest.approx(
        steady(power, grade), rel=1e-3)
    assert track.ascent_m == pytest.approx(track.distance_m * grade,
                                           rel=1e-3)


@pytest.mark.case("T-VRD-01")
@pytest.mark.req("APP-903")
def test_coasting_downhill_reaches_the_terminal_speed() -> None:
    route = read_route(gpx(climb(30_000, -0.05, step_m=100.0, start_ele=2000)),
                       "descent")
    track = simulate(route, [(t, 0) for t in range(600)], [], RIDER)
    slope = math.atan(0.05)
    terminal = math.sqrt(RIDER.mass_kg * GRAVITY * (
        math.sin(slope) - CRR * math.cos(slope)) / (
        0.5 * AIR_DENSITY * CDA_M2))
    assert track.points[-1].speed_mps == pytest.approx(terminal, rel=1e-3)
    assert track.ascent_m == 0.0 and track.descent_m > 0


@pytest.mark.case("T-VRD-02")
@pytest.mark.req("APP-903")
def test_seconds_without_power_coast_and_a_pause_stops_the_rider() -> None:
    route = long_climb(0.0)
    seconds = [(t, 200 if t < 300 else None) for t in range(330)]
    coasting = simulate(route, seconds, [], RIDER)
    speeds = [p.speed_mps for p in coasting.points]
    assert speeds[329] < speeds[299]
    assert all(b <= a for a, b in zip(speeds[300:], speeds[301:]))
    paused = simulate(route, [(t, 200) for t in range(400)], [300.0], RIDER)
    assert paused.points[299].speed_mps == pytest.approx(steady(200, 0.0),
                                                         rel=1e-2)
    assert paused.points[300].speed_mps < 4.0
    standing = simulate(long_climb(0.08), [(t, 0) for t in range(10)], [],
                        RIDER)
    assert {p.speed_mps for p in standing.points} == {0.0}
    assert standing.distance_m == 0.0


@pytest.mark.case("T-VRD-03")
@pytest.mark.req("APP-905")
def test_a_ride_longer_than_the_route_starts_it_again() -> None:
    route = read_route(gpx(loop(radius_m=500.0, rise_m=20.0)), "loop")
    track = simulate(route, [(t, 250) for t in range(1800)], [], RIDER)
    laps = track.distance_m / route.length_m
    assert laps > 3
    distances = [p.distance_m for p in track.points]
    assert all(b > a for a, b in zip(distances, distances[1:]))
    assert track.ascent_m == pytest.approx(20.0 * laps, abs=20.0)
    assert track.descent_m == pytest.approx(track.ascent_m, abs=20.0)
    back = next(p for p in track.points if p.distance_m > route.length_m)
    assert back.lat == pytest.approx(route.lat[0], abs=1e-3)


@pytest.mark.case("T-VRD-03")
@pytest.mark.req("APP-905")
def test_a_point_to_point_route_jumps_back_without_counting_the_jump() -> None:
    route = read_route(gpx(climb(1000, 0.05)), "ramp")
    track = simulate(route, [(t, 400) for t in range(900)], [], RIDER)
    laps = track.distance_m / route.length_m
    assert laps > 1.5
    assert track.descent_m == pytest.approx(0.0, abs=1e-6)
    assert track.ascent_m == pytest.approx(0.05 * track.distance_m, rel=1e-3)
    altitudes = [p.altitude_m for p in track.points]
    assert min(altitudes) >= 400.0 - 1e-9 and max(altitudes) <= 450.0 + 1e-9


@pytest.mark.case("T-VRD-01")
@pytest.mark.req("APP-903")
def test_a_chosen_route_is_read_and_ridden() -> None:
    choice = RouteChoice("ramp.gpx", "Ramp", gpx(climb(2000, 0.03)))
    track = track_of(choice, [(t, 220) for t in range(60)], [], 75)
    assert track.route_name == "Ramp"
    assert [p.t for p in track.points] == list(range(60))
    assert track.by_second()[59] == track.points[-1]
    with pytest.raises(RouteError):
        track_of(RouteChoice("bad.gpx", "Bad", b"<gpx/>"), [(0, 100)], [], 75)
