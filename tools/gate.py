"""Run the slice gate on the laptop.

The slice gate on the laptop (test plan, section 4): pytest without the
slow and pi tests (T-TOOL-01 to T-TOOL-04 run inside it, with the
display's svelte-check, ESLint, tsc and npm ci), the coverage floors of
section 2.5, Vitest, then tools/trace.py.

Usage:
    uv run python tools/gate.py --through SL-01
"""

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
COVERAGE: Final[Path] = ROOT / "build" / "coverage.json"
DISPLAY: Final[Path] = ROOT / "display"


@dataclass(frozen=True)
class Floor:
    """Coverage floor of a group of files."""

    name: str
    prefixes: tuple[str, ...]
    kind: str
    percent: float


FLOORS: Final[tuple[Floor, ...]] = (
    Floor("core", ("src/wow/core/",), "branch", 95.0),
    Floor("app and web", ("src/wow/app/", "src/wow/web/"), "line", 85.0),
    Floor("testable adapters", (
        "src/wow/adapters/ble_sim/", "src/wow/adapters/ble_replay",
        "src/wow/adapters/ble_log", "src/wow/adapters/store_files",
        "src/wow/adapters/fit_garmin", "src/wow/adapters/intervals_icu",
        "src/wow/adapters/clock_stepped"), "line", 85.0),
)


def coverage_problems(files: Mapping[str, Mapping[str, object]]) -> list[str]:
    """Return the groups below their coverage floor."""
    problems: list[str] = []
    for floor in FLOORS:
        covered = total = 0
        for path, entry in files.items():
            if not path.replace("\\", "/").startswith(floor.prefixes):
                continue
            summary = entry["summary"]
            assert isinstance(summary, dict)
            if floor.kind == "branch":
                covered += summary["covered_branches"]
                total += summary["num_branches"]
            else:
                covered += summary["covered_lines"]
                total += summary["num_statements"]
        percent = 100.0 if total == 0 else 100.0 * covered / total
        verdict = "ok" if percent >= floor.percent else "BELOW FLOOR"
        print(f"coverage {floor.name}: {percent:.1f} % {floor.kind} "
              f"(floor {floor.percent:.0f} %) {verdict}")
        if percent < floor.percent:
            problems.append(f"{floor.name} below its floor")
    return problems


def run(command: Sequence[str], cwd: Path = ROOT) -> int:
    """Run a command; return its exit code."""
    print("$", " ".join(command), flush=True)
    return subprocess.run(command, cwd=cwd).returncode


def vitest() -> int:
    """Run the display tests; return the exit code."""
    npm = shutil.which("npm")
    if npm is None:
        print("npm is not on the PATH")
        return 1
    return run([npm, "test"], cwd=DISPLAY)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the gate from the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--through", required=True)
    parser.add_argument("--plan", type=Path,
                        default=ROOT / "docs" / "phase4-test-plan.md")
    args = parser.parse_args(argv)
    failures: list[str] = []
    if run([sys.executable, "-m", "pytest", "-m", "not slow and not pi",
            "--cov=wow", "--cov-report=term:skip-covered",
            f"--cov-report=json:{COVERAGE}"]) != 0:
        failures.append("pytest")
    if COVERAGE.exists():
        files = json.loads(COVERAGE.read_text(encoding="utf-8"))["files"]
        failures += coverage_problems(files)
    else:
        failures.append("no coverage report")
    if vitest() != 0:
        failures.append("vitest")
    if run([sys.executable, str(ROOT / "tools" / "trace.py"), "--through",
            args.through, "--note", args.through, "--plan",
            str(args.plan)]) != 0:
        failures.append("trace")
    print("GATE " + ("PASSED" if not failures else
                     "FAILED: " + ", ".join(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
