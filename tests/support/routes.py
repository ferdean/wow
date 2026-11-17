"""GPX files made up for the route tests: no real map data."""

import math
from collections.abc import Sequence

from wow.core.route import EARTH_RADIUS_M

Point = tuple[float, float, float | None]

START = (47.0, 8.0)


def gpx(points: Sequence[Point], name: str | None = "Test route",
        kind: str = "trk", namespace: str = "http://www.topografix.com/GPX/1/1"
        ) -> bytes:
    """Return a GPX document of points as a track or a route."""
    def point(tag: str, p: Point) -> str:
        ele = "" if p[2] is None else f"<ele>{p[2]:.2f}</ele>"
        return f'<{tag} lat="{p[0]:.7f}" lon="{p[1]:.7f}">{ele}</{tag}>'

    title = "" if name is None else f"<name>{name}</name>"
    if kind == "trk":
        body = (f"<trk>{title}<trkseg>"
                + "".join(point("trkpt", p) for p in points)
                + "</trkseg></trk>")
    else:
        body = (f"<rte>{title}" + "".join(point("rtept", p) for p in points)
                + "</rte>")
    xmlns = f' xmlns="{namespace}"' if namespace else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" '
            f'creator="wow tests"{xmlns}>{body}</gpx>\n').encode()


def north(metres: float) -> float:
    """Return the latitude change of a distance along a meridian."""
    return math.degrees(metres / EARTH_RADIUS_M)


def climb(length_m: float, grade: float, step_m: float = 20.0,
          start_ele: float = 400.0) -> list[Point]:
    """Return a straight climb north at a steady grade."""
    count = int(length_m // step_m)
    return [(START[0] + north(i * step_m), START[1],
             start_ele + grade * i * step_m) for i in range(count + 1)]


def loop(radius_m: float = 1500.0, rise_m: float = 40.0,
         points: int = 400) -> list[Point]:
    """Return a closed circle with one hill, back where it starts."""
    out: list[Point] = []
    for i in range(points + 1):
        angle = 2 * math.pi * i / points
        lat = START[0] + north(radius_m * math.sin(angle))
        lon = START[1] + math.degrees(radius_m * (1 - math.cos(angle)) / (
            EARTH_RADIUS_M * math.cos(math.radians(START[0]))))
        out.append((lat, lon, 400.0 + rise_m * (1 - math.cos(angle)) / 2))
    return out
