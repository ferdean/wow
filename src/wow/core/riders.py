"""Check the riders who share the trainer.

The `[riders]` table of wow.toml (riders.md): each key is a rider's ID,
which names the rider's directory and is stamped into their rides, and
each value is the name the display shows. Without the table there is
one rider, as before.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

RIDER_ID: Final[re.Pattern[str]] = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
NAME_MAX: Final[int] = 24


class RidersError(ValueError):
    """The [riders] table can't be used."""


@dataclass(frozen=True)
class Rider:
    """A rider: the ID on disk and the name on the display."""

    rider_id: str
    name: str


def riders_of(table: object) -> tuple[Rider, ...]:
    """Return the riders of a [riders] table, in its order."""
    if not isinstance(table, Mapping):
        raise RidersError("[riders] is not a table of ID = name")
    riders = []
    names: set[str] = set()
    for rider_id, name in table.items():
        if not RIDER_ID.fullmatch(rider_id):
            raise RidersError(
                f"rider ID {rider_id!r}: 1 to 32 of a-z, 0-9 and -, "
                "starting with a letter or digit")
        if not isinstance(name, str) or not name.strip() or (
                len(name.strip()) > NAME_MAX):
            raise RidersError(
                f"rider {rider_id}: a name of 1 to {NAME_MAX} characters")
        if name.strip().casefold() in names:
            raise RidersError(f"rider {rider_id}: name {name!r} twice")
        names.add(name.strip().casefold())
        riders.append(Rider(rider_id, name.strip()))
    if not riders:
        raise RidersError("[riders] lists no rider")
    return tuple(riders)
