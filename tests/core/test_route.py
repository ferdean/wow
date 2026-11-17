"""GPX routes: reading, refusing and resampling (SL-13)."""

import math

import pytest

from tests.support.routes import START, climb, gpx, loop, north
from tests.support.timeline import TESTDATA
from wow.core.route import (
    EARTH_RADIUS_M, MAX_BYTES, MAX_GRADE, SPACING_M, GpxPoint, RouteError,
    build_route, great_circle_m, parse_gpx, read_route,
)

GPX10 = "http://www.topografix.com/GPX/1/0"


@pytest.mark.case("T-RTE-01")
@pytest.mark.req("APP-901")
@pytest.mark.parametrize("namespace", ["http://www.topografix.com/GPX/1/1",
                                       GPX10, ""])
def test_track_points_are_read_in_any_gpx_namespace(namespace: str) -> None:
    found = parse_gpx(gpx(climb(500, 0.05), "Hill", namespace=namespace))
    assert found.name == "Hill"
    assert len(found.points) == 26
    assert found.points[0] == GpxPoint(START[0], START[1], 400.0)


@pytest.mark.case("T-RTE-01")
@pytest.mark.req("APP-901")
def test_route_points_count_only_without_a_track() -> None:
    only_route = parse_gpx(gpx(climb(200, 0.0), "Planned", kind="rte"))
    assert len(only_route.points) == 11 and only_route.name == "Planned"
    track = gpx(climb(100, 0.0), "Ridden").replace(
        b"</gpx>", b'<rte><rtept lat="1" lon="1"/><rtept lat="2" lon="2"/>'
        b"</rte></gpx>")
    assert len(parse_gpx(track).points) == 6


@pytest.mark.case("T-RTE-01")
@pytest.mark.req("APP-901")
def test_the_name_comes_from_metadata_then_track_then_file() -> None:
    named = gpx(climb(200, 0.0), "Track name").replace(
        b"<trk>", b"<metadata><name>Meta name</name></metadata><trk>")
    assert parse_gpx(named).name == "Meta name"
    assert read_route(gpx(climb(200, 0.0), None), "from-file").name == (
        "from-file")


@pytest.mark.case("T-RTE-02")
@pytest.mark.req("APP-907")
@pytest.mark.parametrize(("data", "reason"), [
    (b"not xml at all", "not XML"),
    (b"<kml><trkpt lat='1' lon='1'/></kml>", "not a GPX file"),
    (b'<!DOCTYPE gpx [<!ENTITY a "x">]><gpx/>', "document type"),
    (gpx(climb(0, 0.0)), "fewer than two points"),
    (gpx([(91.0, 8.0, None), (47.0, 8.0, None)]), "outside WGS84"),
    (gpx(climb(100, 0.0)).replace(b'lat="47.0000000"', b'lat="x"', 1),
     "not a number"),
    (gpx(climb(100, 0.0)).replace(b"<ele>400.00</ele>", b"<ele>nan</ele>",
                                  1), "not finite"),
    (b" " * (MAX_BYTES + 1), "larger than 10 MB"),
])
def test_unusable_files_are_refused_with_the_reason(data: bytes,
                                                    reason: str) -> None:
    with pytest.raises(RouteError, match=reason):
        parse_gpx(data)


@pytest.mark.case("T-RTE-02")
@pytest.mark.req("APP-907")
def test_a_route_shorter_than_100_m_is_refused() -> None:
    with pytest.raises(RouteError, match="shorter than 100 m"):
        read_route(gpx(climb(80, 0.0)), "short")


@pytest.mark.case("T-RTE-03")
@pytest.mark.req("APP-903")
def test_distance_along_a_meridian_is_exact() -> None:
    a = GpxPoint(47.0, 8.0, None)
    b = GpxPoint(47.0 + north(1234.5), 8.0, None)
    assert great_circle_m(a, b) == pytest.approx(1234.5, abs=1e-6)
    east = GpxPoint(0.0, 1.0, None)
    assert great_circle_m(GpxPoint(0.0, 0.0, None), east) == pytest.approx(
        EARTH_RADIUS_M * math.radians(1.0), rel=1e-12)


@pytest.mark.case("T-RTE-03")
@pytest.mark.req("APP-903")
def test_a_route_is_resampled_every_10_m() -> None:
    route = build_route("climb", [GpxPoint(*p) for p in climb(1005, 0.06)])
    assert route.length_m == pytest.approx(1000.0, abs=1e-6)
    assert route.stations[:3] == (0.0, SPACING_M, 2 * SPACING_M)
    assert len(route.stations) == 101
    assert route.ascent_m == pytest.approx(60.0, abs=0.01)
    assert route.descent_m == pytest.approx(0.0, abs=1e-9)
    middle = route.place(505.0)
    assert middle.lat == pytest.approx(START[0] + north(505.0), abs=1e-9)
    assert middle.ele == pytest.approx(430.3, abs=0.01)
    assert middle.grade == pytest.approx(0.06, abs=1e-9)
    assert route.place(-5.0).lat == route.lat[0]
    assert route.place(1e9).lat == route.lat[-1]


@pytest.mark.case("T-RTE-03")
@pytest.mark.req("APP-903")
def test_elevation_is_smoothed_and_grades_kept_within_25_percent() -> None:
    wall = [(START[0] + north(i * 10.0), START[1],
             400.0 + (30.0 if i == 25 else 0.0)) for i in range(51)]
    route = read_route(gpx(wall), "spike")
    assert max(route.ele) == pytest.approx(406.0, abs=1e-3)
    steep = read_route(gpx(climb(1000, 0.40)), "steep")
    assert max(steep.grades) == MAX_GRADE
    assert steep.ascent_m == pytest.approx(400.0, abs=0.01)


@pytest.mark.case("T-RTE-03")
@pytest.mark.req("APP-903")
def test_a_route_without_elevation_is_flat() -> None:
    flat = read_route(gpx([(p[0], p[1], None) for p in climb(500, 0.1)]),
                      "flat")
    assert not flat.has_elevation
    assert set(flat.grades) == {0.0} and flat.ascent_m == 0.0
    loop_route = read_route(gpx(loop()), "loop")
    assert loop_route.has_elevation
    assert loop_route.length_m == pytest.approx(2 * math.pi * 1500.0,
                                                rel=1e-3)
    assert loop_route.ascent_m == pytest.approx(40.0, abs=0.5)
    assert loop_route.descent_m == pytest.approx(40.0, abs=0.5)


@pytest.mark.case("T-RTE-01")
@pytest.mark.req("APP-901")
def test_the_example_route_of_the_repository_reads() -> None:
    data = (TESTDATA.parent / "deploy" / "routes" / "example-loop.gpx"
            ).read_bytes()
    route = read_route(data, "example-loop")
    assert route.name == "Example loop (synthetic)"
    assert route.length_m == pytest.approx(18849, abs=5)
    assert route.ascent_m == pytest.approx(60, abs=0.5)
