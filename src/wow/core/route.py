"""Read a GPX route and find places along it.

Route simulation (SL-13; APP-901, APP-903, APP-907): the track points of
a GPX 1.1 or 1.0 file, or its route points when it has no track, become
a route resampled every 10 m of its length, with the elevation smoothed
over 50 m (a window that narrows at the ends, so a steady climb keeps
its height) and the grade of each piece kept within ±25 %. Distances are
great-circle distances on a sphere of the Earth's mean radius.
"""

import math
import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

SPACING_M: Final[float] = 10.0
SMOOTH_HALF_WIDTH: Final[int] = 2
MAX_GRADE: Final[float] = 0.25
MIN_LENGTH_M: Final[float] = 100.0
MAX_BYTES: Final[int] = 10_000_000
EARTH_RADIUS_M: Final[float] = 6_371_008.8
FORBIDDEN: Final[tuple[bytes, ...]] = (b"<!DOCTYPE", b"<!ENTITY")


class RouteError(ValueError):
    """A file that can't be used as a route."""


@dataclass(frozen=True)
class GpxPoint:
    """A point of a GPX file: WGS84 degrees and metres."""

    lat: float
    lon: float
    ele: float | None


@dataclass(frozen=True)
class Gpx:
    """The name and points of a GPX file."""

    name: str | None
    points: tuple[GpxPoint, ...]


@dataclass(frozen=True)
class Place:
    """A place on a route."""

    lat: float
    lon: float
    ele: float
    grade: float


