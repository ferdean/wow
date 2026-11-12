"""L2 harness for core state machines (test plan 2.2, ICD IF-04).

Events at their times go in; a Tick goes in whenever the machine's next
deadline comes before the next event (an event and a deadline at the same
instant: the event first). The output is every action with its time.
"""

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from wow.core.jsonform import Registry, to_json
from wow.core.machine import StateMachine

ROOT = Path(__file__).resolve().parents[2]
TESTDATA = ROOT / "testdata"
MAX_STEPS = 1_000_000


def load_json(relative: str) -> Any:
    return json.loads((TESTDATA / relative).read_text(encoding="utf-8"))


def expand(
    entries: Sequence[dict[str, Any]], key: str
) -> list[tuple[float, Any]]:
    timed = [
        (entry["at"] + k * entry.get("every", 0.0), entry[key])
        for entry in entries
        for k in range(entry.get("count", 1))
    ]
    return sorted(timed, key=lambda item: item[0])


def run[E, A](
    machine: StateMachine[E, A],
    events: Sequence[tuple[float, E]],
    until: float,
    tick: E,
) -> list[tuple[float, A]]:
    out: list[tuple[float, A]] = []
    index = 0
    for _ in range(MAX_STEPS):
        deadline = machine.next_deadline()
        upcoming = events[index][0] if index < len(events) else None
        tick_due = deadline is not None and deadline <= until and (
            upcoming is None or deadline < upcoming)
        if tick_due and deadline is not None:
            now, event = deadline, tick
        elif upcoming is not None and upcoming <= until:
            now, event = events[index]
            index += 1
        else:
            return out
        out.extend((now, action) for action in machine.handle(event, now))
    raise AssertionError("timeline did not settle")


def as_json(timed: Sequence[tuple[float, Any]]) -> list[list[Any]]:
    return [[round(now, 6), to_json(item)] for now, item in timed]


def run_case(
    directory: str,
    name: str,
    factory: Callable[[], StateMachine[Any, Any]],
    forms: Registry,
    tick: Any,
) -> tuple[list[list[Any]], list[list[Any]]]:
    case = load_json(f"{directory}/{name}.events.json")
    expected = load_json(f"{directory}/{name}.actions.json")
    events = [(at, forms.load(form))
              for at, form in expand(case["events"], "event")]
    actual = run(factory(), events, case["until"], tick)
    wanted = [[round(at, 6), form]
              for at, form in expand(expected["actions"], "action")]
    return as_json(actual), wanted


def case_names(directory: str) -> list[str]:
    folder = TESTDATA / directory
    return sorted(p.name.removesuffix(".events.json")
                  for p in folder.glob("*.events.json"))
