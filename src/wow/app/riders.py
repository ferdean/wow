"""Keep the riders who share the trainer, and the one riding now.

Rider profiles (riders.md). Without a `[riders]` table there is one
rider, whose files are the data directory's, as before. With one, each
rider has a directory under `riders/` with their own `settings.json`,
`secrets.json`, `garmin/` and workout cache. The first time, the first
rider's directory gets a copy of what the data directory held, so `main`
still finds its files there. The rider riding now is kept in
`rider.json`. A ride names its rider in `meta.json`; a ride without one
is the first rider's.
"""

import json
import logging
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from wow.adapters.store_files import write_atomic
from wow.app.config import GARMIN_DIR, SECRETS_FILE, SETTINGS_FILE
from wow.core.riders import Rider

logger = logging.getLogger(__name__)

RIDERS_DIR: Final[str] = "riders"
ACTIVE_FILE: Final[str] = "rider.json"
CACHE_FILE: Final[Path] = Path("cache") / "intervals.json"
HOME_MODE: Final[int] = 0o750
SCHEMA: Final[int] = 1
SOLO: Final[Rider] = Rider("rider", "Rider")
COPIED: Final[tuple[Path, ...]] = (Path(SETTINGS_FILE), Path(SECRETS_FILE),
                                   CACHE_FILE)

Save = Callable[[Callable[[], None]], None]


def cache_of(home: Path) -> Path:
    """Return the workout cache of a rider's directory."""
    return home / CACHE_FILE


class Riders:
    """The riders and the one riding now."""

    def __init__(self, data: Path, riders: Sequence[Rider],
                 save: Save) -> None:
        self._data = data
        self._riders = tuple(riders) or (SOLO,)
        self._save = save
        self.configured = bool(riders)
        self._active = self._read_active()

    @property
    def riders(self) -> tuple[Rider, ...]:
        """Return the riders, in the order of wow.toml."""
        return self._riders

    @property
    def active(self) -> Rider:
        """Return the rider riding now."""
        return self._active

    def home(self, rider_id: str) -> Path:
        """Return the directory of a rider's own files."""
        if not self.configured:
            return self._data
        return self._data / RIDERS_DIR / rider_id

    def find(self, rider_id: object) -> Rider | None:
        """Return the rider of an ID, if listed."""
        return next((r for r in self._riders if r.rider_id == rider_id),
                    None)

    def owner(self, meta: Mapping[str, Any]) -> str:
        """Return the ID of the rider a ride belongs to."""
        rider = meta.get("rider")
        if not self.configured or not isinstance(rider, str):
            return self._riders[0].rider_id
        return rider

    def stamp(self) -> str | None:
        """Return the rider ID a new ride records, if riders are set."""
        return self._active.rider_id if self.configured else None

    def choose(self, rider: Rider) -> None:
        """Make a rider the one riding now and keep the choice."""
        self._active = rider
        path = self._data / ACTIVE_FILE
        text = json.dumps({"schema": SCHEMA, "rider": rider.rider_id})
        self._save(lambda: write_atomic(path, text.encode()))
        logger.info("rider is now %s", rider.rider_id)

    def prepare(self) -> None:
        """Create the riders' directories, the first one from the old files.

        The copy is made aside and renamed into place, so a stop half-way
        leaves nothing that looks finished.
        """
        if not self.configured:
            return
        first = self.home(self._riders[0].rider_id)
        if not first.exists():
            self._copy_old_files(first)
        for rider in self._riders:
            self.home(rider.rider_id).mkdir(mode=HOME_MODE, parents=True,
                                            exist_ok=True)

    def _copy_old_files(self, first: Path) -> None:
        aside = first.with_name(f".{first.name}.new")
        shutil.rmtree(aside, ignore_errors=True)
        aside.mkdir(mode=HOME_MODE, parents=True)
        for name in COPIED:
            if (self._data / name).is_file():
                (aside / name).parent.mkdir(exist_ok=True)
                shutil.copy2(self._data / name, aside / name)
        if (self._data / GARMIN_DIR).is_dir():
            shutil.copytree(self._data / GARMIN_DIR, aside / GARMIN_DIR)
        aside.rename(first)
        logger.info("%s gets a copy of the files in %s", first, self._data)

    def _read_active(self) -> Rider:
        if not self.configured:
            return self._riders[0]
        try:
            raw = json.loads((self._data / ACTIVE_FILE).read_text("utf-8"))
        except (OSError, ValueError):
            return self._riders[0]
        found = self.find(raw.get("rider")) if isinstance(raw, dict) else None
        return found or self._riders[0]
