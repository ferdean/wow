"""Writes build/pytest-cases.json: each test's catalogue IDs, requirements
and outcome, for tools/trace.py (test plan, section 4)."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "build" / "pytest-cases.json"

_TESTS: dict[str, dict[str, object]] = {}


def _ids(item: pytest.Item, name: str) -> list[str]:
    return [str(arg) for mark in item.iter_markers(name) for arg in mark.args]


def pytest_configure(config: pytest.Config) -> None:
    _TESTS.clear()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    for item in items:
        _TESTS[item.nodeid] = {
            "nodeid": item.nodeid,
            "cases": _ids(item, "case"),
            "reqs": _ids(item, "req"),
            "markers": sorted({m.name for m in item.iter_markers()}),
            "outcome": "not run",
        }


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    entry = _TESTS.get(report.nodeid)
    if entry is None:
        return
    if report.failed:
        entry["outcome"] = "failed"
    elif report.skipped and entry["outcome"] != "failed":
        entry["outcome"] = "skipped"
    elif report.when == "call" and report.passed:
        entry["outcome"] = "passed"


def pytest_sessionfinish(session: pytest.Session) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    tests = sorted(_TESTS.values(), key=lambda t: str(t["nodeid"]))
    REPORT.write_text(json.dumps(tests, indent=1), encoding="utf-8")
