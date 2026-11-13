"""One sample per ride second and the metrics of table M (L1, L2)."""

import json
import math
from typing import Any

import pytest

from tests.support.timeline import TESTDATA, load_json
from wow.core import ftms_codec, hr_codec, uuids
from wow.core.metrics import normalized_power, ride_metrics
from wow.core.sampler import (
    Began, HrValue, Paused, Resumed, Sample, Sampler, SamplerEvent, Stopped,
    Tick, TrainerValue,
)

S2_LOG = TESTDATA / "ble" / "phase2-s2-steps.jsonl"


def drive(events: list[tuple[float, SamplerEvent]],
          until: float) -> list[Sample]:
    sampler, samples = Sampler(), []
    for at, event in sorted(events, key=lambda e: e[0]):
        while (due := sampler.next_deadline()) is not None and due < at:
            samples += sampler.handle(Tick(), due)
        samples += sampler.handle(event, at)
    while (due := sampler.next_deadline()) is not None and due <= until:
        samples += sampler.handle(Tick(), due)
    return samples


def s2_values() -> list[tuple[float, SamplerEvent]]:
    values: list[tuple[float, SamplerEvent]] = []
    for line in S2_LOG.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["op"] != "notify":
            continue
        mono, data = record["mono_ms"] / 1000, bytes.fromhex(record["hex"])
        if record["uuid"] == uuids.INDOOR_BIKE_DATA:
            bike = ftms_codec.decode_indoor_bike_data(data, 2)
            if not isinstance(bike, ftms_codec.Dropped):
                values.append((mono, TrainerValue(mono, bike.power)))
        elif record["uuid"] == uuids.HEART_RATE_MEASUREMENT:
            heart = hr_codec.decode_heart_rate(data)
            if not isinstance(heart, ftms_codec.Dropped):
                values.append((mono, HrValue(mono, heart.heart_rate_bpm)))
    return values


@pytest.mark.case("T-SMP-01")
@pytest.mark.req("APP-602")
@pytest.mark.skipif(not S2_LOG.exists(), reason="S2 log not imported")
def test_each_second_holds_the_latest_value_of_a_real_ride() -> None:
    values = s2_values()
    start = values[0][0] + 5.0
    samples = drive([(start, Began(start)), *values], values[-1][0])
    assert [s.t for s in samples] == list(range(len(samples)))
    assert len(samples) > 900
    powers = [(e.mono, e.power) for _, e in values
              if isinstance(e, TrainerValue)]
    for sample in samples[::37]:
        latest = [p for m, p in powers if m <= sample.mono + 1e-6]
        assert sample.power == latest[-1]


@pytest.mark.case("T-SMP-02")
@pytest.mark.req("APP-602")
@pytest.mark.parametrize("age,kept", [(1.9, True), (2.0, True), (2.1, False)])
def test_values_older_than_two_seconds_are_missing(age: float,
                                                   kept: bool) -> None:
    samples = drive([(0.0, TrainerValue(0.0, 150)), (0.0, HrValue(0.0, 140)),
                     (age, Began(age))], age)
    assert (samples[0].power, samples[0].heart_rate_bpm) == (
        (150, 140) if kept else (None, None))


@pytest.mark.case("T-SMP-03")
@pytest.mark.req("APP-603")
def test_gaps_are_missing_and_real_zeros_stay() -> None:
    events: list[tuple[float, SamplerEvent]] = [(0.0, Began(0.0))]
    events += [(t / 4, TrainerValue(t / 4, 0 if t >= 60 else 200))
               for t in range(0, 80)]
    events += [(30.0 + t / 4, TrainerValue(30.0 + t / 4, 180))
               for t in range(0, 40)]
    events += [(t / 2, HrValue(t / 2, 0 if t >= 20 else 130))
               for t in range(0, 30)]
    samples = drive(events, 40.0)
    assert [s.power for s in samples[22:30]] == [None] * 8
    assert {s.power for s in samples[15:22]} == {0}
    assert {s.heart_rate_bpm for s in samples[10:16]} == {None}
    assert samples[5].heart_rate_bpm == 130


