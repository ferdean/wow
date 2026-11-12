from typing import Any

import pytest

from tests.support.timeline import load_json
from wow.core import hr_codec
from wow.core.ftms_codec import Dropped

HR = load_json("hr/heart_rate.json")


def entries(table: list[dict[str, Any]]) -> list[Any]:
    return [pytest.param(e, id=e["name"]) for e in table]


@pytest.mark.case("T-COD-10")
@pytest.mark.req("APP-111", "APP-603")
@pytest.mark.parametrize("entry", entries(HR["heart_rate"]))
def test_heart_rate_measurement(entry: dict[str, Any]) -> None:
    decoded = hr_codec.decode_heart_rate(bytes.fromhex(entry["hex"]))
    if entry.get("drop"):
        assert isinstance(decoded, Dropped)
        return
    assert isinstance(decoded, hr_codec.HeartRate)
    assert {"heart_rate_bpm": decoded.heart_rate_bpm,
            "rr": list(decoded.rr)} == entry["expect"]


@pytest.mark.case("T-COD-11")
@pytest.mark.req("APP-113")
@pytest.mark.parametrize("entry", entries(HR["battery"]))
def test_battery_level(entry: dict[str, Any]) -> None:
    decoded = hr_codec.decode_battery_level(bytes.fromhex(entry["hex"]))
    if entry.get("drop"):
        assert isinstance(decoded, Dropped)
        return
    assert isinstance(decoded, hr_codec.BatteryLevel)
    assert {"battery_pct": decoded.battery_pct,
            "raw": decoded.raw} == entry["expect"]
