"""Read, list and delete the rides on disk.

Past rides (3A, store; ICD IF-07, IF-09; APP-610 to APP-612): the kept
rides with their `meta.json`, the FIT file's download name, and deleting
a ride, which only the rider does.
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from wow.adapters.store_files import write_atomic
from wow.core.metrics import Metrics

META: Final[str] = "meta.json"
FIT_FILE: Final[str] = "ride.fit"
FINISHED: Final[str] = "finished"
RIDE_ID: Final[re.Pattern[str]] = re.compile(r"\d{4}-\d{2}-\d{2}T\d{6}Z")
NAME_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9]+")


def ride_path(rides: Path, ride_id: str) -> Path | None:
    """Return the directory of a ride ID, if it is one and exists."""
    if not RIDE_ID.fullmatch(ride_id):
        return None
    path = rides / ride_id
    return path if path.is_dir() else None


def read_meta(ride_dir: Path) -> dict[str, Any] | None:
    """Return a ride's meta.json, if readable."""
    try:
        meta = json.loads((ride_dir / META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) else None


def write_meta(ride_dir: Path, meta: dict[str, Any]) -> None:
    """Replace a ride's meta.json."""
    write_atomic(ride_dir / META, json.dumps(meta).encode())


def kept_rides(rides: Path) -> list[dict[str, Any]]:
    """Return the meta of every finished ride, newest first."""
    if not rides.is_dir():
        return []
    kept = []
    for ride_dir in sorted(rides.iterdir(), reverse=True):
        meta = read_meta(ride_dir)
        if meta is not None and meta.get("state") == FINISHED:
            kept.append(meta)
    return kept


def delete_ride(rides: Path, ride_id: str) -> bool:
    """Delete one ride's directory; return whether it was there."""
    path = ride_path(rides, ride_id)
    if path is None:
        return False
    shutil.rmtree(path)
    return True


def fit_name(meta: dict[str, Any]) -> str:
    """Return the download name of a ride's FIT file (ICD IF-07)."""
    day = str(meta.get("ride_id", ""))[:10]
    title = NAME_CHARS.sub("-", str(meta.get("title") or "ride")).strip("-")
    return f"wow-{day}-{title or 'ride'}.fit"


def metrics_of(data: dict[str, Any]) -> Metrics:
    """Return the metrics kept in a meta.json."""
    return Metrics(
        int(data["duration"]), data.get("avg_power"), data.get("max_power"),
        data.get("np"), data.get("intensity_factor"), data.get("tss"),
        float(data.get("work_kj") or 0.0),
        tuple(data.get("time_in_zone") or ()), data.get("avg_hr_bpm"),
        data.get("max_hr_bpm"))


def utc_of(text: str) -> datetime:
    """Return the moment of a UTC text stamp."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
