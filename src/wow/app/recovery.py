"""Find a ride the app was riding when it stopped.

Crash recovery (3A, app/recovery; ICD 4.9.4; APP-809): at start the ride
directory whose `meta.json` still says `running` is read back: its
journal, its samples, its workout and its route (APP-908). A ride that
never got its first power is closed as cancelled; any other is offered
on Home, to continue with the outage as a dropout or to finish.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from wow.adapters.store_files import write_atomic
from wow.app.recorder import JOURNAL, SAMPLES
from wow.app.ride_controller import (
    DEFAULT_RIDER_KG, META, ROUTE_FILE, WORKOUT, Resumption, RideSetup,
)
from wow.app.workout_catalog import Source, entry
from wow.core.intervals_doc import WorkoutError, parse_builtin
from wow.core.replay import Record, record_mono
from wow.core.route import RouteChoice
from wow.core.vocab import Mode, UploadState
from wow.core.workout import Workout, free_ride_workout

logger = logging.getLogger(__name__)

RUNNING: Final[str] = "running"
CANCELLED: Final[str] = "cancelled"


@dataclass(frozen=True)
class Interrupted:
    """A ride the app stopped in the middle of."""

    ride_dir: Path
    meta: dict[str, Any]
    records: list[Record]
    samples: list[Record]
    setup: RideSetup
    crash_mono: float
    crash_utc: datetime
    boot_id: str

    @property
    def ride_id(self) -> str:
        """Return the ride's ID."""
        return str(self.meta["ride_id"])

    @property
    def started(self) -> bool:
        """Return whether the ride got its first power."""
        return any(r.get("type") == "ride_started" for r in self.records)


def read_lines(path: Path) -> list[Record]:
    """Return the complete JSON lines of a file; a torn last one is out."""
    if not path.exists():
        return []
    lines = []
    for line in path.read_text(encoding="utf-8").split("\n")[:-1]:
        try:
            lines.append(json.loads(line))
        except ValueError:
            logger.warning("%s: unreadable line dropped", path)
    return lines


def find_interrupted(rides: Path) -> Interrupted | None:
    """Return the newest ride still marked running, if any."""
    if not rides.is_dir():
        return None
    for ride_dir in sorted(rides.iterdir(), reverse=True):
        meta = _meta(ride_dir)
        if meta is None or meta.get("state") != RUNNING:
            continue
        found = _read(ride_dir, meta)
        if found is not None:
            return found
    return None


def close_cancelled(found: Interrupted) -> None:
    """Close a ride that was still waiting for its first power."""
    write_atomic(found.ride_dir / META,
                 json.dumps({**found.meta, "state": CANCELLED}).encode())


def outage(found: Interrupted, now_mono: float, now_utc: datetime,
           boot_id: str, synchronised: bool) -> float | None:
    """Return how long the app was gone, if it can be known."""
    if found.boot_id == boot_id:
        return max(0.0, now_mono - found.crash_mono)
    if synchronised:
        return max(0.0, (now_utc - found.crash_utc).total_seconds())
    return None


def _meta(ride_dir: Path) -> dict[str, Any] | None:
    try:
        meta = json.loads((ride_dir / META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def _read(ride_dir: Path, meta: dict[str, Any]) -> Interrupted | None:
    records = read_lines(ride_dir / JOURNAL)
    armed = next((r for r in records if r.get("type") == "armed"), None)
    workout = _workout(ride_dir, meta)
    if armed is None or workout is None or "capabilities" not in armed:
        logger.warning("%s: can't be recovered", ride_dir.name)
        return None
    samples = read_lines(ride_dir / SAMPLES)
    last = records[-1]
    crash_utc = _utc(str(last["utc"]))
    if samples:
        crash_utc = max(crash_utc, _utc(str(samples[-1]["utc"])))
    crash_mono = record_mono(last) + (
        crash_utc - _utc(str(last["utc"]))).total_seconds()
    setup = RideSetup(
        workout, int(meta["ftp"]), float(armed["lead_time"]),
        source=str(meta.get("source", Source.BUILTIN)),
        zones_pct=tuple(meta.get("zones_pct") or ()) or RideSetup.zones_pct,
        free_ride_level_pct=int(armed.get("free_ride_level_pct", 0)),
        upload_on=meta.get("upload") != UploadState.OFF,
        block_modes=tuple(Mode(m) for m in armed.get("block_modes", [])),
        route=_route(ride_dir, meta),
        rider_kg=int(meta.get("rider_kg", DEFAULT_RIDER_KG)))
    return Interrupted(ride_dir, meta, records, samples, setup, crash_mono,
                       crash_utc, str(last.get("boot_id", "")))


def _workout(ride_dir: Path, meta: dict[str, Any]) -> Workout | None:
    source = meta.get("source")
    if source == Source.FREE_RIDE:
        return free_ride_workout()
    try:
        raw = json.loads((ride_dir / WORKOUT).read_bytes())
        if source == Source.BUILTIN:
            return parse_builtin(raw)
        return entry(Source(str(source)), raw).workout
    except (OSError, ValueError, KeyError, WorkoutError) as error:
        logger.warning("%s: workout unreadable: %s", ride_dir.name, error)
        return None


def _route(ride_dir: Path, meta: dict[str, Any]) -> RouteChoice | None:
    route = meta.get("route")
    if not isinstance(route, dict):
        return None
    try:
        gpx = (ride_dir / ROUTE_FILE).read_bytes()
    except OSError as error:
        logger.warning("%s: route unreadable: %s", ride_dir.name, error)
        return None
    return RouteChoice(str(route.get("file")), str(route.get("name")), gpx)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def resumption(found: Interrupted, now_mono: float, gone: float | None,
               keep_riding: bool) -> Resumption:
    """Return how the ride controller takes the ride up again.

    Continuing puts the crash an outage before now, so the step position
    is that of a ride that never stopped; finishing puts it at now.
    """
    shift = now_mono - found.crash_mono - (
        gone if keep_riding and gone is not None else 0.0)
    return Resumption(found.ride_dir, found.meta, found.records,
                      found.samples, found.setup, found.crash_mono, shift,
                      gone)
