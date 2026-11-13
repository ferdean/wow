"""FIT activity files decoded with the Garmin SDK's own decoder (L1)."""

import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from garmin_fit_sdk import Decoder, Stream

from wow.adapters.fit_garmin import encode_activity, software_version
from wow.core.activity import Activity, Pause, RecordedSample
from wow.core.metrics import ride_metrics

START = datetime(2026, 11, 13, 17, 0, tzinfo=UTC)


def decode(data: bytes) -> Any:
    assert Decoder(Stream.from_byte_array(bytearray(data))).check_integrity()
    messages, errors = Decoder(Stream.from_byte_array(bytearray(data))).read()
    assert errors == []
    return messages


def activity(power: Sequence[int | None], laps: tuple[float, ...] = (0.0,),
             pauses: tuple[Pause, ...] = (), version: str = "0.3.0"
             ) -> Activity:
    hr: list[int | None] = [140] * len(power)
    shifted = Activity("Test", version, 250, START, float(len(power)), (),
                       laps, pauses, ride_metrics(power, hr, 250))
    samples = tuple(RecordedSample(t, shifted.utc_at(t), p, 140, None, 200)
                    for t, p in enumerate(power))
    return Activity("Test", version, 250, START, float(len(power)), samples,
                    laps, pauses, ride_metrics(power, hr, 250))


@pytest.mark.case("T-FIT-02")
@pytest.mark.req("APP-604")
def test_a_pause_is_two_timer_events_and_no_records() -> None:
    ride = activity([200] * 120, laps=(0.0, 30.0, 90.0),
                    pauses=(Pause(60.0, 60.0),))
    messages = decode(encode_activity(ride))
    events = [(e["event_type"], e["timestamp"] - START)
              for e in messages["event_mesgs"]]
    assert events == [("start", timedelta(0)),
                      ("stop_all", timedelta(seconds=60)),
                      ("start", timedelta(seconds=120)),
                      ("stop_all", timedelta(seconds=180))]
    stamps = [r["timestamp"] - START for r in messages["record_mesgs"]]
    assert not any(timedelta(seconds=60) <= s < timedelta(seconds=120)
                   for s in stamps)
    laps = messages["lap_mesgs"]
    assert [lap["total_timer_time"] for lap in laps] == [30, 60, 30]
    assert laps[1]["total_elapsed_time"] == 120
    session = messages["session_mesgs"][0]
    assert (session["total_timer_time"], session["total_elapsed_time"]) == (
        120, 180)


@pytest.mark.case("T-FIT-03")
@pytest.mark.req("APP-605")
def test_one_lap_per_step_started_at_the_journal_times() -> None:
    starts = [30.0 * i for i in range(12)]
    starts[7] = 201.0
    skipped = tuple(s for i, s in enumerate(starts) if i != 8)
    ride = activity([250] * 360, laps=skipped)
    laps = decode(encode_activity(ride))["lap_mesgs"]
    assert len(laps) == len(skipped)
    assert [(lap["start_time"] - START).total_seconds() for lap in laps] == (
        list(skipped))


@pytest.mark.case("T-FIT-04")
@pytest.mark.req("APP-603")
def test_records_in_a_dropout_have_no_power() -> None:
    power: list[int | None] = [200] * 30 + [None] * 10 + [200] * 20
    records = decode(encode_activity(activity(power)))["record_mesgs"]
    assert len(records) == 60
    assert all("power" not in r for r in records[30:40])
    assert all(r["power"] == 200 for r in records[40:])
    assert all(r["heart_rate"] == 140 for r in records)


@pytest.mark.case("T-FIT-05")
@pytest.mark.req("APP-815")
def test_the_app_version_is_in_the_creator_and_device_info() -> None:
    messages = decode(encode_activity(activity([200] * 40, version="1.12.3")))
    assert messages["file_creator_mesgs"][0]["software_version"] == 112
    device = messages["device_info_mesgs"][0]
    assert device["product_name"] == "WitchesOnWheels 1.12.3"
    assert device["device_index"] == "creator"
    assert software_version("0+unknown") == 0


@pytest.mark.case("T-FIT-06")
@pytest.mark.req("APP-606")
def test_the_session_carries_the_metrics_of_table_m() -> None:
    ride = activity(([330] * 30 + [140] * 30) * 6)
    session = decode(encode_activity(ride))["session_mesgs"][0]
    metrics = ride.metrics
    assert metrics.np is not None and metrics.intensity_factor is not None
    assert metrics.tss is not None
    assert session["normalized_power"] == round(metrics.np)
    assert session["intensity_factor"] == pytest.approx(
        metrics.intensity_factor, abs=0.001)
    assert session["training_stress_score"] == pytest.approx(
        metrics.tss, abs=0.1)
    assert session["threshold_power"] == 250
    assert session["total_work"] == round(metrics.work_kj * 1000)
    assert (session["sport"], session["sub_sport"]) == (
        "cycling", "indoor_cycling")


@pytest.mark.case("S-FIT-01")
@pytest.mark.slow
@pytest.mark.pi
def test_a_four_hour_ride_encodes_within_ten_seconds() -> None:
    hours = float(os.environ.get("WOW_FIT_HOURS", "4"))
    seconds = int(hours * 3600)
    ride = activity([200] * seconds,
                    laps=tuple(float(t) for t in range(0, seconds, 300)))
    began = time.monotonic()
    data = encode_activity(ride)
    took = time.monotonic() - began
    print(f"S-FIT-01 {'pass' if took <= 10 else 'fail'}: "
          f"{seconds} records in {took:.1f} s, {len(data)} bytes")
    assert took <= 10.0
