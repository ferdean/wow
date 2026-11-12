import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from tools import import_spike_log, trace
from wow.adapters.ble_log import record_line

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "wow"
DISPLAY = ROOT / "display"
DISPLAY_FILES = ("package.json", "package-lock.json", ".npmrc")
PLAN = ROOT / "docs" / "phase4-test-plan.md"

NOT_IN_CORE = {
    "asyncio", "time", "os", "pathlib", "io", "shutil", "tempfile",
    "socket", "threading", "logging", "subprocess", "bleak", "aiohttp",
    "dbus_fast", "wow.app", "wow.adapters", "wow.ports", "wow.web",
}
HTTP_CLIENTS = {"http.client", "urllib.request", "requests", "httpx",
                "aiohttp.client"}


def run(*command: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True)


def npm() -> str:
    found = shutil.which("npm")
    assert found, "npm is not on the PATH: the display checks need Node.js"
    version = run("node", "--version").stdout.strip().lstrip("v")
    major, minor = (int(part) for part in version.split(".")[:2])
    assert (major, minor) >= (22, 12), f"Node.js {version}: need >= 22.12"
    return found


@pytest.mark.case("T-TOOL-01")
@pytest.mark.req("APP-823")
def test_flake8_and_strict_mypy_find_nothing() -> None:
    flake8 = run(sys.executable, "-m", "flake8", "src", "tools", "tests")
    assert flake8.returncode == 0, flake8.stdout
    mypy = run(sys.executable, "-m", "mypy")
    assert mypy.returncode == 0, mypy.stdout


@pytest.mark.case("T-TOOL-01")
@pytest.mark.req("APP-823")
@pytest.mark.parametrize("script", ["check", "lint", "typecheck"])
def test_svelte_check_eslint_and_tsc_find_nothing(script: str) -> None:
    assert (DISPLAY / "node_modules").is_dir(), (
        "run `npm ci` in display/ first")
    result = run(npm(), "run", "--silent", script, cwd=DISPLAY)
    assert result.returncode == 0, result.stdout + result.stderr


