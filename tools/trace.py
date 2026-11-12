"""Trace requirements from the test plan to the results.

Traceability from the Phase 4 test plan's catalogues to the test
results (test plan, section 4).

Reads the catalogues of sections 5 to 8, build/pytest-cases.json (written
by tests/conftest.py) and docs/verification-log.md, writes
docs/traceability.md, and fails when:
- a test names no catalogue ID, or an ID the catalogue doesn't have;
- a test's req markers don't match the catalogue's requirements;
- a catalogue test of a finished slice is missing or isn't passing;
- any test failed.
IDs starting with S- are supporting tests outside the matrix. Tests
marked `pi` don't run in the laptop gate: they show as "due on the Pi"
until docs/verification-log.md has a line with their result.

Usage:
    uv run python tools/trace.py --through SL-01 [--note SL-01]
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
CASE: Final[re.Pattern[str]] = re.compile(r"^T-[A-Z0-9]+-\d+$")
EVIDENCE: Final[re.Pattern[str]] = re.compile(r"^(RR|D|I)-\d+$")
SUPPORTING: Final[re.Pattern[str]] = re.compile(r"^S-[A-Z0-9]+-\d+$")
REQ: Final[re.Pattern[str]] = re.compile(r"APP-\d{3}")
SLICE: Final[re.Pattern[str]] = re.compile(r"^SL-(\d+)$")


@dataclass(frozen=True)
class Item:
    """A test case or evidence item of the plan."""

    id: str
    slice: str | None
    reqs: tuple[str, ...]


@dataclass
class Plan:
    """The catalogues of the test plan."""

    tests: dict[str, Item] = field(default_factory=dict)
    evidence: dict[str, Item] = field(default_factory=dict)


@dataclass(frozen=True)
class Result:
    """The result of one test run."""

    nodeid: str
    cases: tuple[str, ...]
    reqs: tuple[str, ...]
    outcome: str
    markers: tuple[str, ...] = ()

    @property
    def on_the_pi(self) -> bool:
        """Return whether the test is due on the Pi."""
        return "pi" in self.markers and self.outcome == "not run"


def slice_number(name: str) -> int:
    """Return the number of a slice name."""
    match = SLICE.match(name)
    if match is None:
        raise ValueError(f"not a slice: {name!r}")
    return int(match.group(1))


def requirements(cell: str) -> tuple[str, ...]:
    """Return the requirement IDs of a table cell."""
    found: list[str] = []
    for part in re.split(r",\s*", cell):
        span = re.fullmatch(r"(APP-(\d{3})) to (APP-(\d{3}))", part.strip())
        if span:
            found += [f"APP-{n}" for n in range(int(span.group(2)),
                                                int(span.group(4)) + 1)]
        else:
            found += REQ.findall(part)
    return tuple(dict.fromkeys(found))


def parse_plan(text: str) -> Plan:
    """Parse the catalogues of the test plan."""
    plan = Plan()
    matrix = False
    for line in text.splitlines():
        if "matrix:start" in line:
            matrix = True
        if "matrix:end" in line:
            matrix = False
        if matrix or not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        first = cells[0]
        if CASE.match(first) and len(cells) >= 5:
            plan.tests[first] = Item(first, cells[-2],
                                     requirements(cells[-1]))
        elif EVIDENCE.match(first):
            plan.evidence[first] = Item(first, None, requirements(cells[-1]))
    return plan


def parse_report(text: str) -> list[Result]:
    """Parse the pytest case report."""
    return [Result(entry["nodeid"], tuple(entry["cases"]),
                   tuple(entry["reqs"]), entry["outcome"],
                   tuple(entry.get("markers", ())))
            for entry in json.loads(text)]


def parse_log(text: str) -> dict[str, str]:
    """Parse the verification log into results by ID."""
    results: dict[str, str] = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) >= 5 and (
                EVIDENCE.match(cells[3]) or CASE.match(cells[3])):
            results[cells[3]] = cells[4].lower()
    return results


def check(plan: Plan, results: Sequence[Result], through: str) -> list[str]:
    """Return the traceability problems up to a slice."""
    errors: list[str] = []
    by_case: dict[str, list[Result]] = defaultdict(list)
    for result in results:
        if not result.cases:
            errors.append(f"{result.nodeid}: no case marker")
        for case in result.cases:
            if CASE.match(case) and case in plan.tests:
                by_case[case].append(result)
            elif not SUPPORTING.match(case):
                errors.append(f"{result.nodeid}: {case} is not in the plan")
        if result.outcome == "failed":
            errors.append(f"{result.nodeid}: failed")
    for case, tests in sorted(by_case.items()):
        wanted = set(plan.tests[case].reqs)
        claimed = {req for test in tests for req in test.reqs}
        if claimed - wanted:
            errors.append(f"{case}: tests claim {sorted(claimed - wanted)}, "
                          "which the catalogue doesn't list")
        if wanted - claimed:
            errors.append(f"{case}: no test claims {sorted(wanted - claimed)}")
    limit = slice_number(through)
    for case, item in sorted(plan.tests.items()):
        if item.slice is None or slice_number(item.slice) > limit:
            continue
        tests = by_case.get(case, [])
        if not tests:
            errors.append(f"{case} ({item.slice}): not implemented")
        for test in tests:
            if test.outcome != "passed" and not test.on_the_pi:
                errors.append(f"{case}: {test.nodeid} {test.outcome}")
    return errors


def case_status(case: str, item: Item, results: Sequence[Result],
                through: str, log: dict[str, str] | None = None) -> str:
    """Return the status of a test case."""
    mine = [r for r in results if case in r.cases]
    if mine and all(r.on_the_pi for r in mine):
        logged = (log or {}).get(case)
        return {"pass": "passed on the Pi", "fail": "failed"}.get(
            logged or "", "due on the Pi")
    outcomes = {r.outcome for r in mine if not r.on_the_pi}
    if not outcomes:
        due = item.slice is not None and slice_number(
            item.slice) <= slice_number(through)
        return "not implemented" if due else f"due {item.slice}"
    for outcome in ("failed", "skipped", "not run"):
        if outcome in outcomes:
            return outcome
    return "passed"


def requirement_rows(
    plan: Plan, results: Sequence[Result], log: dict[str, str], through: str
) -> list[tuple[str, str, str, str]]:
    """Return the status row of each requirement."""
    tests: dict[str, list[str]] = defaultdict(list)
    evidence: dict[str, list[str]] = defaultdict(list)
    verdicts: dict[str, set[str]] = defaultdict(set)
    for case, item in sorted(plan.tests.items()):
        status = case_status(case, item, results, through, log)
        for req in item.reqs:
            tests[req].append(f"{case} {status}")
            verdicts[req].add(status)
    for key, item in sorted(plan.evidence.items()):
        for req in item.reqs:
            evidence[req].append(f"{key} {log.get(key, 'pending')}")
    rows = []
    for req in sorted(set(tests) | set(evidence)):
        rows.append((req, ", ".join(tests[req]) or "—",
                     ", ".join(evidence[req]) or "—",
                     automated_verdict(verdicts[req])))
    return rows


def automated_verdict(statuses: set[str]) -> str:
    """Return the verdict of a set of statuses."""
    if not statuses:
        return "no automated test"
    if statuses & {"failed", "not implemented", "skipped", "not run"}:
        return "open"
    if statuses <= {"passed", "passed on the Pi"}:
        return "passed"
    return "passed so far" if "passed" in statuses else "not yet due"


def markdown(rows: Iterable[tuple[str, str, str, str]], title: str) -> str:
    """Return rows as a Markdown table."""
    lines = [title, "",
             "| Req. | Automated tests | Ride checks, demonstrations, "
             "inspections | Automated part |",
             "|---|---|---|---|"]
    lines += [f"| {req} | {tests} | {evidence} | {verdict} |"
              for req, tests, evidence, verdict in rows]
    return "\n".join(lines) + "\n"


def slice_rows(plan: Plan, rows: Sequence[tuple[str, str, str, str]],
               name: str) -> list[tuple[str, str, str, str]]:
    """Return the rows of one slice."""
    reqs = {req for item in plan.tests.values() if item.slice == name
            for req in item.reqs}
    return [row for row in rows if row[0] in reqs]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the traceability report from the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--through", required=True)
    parser.add_argument("--plan", type=Path,
                        default=ROOT / "docs" / "phase4-test-plan.md")
    parser.add_argument("--report", type=Path,
                        default=ROOT / "build" / "pytest-cases.json")
    parser.add_argument("--log", type=Path,
                        default=ROOT / "docs" / "verification-log.md")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "docs" / "traceability.md")
    parser.add_argument("--note")
    args = parser.parse_args(argv)
    if not args.plan.exists():
        print(f"TRACE: {args.plan} missing: put the approved Phase 4 test "
              "plan (Markdown) there")
        return 1
    plan = parse_plan(args.plan.read_text(encoding="utf-8"))
    results = parse_report(args.report.read_text(encoding="utf-8"))
    log = parse_log(args.log.read_text(encoding="utf-8")
                    if args.log.exists() else "")
    rows = requirement_rows(plan, results, log, args.through)
    args.out.write_text(markdown(
        rows, f"# Traceability (generated; finished slices through "
              f"{args.through})"), encoding="utf-8")
    if args.note:
        print(markdown(slice_rows(plan, rows, args.note),
                       f"## Traceability note {args.note}"))
    errors = check(plan, results, args.through)
    for error in errors:
        print(f"TRACE: {error}")
    print(f"trace: {len(plan.tests)} catalogue tests, {len(results)} pytest "
          f"tests, {len(errors)} problems")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
