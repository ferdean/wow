"""List the workouts the rider can choose.

The workout catalog (3A, app/workout_catalog; ICD IF-08; APP-201,
APP-202, APP-208, APP-210, APP-211): today's planned workouts and the
library from intervals.icu, kept in a cache with its download time, and
the built-in workouts.
"""

import asyncio
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta, tzinfo
from enum import StrEnum
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Final

from wow.adapters.store_files import write_atomic
from wow.core.intervals_doc import WorkoutError, parse_builtin, parse_workout
from wow.core.timefmt import utc_text
from wow.core.workout import Workout
from wow.ports.clock import Clock
from wow.ports.workouts import ProviderError, WorkoutProvider

logger = logging.getLogger(__name__)

PLANNED_DAYS: Final[int] = 7
REFRESH_GAP: Final[float] = 60.0
CACHE_SCHEMA: Final[int] = 1
WORKOUT: Final[str] = "WORKOUT"
RIDE: Final[str] = "Ride"


class Source(StrEnum):
    """Where a workout comes from."""

    PLAN = "plan"
    LIBRARY = "library"
    BUILTIN = "builtin"


@dataclass(frozen=True)
class Entry:
    """A workout the rider can see; workout is None if not rideable."""

    ref: str
    source: Source
    name: str
    workout: Workout | None
    raw: bytes | None


def builtin_directory() -> Traversable:
    """Return the directory of the built-in workouts."""
    return resources.files("wow.builtin")


def builtin_entries(directory: Traversable | None = None) -> list[Entry]:
    """Load the built-in workouts with their file contents."""
    folder = directory or builtin_directory()
    entries = []
    for item in sorted(folder.iterdir(), key=lambda e: e.name):
        if not item.name.endswith(".json"):
            continue
        raw = item.read_bytes()
        try:
            workout = parse_builtin(json.loads(raw))
        except (WorkoutError, ValueError, KeyError) as error:
            logger.warning("built-in workout %s skipped: %s", item.name,
                           error)
            continue
        entries.append(Entry(workout.ref, Source.BUILTIN, workout.name,
                             workout, raw))
    return entries


def load_builtin(directory: Traversable | None = None) -> list[Workout]:
    """Load the built-in workouts."""
    return [e.workout for e in builtin_entries(directory)
            if e.workout is not None]


def entry(source: Source, item: Mapping[str, Any]) -> Entry:
    """Return the catalog entry of a downloaded event or workout."""
    ref = f"{source}:{item.get('id')}"
    name = str(item.get("name") or "Workout")
    raw = json.dumps(item, ensure_ascii=False).encode()
    doc = item.get("workout_doc")
    try:
        workout = (parse_workout(ref, name, item.get("description"), doc)
                   if isinstance(doc, Mapping) else None)
    except WorkoutError as error:
        logger.info("%s not rideable: %s", ref, error)
        workout = None
    return Entry(ref, source, name, workout, raw)


def planned_on(events: Sequence[Any], day: date) -> list[Entry]:
    """Return the planned rides of a local day."""
    wanted = day.isoformat()
    return [entry(Source.PLAN, e) for e in events
            if isinstance(e, Mapping) and e.get("category") == WORKOUT
            and e.get("type") == RIDE
            and str(e.get("start_date_local", ""))[:10] == wanted]


def rides_of(workouts: Sequence[Any]) -> list[Entry]:
    """Return the library workouts that are rides."""
    return [entry(Source.LIBRARY, w) for w in workouts
            if isinstance(w, Mapping) and w.get("type") == RIDE]


class WorkoutCatalog:
    """Planned, library and built-in workouts."""

    def __init__(self, clock: Clock, provider: WorkoutProvider | None,
                 cache: Path, builtin: Sequence[Entry],
                 on_change: Callable[[], None],
                 zone: tzinfo | None = None) -> None:
        self._clock = clock
        self._provider = provider
        self._cache = cache
        self._builtin = list(builtin)
        self._on_change = on_change
        self._zone = zone
        self._events: list[Any] = []
        self._workouts: list[Any] = []
        self._downloaded: str | None = None
        self._offline = False
        self._last_try: float | None = None
        self._task: asyncio.Task[None] | None = None
        self._read_cache()

    @property
    def builtin(self) -> list[Entry]:
        """Return the built-in workouts."""
        return list(self._builtin)

    def today(self) -> list[Entry]:
        """Return the rides planned for the local day."""
        return planned_on(self._events, self._today())

    def library(self) -> list[Entry]:
        """Return the library's rides."""
        return rides_of(self._workouts)

    def find(self, ref: str) -> Entry | None:
        """Return the entry of a reference, if listed."""
        for item in [*self.today(), *self.library(), *self._builtin]:
            if item.ref == ref:
                return item
        return None

    @property
    def offline_since(self) -> str | None:
        """Return the cache's download time while offline, else None."""
        return self._downloaded if self._offline else None

    def request_refresh(self) -> None:
        """Start a download unless one ran in the last minute."""
        now = self._clock.monotonic()
        running = self._task is not None and not self._task.done()
        recent = (self._last_try is not None
                  and now - self._last_try < REFRESH_GAP)
        if self._provider is None or running or recent:
            return
        self._last_try = now
        self._task = asyncio.get_running_loop().create_task(self.refresh())

    async def refresh(self) -> None:
        """Download the planned and library workouts, or use the cache."""
        provider = self._provider
        if provider is None:
            return
        today = self._today()
        try:
            events, workouts = await asyncio.gather(
                provider.planned(today, today + timedelta(
                    days=PLANNED_DAYS - 1)),
                provider.library())
        except ProviderError as error:
            logger.warning("workouts offline: %s", error)
            self._offline = True
            self._on_change()
            return
        self._events, self._workouts = events, workouts
        self._downloaded = utc_text(self._clock.utc())
        self._offline = False
        self._write_cache()
        self._on_change()

    async def close(self) -> None:
        """Stop a running download."""
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    def _today(self) -> date:
        return self._clock.utc().astimezone(self._zone).date()

    def _read_cache(self) -> None:
        try:
            cache = json.loads(self._cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if cache.get("schema") != CACHE_SCHEMA:
            return
        self._events = list(cache.get("events", []))
        self._workouts = list(cache.get("workouts", []))
        self._downloaded = cache.get("downloaded_utc")

    def _write_cache(self) -> None:
        write_atomic(self._cache, json.dumps({
            "schema": CACHE_SCHEMA, "downloaded_utc": self._downloaded,
            "events": self._events, "workouts": self._workouts,
        }, ensure_ascii=False).encode())