def modules(path: Path) -> Iterator[tuple[str, ast.AST]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, node
            for alias in node.names:
                yield f"{node.module}.{alias.name}", node


def under(name: str, roots: set[str]) -> bool:
    return any(name == root or name.startswith(root + ".") for root in roots)


def import_problems(src: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(src.rglob("*.py")):
        relative = path.relative_to(src).as_posix()
        names = {name for name, _ in modules(path)}
        if under_any(names, {"bleak"}) and relative != "adapters/ble_bleak.py":
            problems.append(f"{relative} imports bleak")
        if (under_any(names, {"dbus_fast"})
                and relative != "adapters/bluez_stale.py"):
            problems.append(f"{relative} imports dbus_fast")
        if (under_any(names, HTTP_CLIENTS) or "ClientSession" in
                path.read_text(encoding="utf-8")) and (
                relative != "adapters/intervals_icu.py"):
            problems.append(f"{relative} uses an HTTP client")
        if relative.startswith("core/"):
            problems += [f"{relative} imports {name}" for name in sorted(names)
                         if under(name, NOT_IN_CORE)]
            problems += core_calls(path, relative)
    return problems


def under_any(names: set[str], roots: set[str]) -> bool:
    return any(under(name, roots) for name in names)


def core_calls(path: Path, relative: str) -> list[str]:
    problems = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name) and node.id == "open":
            problems.append(f"{relative} opens a file")
        if isinstance(node, ast.Attribute) and node.attr in (
                "now", "utcnow", "today", "monotonic", "time"):
            problems.append(f"{relative} reads a clock ({node.attr})")
    return problems


@pytest.mark.case("T-TOOL-02")
@pytest.mark.req("APP-818", "APP-819")
def test_imports_keep_the_layers_apart() -> None:
    assert import_problems(SRC) == []


@pytest.mark.case("T-TOOL-02")
@pytest.mark.req("APP-818", "APP-819")
def test_import_check_catches_violations(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "bad.py").write_text(
        "import asyncio\nfrom datetime import datetime\n"
        "x = datetime.now()\nopen('f')\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "net.py").write_text(
        "import urllib.request\nimport bleak\nfrom dbus_fast import Message\n")
    problems = import_problems(tmp_path)
    assert "core/bad.py imports asyncio" in problems
    assert "core/bad.py reads a clock (now)" in problems
    assert "core/bad.py opens a file" in problems
    assert {"app/net.py imports bleak", "app/net.py imports dbus_fast",
            "app/net.py uses an HTTP client"} <= set(problems)


SYNTHETIC_PLAN = """
| ID | Test | Pass criterion | Slice | Req. |
|----|------|----------------|-------|------|
| T-AAA-01 | one | ok | SL-01 | APP-101 |
| T-AAA-02 | two | ok | SL-01 | APP-102, APP-103 |
| T-BBB-01 | later | ok | SL-03 | APP-104 to APP-106 |
| S-DSP-01 | supporting | ok | SL-02 |
| RR-01 | ride check | APP-101 |
| D-01 | step | expected | APP-102 |
| I-01 | inspection | APP-104 |
<!-- matrix:start -->
| T-ZZZ-99 | inside the matrix | x | SL-01 | APP-999 |
<!-- matrix:end -->
"""


def result(nodeid: str, cases: tuple[str, ...], reqs: tuple[str, ...],
           outcome: str = "passed") -> trace.Result:
    return trace.Result(nodeid, cases, reqs, outcome)


@pytest.mark.case("T-TOOL-03")
@pytest.mark.req("APP-819")
def test_trace_parses_the_catalogues() -> None:
    plan = trace.parse_plan(SYNTHETIC_PLAN)
    assert set(plan.tests) == {"T-AAA-01", "T-AAA-02", "T-BBB-01"}
    assert plan.tests["T-BBB-01"] == trace.Item(
        "T-BBB-01", "SL-03", ("APP-104", "APP-105", "APP-106"))
    assert set(plan.evidence) == {"RR-01", "D-01", "I-01"}
    if PLAN.exists():
        text = PLAN.read_text(encoding="utf-8")
        counts = re.search(r"(\d+) automated tests, (\d+) ride checks, "
                           r"(\d+) demonstration steps, (\d+) inspections",
                           text)
        assert counts is not None
        real = trace.parse_plan(text)
        assert len(real.tests) == int(counts.group(1))
        assert len(real.evidence) == sum(int(counts.group(n))
                                         for n in (2, 3, 4))


@pytest.mark.case("T-TOOL-03")
@pytest.mark.req("APP-819")
def test_trace_passes_a_finished_slice_and_reports_gaps() -> None:
    plan = trace.parse_plan(SYNTHETIC_PLAN)
    good = [result("a", ("T-AAA-01",), ("APP-101",)),
            result("b", ("T-AAA-02",), ("APP-102", "APP-103")),
            result("c", ("S-INF-01",), ())]
    assert trace.check(plan, good, "SL-01") == []
    assert trace.check(plan, good, "SL-03") == [
        "T-BBB-01 (SL-03): not implemented"]
    bad = [result("a", ("T-AAA-01",), ("APP-101",), "skipped"),
           result("b", ("T-AAA-02",), ("APP-102", "APP-999")),
           result("x", (), ()),
           result("y", ("T-NEW-01",), (), "failed")]
    assert trace.check(plan, bad, "SL-01") == [
        "x: no case marker",
        "y: T-NEW-01 is not in the plan",
        "y: failed",
        "T-AAA-02: tests claim ['APP-999'], which the catalogue doesn't list",
        "T-AAA-02: no test claims ['APP-103']",
        "T-AAA-01: a skipped",
    ]


@pytest.mark.case("T-TOOL-03")
@pytest.mark.req("APP-819")
def test_trace_writes_the_requirement_table(tmp_path: Path) -> None:
    plan_file = tmp_path / "plan.md"
    plan_file.write_text(SYNTHETIC_PLAN)
    report = tmp_path / "report.json"
    report.write_text(
        '[{"nodeid": "a", "cases": ["T-AAA-01"], "reqs": ["APP-101"], '
        '"outcome": "passed"}, {"nodeid": "b", "cases": ["T-AAA-02"], '
        '"reqs": ["APP-102", "APP-103"], "outcome": "passed"}]')
    log = tmp_path / "log.md"
    log.write_text("| Date | Version | Ride | Item | Result | Evidence |\n"
                   "| 2026-11-12 | 0.1.0 | — | D-01 | pass | photo |\n")
    out = tmp_path / "traceability.md"
    code = trace.main(["--through", "SL-01", "--plan", str(plan_file),
                       "--report", str(report), "--log", str(log),
                       "--out", str(out), "--note", "SL-01"])
    assert code == 0
    table = out.read_text()
    assert "| APP-101 | T-AAA-01 passed | RR-01 pending | passed |" in table
    assert "| APP-102 | T-AAA-02 passed | D-01 pass | passed |" in table
    assert "| APP-104 | T-BBB-01 due SL-03 | I-01 pending | not yet due |" in (
        table)
    assert trace.automated_verdict({"passed", "due SL-03"}) == (
        "passed so far")
    assert trace.automated_verdict(set()) == "no automated test"
    assert trace.automated_verdict({"failed"}) == "open"
    with pytest.raises(ValueError):
        trace.slice_number("SL-x")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.case("T-TOOL-04")
@pytest.mark.req("APP-822")
def test_frozen_install_from_a_clean_copy(tmp_path: Path) -> None:
    uv = os.environ.get("UV") or shutil.which("uv")
    assert uv, "uv is not on the PATH"
    before = sha(ROOT / "uv.lock")
    check = run(uv, "lock", "--check", "--offline")
    assert check.returncode == 0, check.stderr
    clean = tmp_path / "clone"
    clean.mkdir()
    for name in ("pyproject.toml", "uv.lock", "README.md", ".python-version"):
        shutil.copy2(ROOT / name, clean / name)
    shutil.copytree(ROOT / "src", clean / "src")
    sync = run(uv, "sync", "--frozen", "--offline", "--dry-run", cwd=clean)
    assert sync.returncode == 0, sync.stderr
    assert sha(clean / "uv.lock") == sha(ROOT / "uv.lock") == before


def unpinned(package: dict[str, dict[str, str]]) -> list[str]:
    return [f"{name} {version}" for group in ("dependencies",
                                              "devDependencies")
            for name, version in package.get(group, {}).items()
            if not re.fullmatch(r"\d+\.\d+\.\d+", version)]


@pytest.mark.case("T-TOOL-04")
@pytest.mark.req("APP-822")
def test_npm_ci_from_a_clean_copy(tmp_path: Path) -> None:
    package = json.loads((DISPLAY / "package.json").read_text("utf-8"))
    assert unpinned(package) == []
    assert unpinned({"devDependencies": {"a": "^1.2.3"}}) == ["a ^1.2.3"]
    before = sha(DISPLAY / "package-lock.json")
    clean = tmp_path / "display"
    clean.mkdir()
    for name in DISPLAY_FILES:
        shutil.copy2(DISPLAY / name, clean / name)
    install = run(npm(), "ci", "--prefer-offline", "--ignore-scripts",
                  "--no-audit", "--no-fund", cwd=clean)
    assert install.returncode == 0, install.stderr
    assert sha(clean / "package-lock.json") == before


SPIKE_LOG = [
    '{"utc": "2026-11-04T21:46:02.000Z", "mono_ms": 1000, "kind": "event", '
    '"name": "connected", "device": "trainer"}',
    '{"utc": "2026-11-04T21:46:02.100Z", "mono_ms": 1100, "kind": "read", '
    '"device": "trainer", "uuid": "2acc", "hex": "014000000ca00000"}',
    '{"utc": "2026-11-04T21:46:02.200Z", "mono_ms": 1200, "kind": "tx", '
    '"device": "trainer", "uuid": "2ad9", "hex": "00"}',
    '{"utc": "2026-11-04T21:46:02.400Z", "mono_ms": 1400, "kind": "rx", '
    '"device": "trainer", "uuid": "2ad9", "hex": "800001"}',
    '{"utc": "2026-11-04T21:46:02.500Z", "mono_ms": 1500, "kind": "rx", '
    '"device": "hrm", "uuid": "2a37", "hex": "10489a03"}',
    '{"utc": "2026-11-04T21:46:02.600Z", "mono_ms": 1600, "kind": "event", '
    '"name": "decode_failed", "device": "trainer"}',
    '{"utc": "2026-11-04T21:46:02.700Z", "mono_ms": 1700, "kind": "event", '
    '"name": "connected", "device": "trainer"}',
    '{"utc": "2026-11-04T21:46:02.800Z", "mono_ms": 1800, "kind": "rx", '
    '"device": "trainer", "uuid": "2ad2", "hex": "40002c0bc800"}',
    '{"utc": "2026-11-04T21:46:02.900Z", "mono_ms": 1900, "kind": "status",'
    ' "device": "trainer"}',
    '{"utc": "2026-11-04T21:46:03.000Z", "mono_ms": 2000, "kind": "event", '
    '"name": "start"}',
    '',
]


@pytest.mark.case("S-INF-04")
def test_spike_logs_convert_to_the_bluetooth_log_format(
    tmp_path: Path,
) -> None:
    records, skipped = import_spike_log.convert(
        SPIKE_LOG, {"trainer": "94:05:BB:03:5D:9D",
                    "hrm": "E0:E2:EF:63:14:BC"})
    assert [(r.dev, r.gen, r.op, r.uuid and r.uuid[4:8], r.hex)
            for r in records] == [
        ("trainer", 1, "connected", None, None),
        ("trainer", 1, "read", "2acc", "014000000ca00000"),
        ("trainer", 1, "write", "2ad9", "00"),
        ("trainer", 1, "indicate", "2ad9", "800001"),
        ("hrm", 1, "notify", "2a37", "10489a03"),
        ("trainer", 2, "connected", None, None),
        ("trainer", 2, "notify", "2ad2", "40002c0bc800"),
    ]
    assert skipped == {"event:decode_failed": 1, "status": 1, "event:start": 1}
    source = tmp_path / "spike.jsonl"
    source.write_text("\n".join(SPIKE_LOG))
    out = tmp_path / "ble" / "converted.jsonl"
    assert import_spike_log.main([str(source), str(out)]) == 0
    assert out.read_text().splitlines()[1] == record_line(records[1])
    assert import_spike_log.full_uuid(
        "00002AD2-0000-1000-8000-00805F9B34FB") == (
        "00002ad2-0000-1000-8000-00805f9b34fb")


@pytest.mark.case("T-TOOL-03")
@pytest.mark.req("APP-819")
def test_trace_counts_pi_tests_from_the_verification_log() -> None:
    plan = trace.parse_plan(SYNTHETIC_PLAN)
    results = [trace.Result("a", ("T-AAA-01",), ("APP-101",), "not run",
                            ("pi", "slow")),
               result("b", ("T-AAA-02",), ("APP-102", "APP-103"))]
    assert trace.check(plan, results, "SL-01") == []
    item = plan.tests["T-AAA-01"]
    assert trace.case_status("T-AAA-01", item, results, "SL-01") == (
        "due on the Pi")
    assert trace.case_status("T-AAA-01", item, results, "SL-01",
                             {"T-AAA-01": "pass"}) == "passed on the Pi"
    assert trace.parse_log(
        "| 2026-11-12 | 0.2.0 | — | T-AAA-01 | pass | log | |") == {
        "T-AAA-01": "pass"}
    rows = trace.requirement_rows(plan, results, {"T-AAA-01": "pass"},
                                  "SL-01")
    assert rows[0] == ("APP-101", "T-AAA-01 passed on the Pi",
                       "RR-01 pending", "passed")