@pytest.mark.case("T-SMP-04")
@pytest.mark.req("APP-604")
def test_no_samples_in_a_pause_and_no_hole_in_ride_time() -> None:
    events: list[tuple[float, SamplerEvent]] = [
        (0.0, Began(0.0)), (10.5, Paused(10.5)), (70.5, Resumed(70.5))]
    events += [(t / 4, TrainerValue(t / 4, 150)) for t in range(0, 400)]
    samples = drive(events, 99.9)
    assert [s.t for s in samples] == list(range(len(samples)))
    assert [round(s.mono, 3) for s in samples[10:12]] == [10.0, 71.0]
    assert not any(10.5 < s.mono < 70.5 for s in samples)
    assert drive([(0.0, Began(0.0)), (3.0, Stopped(3.0))], 9.0)[-1].t == 3


@pytest.mark.case("T-MET-01")
@pytest.mark.req("APP-606")
def test_an_hour_at_200_w() -> None:
    metrics = ride_metrics([200] * 3600, [150] * 3600, 250)
    assert metrics.avg_power == 200
    assert round(metrics.np or 0, 9) == 200
    assert round(metrics.intensity_factor or 0, 9) == 0.8
    assert metrics.tss == pytest.approx(64.0)
    assert (metrics.work_kj, metrics.duration) == (720, 3600)


@pytest.mark.case("T-MET-02")
@pytest.mark.req("APP-606")
def test_np_needs_thirty_power_samples() -> None:
    assert ride_metrics([200] * 29, [], 250).np is None
    short = ride_metrics([200] * 29, [], 250)
    assert short.intensity_factor is None and short.tss is None
    assert ride_metrics([200] * 30, [], 250).np == pytest.approx(200)


@pytest.mark.case("T-MET-03")
@pytest.mark.req("APP-606")
def test_thirty_thirties_against_an_independent_np() -> None:
    power = ([330] * 30 + [140] * 30) * 6
    rolling = [sum(power[i - 29:i + 1]) / 30 for i in range(29, len(power))]
    independent = math.pow(sum(r ** 4 for r in rolling) / len(rolling), 0.25)
    metrics = ride_metrics(power, [], 250)
    assert metrics.np == pytest.approx(independent, abs=0.5)
    expected_tss = 360 * independent ** 2 / 250 ** 2 / 3600 * 100
    assert metrics.tss == pytest.approx(expected_tss, abs=0.1)


@pytest.mark.case("T-MET-04")
@pytest.mark.req("APP-606", "APP-603")
def test_missing_values_are_left_out_and_zeros_count() -> None:
    power: list[int | None] = [200] * 60 + [None] * 60 + [0] * 60
    metrics = ride_metrics(power, [], 250)
    assert metrics.duration == 180
    assert metrics.avg_power == pytest.approx(100)
    assert metrics.work_kj == pytest.approx(12)
    assert normalized_power([200] * 60 + [0] * 60) == metrics.np


@pytest.mark.case("T-MET-05")
@pytest.mark.req("APP-606", "APP-702")
def test_time_in_zone_at_the_default_zones() -> None:
    metrics = ride_metrics([137, 138, 187, 188, None], [], 250)
    assert metrics.time_in_zone == (1, 2, 1, 0, 0, 0)
    assert sum(metrics.time_in_zone) == 4


@pytest.mark.case("T-MET-06")
@pytest.mark.req("APP-606")
def test_heart_rate_over_the_values_present() -> None:
    metrics = ride_metrics([], [120, None, 140, None, 160], 250)
    assert (metrics.avg_hr_bpm, metrics.max_hr_bpm) == (140, 160)
    assert ride_metrics([], [None], 250).avg_hr_bpm is None


@pytest.mark.case("T-MET-07")
@pytest.mark.req("APP-606")
def test_a_real_ride_against_the_independent_calculation() -> None:
    fixture: dict[str, Any] = load_json("metrics/s2-ride.json")
    metrics = ride_metrics(fixture["power"], fixture["hr_bpm"],
                           fixture["ftp"])
    expected = fixture["expected"]
    for name, value in expected.items():
        actual = getattr(metrics, name)
        if isinstance(value, list):
            assert list(actual) == value
        else:
            assert actual == pytest.approx(value, rel=1e-9), name
