"""List the workouts the rider can choose.

The workouts the rider can choose (3A, app/workout_catalog).

Slice SL-02: the built-in workouts that SL-02's parser can read. Today's
plan, the library and the cache follow in SL-04.
"""

import json
import logging
from importlib import resources
from importlib.resources.abc import Traversable

from wow.core.intervals_doc import WorkoutError, parse_builtin
from wow.core.workout import Workout

logger = logging.getLogger(__name__)


def builtin_directory() -> Traversable:
    """Return the directory of the built-in workouts."""
    return resources.files("wow.builtin")


def load_builtin(directory: Traversable | None = None) -> list[Workout]:
    """Load the built-in workouts."""
    folder = directory or builtin_directory()
    workouts = []
    for entry in sorted(folder.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".json"):
            continue
        try:
            workouts.append(parse_builtin(json.loads(entry.read_text(
                encoding="utf-8"))))
        except (WorkoutError, ValueError, KeyError) as error:
            logger.warning("built-in workout %s skipped: %s", entry.name,
                           error)
    return workouts
