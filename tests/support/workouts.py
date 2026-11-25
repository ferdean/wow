"""The tests' own workouts in the built-in format (ICD IF-13), kept in
`testdata/workouts` so the ride tests don't depend on what the app ships."""

import json

from tests.support.timeline import TESTDATA
from wow.core.intervals_doc import parse_builtin
from wow.core.workout import Workout

THIRTY_THIRTY = "builtin:s2-30-30"
S2_SESSION = TESTDATA / "workouts" / "s2-30-30.builtin.json"


def thirty_thirty() -> Workout:
    """Return the Phase 2 S2 session, the tests' 30/30 workout."""
    return parse_builtin(json.loads(S2_SESSION.read_text(encoding="utf-8")))
