"""List the routes in the data directory.

The routes a ride can be ridden on (SL-13; APP-901, APP-907): the `.gpx`
files of the data directory's `routes` folder that can be read as a
route, with their name, length and climbing. Files are read in a
thread, so a large one never stalls the event loop; one that can't be
used is left out and logged with the reason.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from wow.core.route import MAX_BYTES, RouteChoice, RouteError, read_route
from wow.core.settings import route_file

logger = logging.getLogger(__name__)

ROUTES: Final[str] = "routes"


@dataclass(frozen=True)
class RouteEntry:
    """A route the rider can choose."""

    file: str
    name: str
    length_m: float
    ascent_m: float
    gpx: bytes

    def choice(self) -> RouteChoice:
        """Return the route as a ride takes it."""
        return RouteChoice(self.file, self.name, self.gpx)


def read_entry(path: Path) -> RouteEntry:
    """Return the route of a file; raise RouteError if it can't be used."""
    if path.stat().st_size > MAX_BYTES:
        raise RouteError(f"larger than {MAX_BYTES // 1_000_000} MB")
    data = path.read_bytes()
    route = read_route(data, path.stem)
    return RouteEntry(path.name, route.name, route.length_m, route.ascent_m,
                      data)


def scan_routes(folder: Path) -> list[RouteEntry]:
    """Return the usable routes of a folder, by name."""
    if not folder.is_dir():
        return []
    entries = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or route_file(path.name) is None:
            continue
        try:
            entries.append(read_entry(path))
        except (OSError, RouteError) as error:
            logger.warning("route %s left out: %s", path.name, error)
    return sorted(entries, key=lambda e: (e.name.casefold(), e.file))


class RouteCatalog:
    """The routes of the data directory, read again on request.

    Reads may finish out of order; only the latest one started is kept.
    """

    def __init__(self, folder: Path, on_change: Callable[[], None]) -> None:
        self._folder = folder
        self._on_change = on_change
        self._tasks: set[asyncio.Task[None]] = set()
        self._started = 0
        self._kept = 0
        self.routes: tuple[RouteEntry, ...] = ()

    def request_refresh(self) -> None:
        """Start reading the folder again."""
        task = asyncio.get_running_loop().create_task(self.refresh())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def refresh(self) -> None:
        """Read the folder again."""
        self._started += 1
        mine = self._started
        routes = await asyncio.to_thread(scan_routes, self._folder)
        if mine > self._kept:
            self._kept = mine
            self.routes = tuple(routes)
            self._on_change()

    def find(self, file: str | None) -> RouteEntry | None:
        """Return the route of a file name, if it is listed."""
        return next((r for r in self.routes if r.file == file), None)

    async def close(self) -> None:
        """Wait for the reads still running."""
        await asyncio.gather(*self._tasks, return_exceptions=True)