@dataclass(frozen=True)
class Route:
    """A route resampled along its length."""

    name: str
    stations: tuple[float, ...]
    lat: tuple[float, ...]
    lon: tuple[float, ...]
    ele: tuple[float, ...]
    grades: tuple[float, ...]
    has_elevation: bool

    @property
    def length_m(self) -> float:
        """Return the route's length."""
        return self.stations[-1]

    @property
    def ascent_m(self) -> float:
        """Return the climbing of one lap."""
        return sum(max(0.0, b - a) for a, b in zip(self.ele, self.ele[1:]))

    @property
    def descent_m(self) -> float:
        """Return the descending of one lap."""
        return sum(max(0.0, a - b) for a, b in zip(self.ele, self.ele[1:]))

    def _locate(self, distance: float) -> tuple[int, float]:
        at = min(max(distance, 0.0), self.length_m)
        index = min(int(at // SPACING_M), len(self.stations) - 2)
        low, high = self.stations[index], self.stations[index + 1]
        return index, (at - low) / (high - low)

    def place(self, distance: float) -> Place:
        """Return the place at a distance from the start, within one lap."""
        index, part = self._locate(distance)
        return Place(_between(self.lat, index, part),
                     _between(self.lon, index, part),
                     _between(self.ele, index, part), self.grades[index])

    def ele_at(self, distance: float) -> float:
        """Return the elevation at a distance from the start."""
        index, part = self._locate(distance)
        return _between(self.ele, index, part)

    def grade_at(self, distance: float) -> float:
        """Return the grade at a distance from the start."""
        return self.grades[self._locate(distance)[0]]


@dataclass(frozen=True)
class RouteChoice:
    """The route a ride is ridden on: its file name, name and GPX bytes.

    `parsed` is the route already read from those bytes, when there is one.
    """

    file: str
    name: str
    gpx: bytes
    parsed: Route | None = field(default=None, compare=False, repr=False)

    def route(self) -> Route:
        """Return the route, read from the bytes if need be."""
        return self.parsed or read_route(self.gpx, self.name)

    @property
    def route_id(self) -> str:
        """Return a name for the route that changes with its file."""
        return f"{self.file}@{len(self.gpx)}"


def _between(values: Sequence[float], index: int, part: float) -> float:
    return values[index] + (values[index + 1] - values[index]) * part


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(text: str | None, what: str) -> float:
    try:
        value = float(text or "")
    except ValueError:
        raise RouteError(f"{what} is not a number: {text!r}") from None
    if not math.isfinite(value):
        raise RouteError(f"{what} is not finite")
    return value


def _point(element: ElementTree.Element, index: int) -> GpxPoint:
    lat = _number(element.get("lat"), f"point {index + 1} latitude")
    lon = _number(element.get("lon"), f"point {index + 1} longitude")
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise RouteError(f"point {index + 1} is outside WGS84 ranges")
    ele = next((child.text for child in element if _local(child.tag) == "ele"),
               None)
    return GpxPoint(lat, lon, None if ele is None else _number(
        ele, f"point {index + 1} elevation"))


def _name(root: ElementTree.Element) -> str | None:
    for parent in ("metadata", "trk", "rte"):
        for element in root.iter():
            if _local(element.tag) != parent:
                continue
            for child in element:
                if _local(child.tag) == "name" and (child.text or "").strip():
                    return (child.text or "").strip()
    return None


def parse_gpx(data: bytes) -> Gpx:
    """Return the name and points of a GPX file, or raise RouteError."""
    if len(data) > MAX_BYTES:
        raise RouteError(f"larger than {MAX_BYTES // 1_000_000} MB")
    if any(marker in data for marker in FORBIDDEN):
        raise RouteError("has a document type declaration")
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise RouteError(f"not XML: {error}") from None
    if _local(root.tag) != "gpx":
        raise RouteError("not a GPX file")
    elements = [e for e in root.iter() if _local(e.tag) == "trkpt"] or [
        e for e in root.iter() if _local(e.tag) == "rtept"]
    points = tuple(_point(e, i) for i, e in enumerate(elements))
    if len(points) < 2:
        raise RouteError("fewer than two points")
    return Gpx(_name(root), points)


def great_circle_m(a: GpxPoint, b: GpxPoint) -> float:
    """Return the haversine distance between two points."""
    phi1, phi2 = math.radians(a.lat), math.radians(b.lat)
    dphi, dlam = phi2 - phi1, math.radians(b.lon - a.lon)
    h = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def _stations(length: float) -> list[float]:
    count = int(length // SPACING_M)
    stations = [i * SPACING_M for i in range(count + 1)]
    if length - stations[-1] > 1e-6:
        stations.append(length)
    return stations


def _resample(along: Sequence[float], values: Sequence[float],
              stations: Sequence[float]) -> list[float]:
    out, index = [], 0
    for station in stations:
        while index < len(along) - 2 and along[index + 1] < station:
            index += 1
        span = along[index + 1] - along[index]
        part = 0.0 if span == 0 else (station - along[index]) / span
        out.append(values[index] + (values[index + 1] - values[index]) * part)
    return out


def _smooth(values: Sequence[float]) -> list[float]:
    out = []
    for index in range(len(values)):
        half = min(SMOOTH_HALF_WIDTH, index, len(values) - 1 - index)
        window = values[index - half:index + half + 1]
        out.append(sum(window) / len(window))
    return out


def _grades(stations: Sequence[float], ele: Sequence[float]) -> list[float]:
    return [max(-MAX_GRADE, min(MAX_GRADE, (e2 - e1) / (s2 - s1)))
            for s1, s2, e1, e2 in zip(stations, stations[1:], ele, ele[1:])]


def build_route(name: str, points: Sequence[GpxPoint]) -> Route:
    """Return the route through points, resampled and smoothed."""
    kept = [points[0]]
    along = [0.0]
    for point in points[1:]:
        step = great_circle_m(kept[-1], point)
        if step > 0:
            kept.append(point)
            along.append(along[-1] + step)
    if along[-1] < MIN_LENGTH_M:
        raise RouteError(f"shorter than {MIN_LENGTH_M:.0f} m")
    stations = _stations(along[-1])
    has_elevation = all(p.ele is not None for p in kept)
    raw_ele = [p.ele or 0.0 for p in kept] if has_elevation else [0.0] * len(
        kept)
    ele = _smooth(_resample(along, raw_ele, stations))
    return Route(name, tuple(stations),
                 tuple(_resample(along, [p.lat for p in kept], stations)),
                 tuple(_resample(along, [p.lon for p in kept], stations)),
                 tuple(ele), tuple(_grades(stations, ele)), has_elevation)


def read_route(data: bytes, fallback_name: str) -> Route:
    """Return the route of a GPX file, named by the file if it has no name."""
    gpx = parse_gpx(data)
    return build_route(gpx.name or fallback_name, gpx.points)
