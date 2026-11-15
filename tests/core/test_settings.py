"""Settings against table S (L1, T-SET-02 to T-SET-05)."""

from typing import Any

import pytest

from wow.core.settings import (
    DeviceRef, Rejected, SettingKey, Settings, settings_json, settings_of,
    with_value,
)


def accepted(key: str, values: list[Any]) -> list[Any]:
    found = []
    for value in values:
        result = with_value(Settings(), key, value)
        if not isinstance(result, Rejected):
            found.append(value)
    return found


def rejection(key: str, value: Any) -> str:
    result = with_value(Settings(), key, value)
    assert isinstance(result, Rejected)
    return result.text()


@pytest.mark.case("T-SET-02")
@pytest.mark.req("APP-701")
def test_ftp_takes_whole_watts_from_100_to_500() -> None:
    assert accepted("ftp", [99, 100, 500, 501, 250.5]) == [100, 500]
    assert rejection("ftp", 99) == "ftp: 100 to 500 W in steps of 1"
    assert rejection("ftp", 250.5).startswith("ftp: ")
    assert rejection("ftp", True).startswith("ftp: ")
    changed = with_value(Settings(), "ftp", 260)
    assert isinstance(changed, Settings) and changed.ftp == 260


@pytest.mark.case("T-SET-03")
@pytest.mark.req("APP-702")
def test_zones_are_five_increasing_whole_percentages() -> None:
    valid = [56, 76, 91, 106, 121]
    assert accepted("zones_pct", [
        valid, [55, 75, 75, 105, 120], [55, 75, 90, 105],
        [55, 75, 90.5, 105, 120], [55, 75, 90, 120, 105],
        [0, 75, 90, 105, 120], "55,75"]) == [valid]
    assert "5 increasing upper bounds" in rejection(
        "zones_pct", [55, 75, 90, 105])
    changed = with_value(Settings(), "zones_pct", valid)
    assert isinstance(changed, Settings)
    assert changed.zones_pct == (56, 76, 91, 106, 121)


@pytest.mark.case("T-SET-04")
@pytest.mark.req("APP-703")
def test_lead_time_takes_half_seconds_from_0_to_5() -> None:
    assert accepted("lead_time", [-0.5, 0, 1.5, 5, 5.5, 1.2]) == [0, 1.5, 5]
    assert rejection("lead_time", 1.2) == (
        "lead_time: 0 to 5 s in steps of 0.5")


@pytest.mark.case("T-SET-05")
@pytest.mark.req("APP-704")
def test_battery_threshold_takes_5_percent_steps_from_5_to_50() -> None:
    assert accepted("battery_warn_pct", [0, 5, 20, 50, 55, 12]) == [
        5, 20, 50]
    assert rejection("battery_warn_pct", 12) == (
        "battery_warn_pct: 5 to 50 % in steps of 5")


@pytest.mark.case("S-SET-01")
def test_other_fields_and_the_json_form() -> None:
    assert accepted("free_ride_level_pct", [0, 35, 100, 37, 105]) == [
        0, 35, 100]
    assert accepted("upload_on", [True, False, 1, "on"]) == [True, False]
    assert rejection("colour", 1) == "colour: not a setting"
    trainer = {"address": "94:05:bb:03:5d:9d", "name": "VANRYSEL-HT-9d5d"}
    chosen = with_value(Settings(), SettingKey.TRAINER, trainer)
    assert isinstance(chosen, Settings)
    assert chosen.trainer == DeviceRef("94:05:BB:03:5D:9D",
                                       "VANRYSEL-HT-9d5d")
    assert accepted("hrm", [None, {"address": "nope"}, {
        "address": "E0:E2:EF:63:14:BC", "name": 7}]) == [None]
    raw = settings_json(chosen)
    assert raw["schema"] == 1 and raw["hrm"] is None
    again, rejected = settings_of(raw)
    assert (again, rejected) == (chosen, [])
    partly, problems = settings_of({"ftp": 600, "lead_time": 2.0})
    assert (partly.ftp, partly.lead_time) == (250, 2.0)
    assert [p.key for p in problems] == ["ftp"]
