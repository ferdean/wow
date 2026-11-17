"""The route screen's data: the route message and the live values (SL-14)."""

import math

import pytest

from tests.support.routes import climb, gpx, loop
from wow.core.route import read_route
from wow.core.view import MAP_POINTS, route_live, route_map


@pytest.mark.case("T-RTE-07")
@pytest.mark.req("APP-909")
def test_the_route_message_has_the_shape_and_elevation() -> None:
    route = read_route(gpx(loop(radius_m=3000.0, rise_m=60.0, points=600)),
                       "loop")
    found = route_map("loop.gpx@1", "Lake loop", route)
    assert found["type"] == "route" and found["route_id"] == "loop.gpx@1"
    points = found["points"]
    assert len(points) <= MAP_POINTS + 1
    assert points[0][0] == 0.0
    assert points[-1][0] == pytest.approx(route.length_m, abs=0.1)
    assert all(b[0] > a[0] for a, b in zip(points, points[1:]))
    xs, ys = [p[1] for p in points], [p[2] for p in points]
    assert min(xs) == 0.0 and min(ys) == 0.0
    assert max(max(xs), max(ys)) == pytest.approx(1000.0, abs=0.1)
    assert found["width"] == pytest.approx(found["height"], rel=0.01)
    assert (found["ele_min"], found["ele_max"]) == (pytest.approx(400.0,
                                                    abs=0.1),
                                                    pytest.approx(460.0,
                                                    abs=0.5))
    start = points[0]
    assert start[3] == pytest.approx(400.0, abs=0.1)


@pytest.mark.case("T-RTE-07")
@pytest.mark.req("APP-909")
def test_north_is_up_on_the_map() -> None:
    route = read_route(gpx(climb(2000, 0.0)), "north")
    found = route_map("north.gpx@1", "North", route)
    first, last = found["points"][0], found["points"][-1]
    assert first[2] > last[2]
    assert found["width"] == 0.0 and found["height"] == 1000.0


@pytest.mark.case("T-RTE-07")
@pytest.mark.req("APP-909")
def test_the_live_values_at_a_place_on_the_route() -> None:
    route = read_route(gpx(climb(2000, 0.05)), "ramp")
    live = route_live("ramp.gpx@1", route, 2500.4, 5.0, False)
    assert live == {"route_id": "ramp.gpx@1", "speed_kmh": 18.0,
                    "grade_pct": 5.0, "altitude_m": 425,
                    "distance_m": 2500, "at_m": pytest.approx(500.4, abs=0.1)}
    paused = route_live("ramp.gpx@1", route, 2500.4, 5.0, True)
    assert paused["speed_kmh"] == 0.0
    assert math.isclose(paused["at_m"], live["at_m"])
