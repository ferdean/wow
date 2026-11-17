"""The suite runs without Bluetooth (T-SIM-04)."""

import re
from pathlib import Path

import pytest

from tests import conftest
from tests.support.app_rig import AppSession
from tools import trace
from wow.app import main

ROOT = Path(__file__).resolve().parents[2]
ROW = re.compile(r"^\| (APP-\d{3}) \| \w+ \| ([^|]+) \| ([^|]+) \|")
CASE = re.compile(r"T-[A-Z0-9]+-\d+")


def matrix_rows() -> list[tuple[str, str, tuple[str, ...]]]:
    text = (ROOT / "docs" / "phase4-test-plan.md").read_text("utf-8")
    inside = text.split("<!-- matrix:start -->")[1].split(
        "<!-- matrix:end -->")[0]
    rows = []
    for line in inside.splitlines():
        found = ROW.match(line)
        if found:
            cell = found.group(3)
            spans = re.findall(r"(T-[A-Z0-9]+-)(\d+) to T-[A-Z0-9]+-(\d+)",
                               cell)
            cases = set(CASE.findall(cell))
            for prefix, low, high in spans:
                numbers = range(int(low), int(high) + 1)
                cases |= {f"{prefix}{n:02d}" for n in numbers}
            rows.append((found.group(1), found.group(2), tuple(cases)))
    return rows


@pytest.mark.case("T-SIM-04")
@pytest.mark.req("APP-819")
def test_every_requirement_verified_by_test_has_a_test_without_hardware(
        ) -> None:
    rows = matrix_rows()
    assert len(rows) == 126
    collected = {str(case) for entry in conftest._TESTS.values()
                 for case in entry["cases"]}  # type: ignore[attr-defined]
    if "T-COD-01" not in collected:
        pytest.skip("needs the whole suite collected")
    plan = trace.parse_plan(
        (ROOT / "docs" / "phase4-test-plan.md").read_text("utf-8"))
    missing = [req for req, methods, cases in rows if "T" in methods
               and not any(c in collected and c in plan.tests
                           for c in cases)]
    assert missing == []
    sources = "\n".join(p.read_text("utf-8")
                        for p in (ROOT / "tests").rglob("*.py")
                        if p.name not in ("test_tooling.py",
                                          "test_hardware_free.py"))
    assert "BleakConnector" not in sources
    assert "ble_bleak" not in sources


@pytest.mark.case("T-SIM-04")
@pytest.mark.req("APP-819")
@pytest.mark.asyncio
async def test_the_simulated_app_never_reaches_for_bluetooth(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_bluetooth(*_args: object) -> None:
        raise AssertionError("BlueZ used with simulate = true")

    monkeypatch.setattr(main, "BleakConnector", no_bluetooth)
    session = AppSession(tmp_path)
    await session.begin("builtin:erg-check")
    await session.until(30.0)
    assert session.command("finish") is None
    ride = await session.close()
    assert (ride / "ride.fit").exists()
