import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.support.timeline import TESTDATA, load_json
from wow.core import ftms_codec as codec
from wow.core import hr_codec
from wow.core.devices import Erg, Range, Resistance, TrainerCapabilities
from wow.core.ftms_codec import Dropped
from wow.core.uuids import INDOOR_BIKE_DATA

BIKE = load_json("ftms/indoor_bike_data.json")
MACHINE = load_json("ftms/machine.json")
S1_LOG = TESTDATA / "ble" / "phase2-s1-contact.jsonl"
D100_RECORDS_IN_S1 = 1076


def entries(table: list[dict[str, Any]], case: str) -> list[Any]:
    return [pytest.param(e, id=e["name"]) for e in table if e["case"] == case]


def bike_fields(record: codec.IndoorBikeData) -> dict[str, Any]:
    return {
        "more_data": record.more_data,
        "speed_kmh": record.speed_kmh,
        "cadence_rpm": record.cadence_rpm,
        "resistance_raw": record.resistance_raw,
        "power": record.power,
        "declared_length": record.declared_length,
    }


def range_fields(value: Range | None) -> dict[str, int] | None:
    if value is None:
        return None
    return {"minimum": value.minimum, "maximum": value.maximum,
            "step": value.step}


def check_bike_record(entry: dict[str, Any]) -> None:
    decoded = codec.decode_indoor_bike_data(
        bytes.fromhex(entry["hex"]), entry["resistance_width"])
    if entry.get("drop"):
        assert isinstance(decoded, Dropped)
        assert decoded.data == bytes.fromhex(entry["hex"])
        return
    assert isinstance(decoded, codec.IndoorBikeData)
    assert bike_fields(decoded) == pytest.approx(entry["expect"])


@pytest.mark.case("T-COD-01")
@pytest.mark.req("APP-108")
@pytest.mark.parametrize("entry", entries(BIKE["records"], "T-COD-01"))
def test_real_d100_record_ignores_undeclared_bytes(
    entry: dict[str, Any],
) -> None:
    check_bike_record(entry)


@pytest.mark.case("T-COD-01")
@pytest.mark.req("APP-108")
def test_every_d100_record_of_the_s1_log_decodes() -> None:
    if not S1_LOG.exists():
        pytest.skip("Phase 2 S1 log not imported yet: "
                    "run tools/import_spike_log.py (testdata/README.md)")
    payloads = [
        bytes.fromhex(record["hex"])
        for record in map(json.loads, S1_LOG.read_text().splitlines())
        if record.get("op") == "notify"
        and record.get("uuid") == INDOOR_BIKE_DATA
    ]
    decoded = [codec.decode_indoor_bike_data(p) for p in payloads]
    assert len(decoded) == D100_RECORDS_IN_S1
    assert not [d for d in decoded if isinstance(d, Dropped)]


@pytest.mark.case("T-COD-02")
@pytest.mark.req("APP-108")
@pytest.mark.parametrize("entry", entries(BIKE["records"], "T-COD-02"))
def test_each_flag_places_its_field(entry: dict[str, Any]) -> None:
    check_bike_record(entry)


@pytest.mark.case("T-COD-03")
@pytest.mark.req("APP-108")
@pytest.mark.parametrize("entry", entries(BIKE["records"], "T-COD-03"))
def test_short_record_is_dropped_with_its_bytes(entry: dict[str, Any]) -> None:
    check_bike_record(entry)


@pytest.mark.case("T-COD-04")
@pytest.mark.req("APP-108")
@pytest.mark.parametrize("entry", entries(BIKE["joins"], "T-COD-04"))
def test_more_data_parts_are_joined(entry: dict[str, Any]) -> None:
    assembler = codec.BikeDataAssembler()
    results = []
    for part in entry["parts"]:
        decoded = codec.decode_indoor_bike_data(bytes.fromhex(part))
        assert isinstance(decoded, codec.IndoorBikeData)
        results.append(assembler.add(decoded))
    assert results[:-1] == [None] * (len(results) - 1)
    joined = results[-1]
    assert joined is not None
    assert bike_fields(joined) == pytest.approx(entry["expect"])


@pytest.mark.case("T-COD-04")
@pytest.mark.req("APP-108")
def test_endless_more_data_is_discarded() -> None:
    assembler = codec.BikeDataAssembler()
    part = codec.decode_indoor_bike_data(bytes.fromhex("4100c800"))
    assert isinstance(part, codec.IndoorBikeData)
    for _ in range(codec.MAX_JOINED_PARTS + 1):
        assert assembler.add(part) is None
    closing = codec.decode_indoor_bike_data(bytes.fromhex("00002c0b"))
    assert isinstance(closing, codec.IndoorBikeData)
    joined = assembler.add(closing)
    assert joined is not None and joined.power is None


DECODERS = (
    lambda b: codec.decode_indoor_bike_data(b, 2),
    lambda b: codec.decode_indoor_bike_data(b, 1),
    codec.decode_features,
    codec.decode_power_range,
    codec.decode_inclination_range,
    codec.decode_resistance_range,
    codec.decode_control_point_response,
    codec.decode_spin_down_band,
    codec.decode_status,
    hr_codec.decode_heart_rate,
    hr_codec.decode_battery_level,
)


@pytest.mark.case("T-COD-05")
@pytest.mark.req("APP-108")
@given(st.binary(min_size=0, max_size=40))
def test_decoders_never_raise(data: bytes) -> None:
    assembler = codec.BikeDataAssembler()
    for decode in DECODERS:
        result = decode(data)
        assert result is not None
        if isinstance(result, codec.IndoorBikeData):
            assembler.add(result)


@pytest.mark.case("T-COD-06")
@pytest.mark.req("APP-103")
@pytest.mark.parametrize("entry", entries(MACHINE["features"], "T-COD-06"))
def test_feature_bits(entry: dict[str, Any]) -> None:
    features = codec.decode_features(bytes.fromhex(entry["hex"]))
    assert isinstance(features, codec.Features)
    assert {name: getattr(features, name)
            for name in entry["expect"]} == entry["expect"]


@pytest.mark.case("T-COD-06")
@pytest.mark.req("APP-103")
@pytest.mark.parametrize(
    "table, decode",
    [("power_ranges", codec.decode_power_range),
     ("inclination_ranges", codec.decode_inclination_range)])
def test_power_and_inclination_ranges(table: str, decode: Any) -> None:
    for entry in MACHINE[table]:
        decoded = decode(bytes.fromhex(entry["hex"]))
        if entry.get("drop"):
            assert isinstance(decoded, Dropped), entry["name"]
        else:
            assert range_fields(decoded) == entry["expect"], entry["name"]


@pytest.mark.case("T-COD-06")
@pytest.mark.req("APP-103")
@pytest.mark.parametrize("entry",
                         entries(MACHINE["resistance_ranges"], "T-COD-06"))
def test_resistance_range_layouts(entry: dict[str, Any]) -> None:
    decoded = codec.decode_resistance_range(bytes.fromhex(entry["hex"]))
    if entry.get("drop"):
        assert isinstance(decoded, Dropped)
        assert decoded.data == bytes.fromhex(entry["hex"])
        return
    assert isinstance(decoded, codec.ResistanceSupport)
    fields = range_fields(decoded.range)
    assert fields is not None
    assert {**fields, "data_width": decoded.data_width} == entry["expect"]


@pytest.mark.case("T-COD-06")
@pytest.mark.req("APP-103")
@pytest.mark.parametrize("entry", entries(MACHINE["capabilities"], "T-COD-06"))
def test_capabilities_hide_undeclared_modes(entry: dict[str, Any]) -> None:
    features = codec.decode_features(bytes.fromhex(entry["features"]))
    power = codec.decode_power_range(bytes.fromhex(entry["power_range"]))
    resistance = codec.decode_resistance_range(
        bytes.fromhex(entry["resistance_range"]))
    assert isinstance(features, codec.Features)
    capabilities = codec.trainer_capabilities(
        features,
        None if isinstance(power, Dropped) else power,
        None if isinstance(resistance, Dropped) else resistance.range,
    )
    assert {
        "power": range_fields(capabilities.power),
        "resistance": range_fields(capabilities.resistance),
        "spin_down": capabilities.spin_down,
        "cadence": capabilities.cadence,
    } == entry["expect"]


def encoded(command: Any) -> bytes:
    match command:
        case "request_control":
            return codec.encode_request_control()
        case "start_or_resume":
            return codec.encode_start_or_resume()
        case "spin_down_start":
            return codec.encode_spin_down(True)
        case {"type": "erg", "power": power}:
            return codec.encode_command(Erg(power))
        case {"type": "resistance", "level_raw": level}:
            return codec.encode_command(Resistance(level))
    raise AssertionError(command)


@pytest.mark.case("T-COD-07")
@pytest.mark.req("APP-101", "APP-104")
@pytest.mark.parametrize("entry", entries(MACHINE["commands"], "T-COD-07"))
def test_command_encoding(entry: dict[str, Any]) -> None:
    assert encoded(entry["command"]).hex() == entry["hex"]


@pytest.mark.case("T-COD-07")
@pytest.mark.req("APP-101", "APP-104")
def test_spin_down_ignore_encoding() -> None:
    assert codec.encode_spin_down(False) == bytes([0x13, 0x02])


@pytest.mark.case("T-COD-08")
@pytest.mark.req("APP-105", "APP-502", "APP-503")
@pytest.mark.parametrize("entry", entries(MACHINE["responses"], "T-COD-08"))
def test_control_point_responses(entry: dict[str, Any]) -> None:
    decoded = codec.decode_control_point_response(bytes.fromhex(entry["hex"]))
    if entry.get("drop"):
        assert isinstance(decoded, Dropped)
        return
    assert isinstance(decoded, codec.ControlPointResponse)
    assert {"request_op": decoded.request_op, "result": decoded.result,
            "parameter": decoded.parameter.hex()} == entry["expect"]
    if "band_kmh" in entry:
        band = codec.decode_spin_down_band(decoded.parameter)
        assert list(band) == entry["band_kmh"]  # type: ignore[arg-type]


@pytest.mark.case("T-COD-08")
@pytest.mark.req("APP-105", "APP-502", "APP-503")
@pytest.mark.parametrize("entry", entries(MACHINE["statuses"], "T-COD-08"))
def test_machine_statuses(entry: dict[str, Any]) -> None:
    decoded = codec.decode_status(bytes.fromhex(entry["hex"]))
    if entry.get("drop"):
        assert isinstance(decoded, Dropped)
        return
    assert isinstance(decoded, codec.MachineStatus)
    assert {"code": decoded.code,
            "parameter": decoded.parameter.hex()} == entry["expect"]


@pytest.mark.case("T-COD-08")
@pytest.mark.req("APP-105", "APP-502", "APP-503")
def test_short_spin_down_band_is_dropped() -> None:
    assert isinstance(codec.decode_spin_down_band(b"\x00\x00"), Dropped)


@pytest.mark.case("T-COD-09")
@pytest.mark.req("APP-109")
@pytest.mark.parametrize("declared, expected", [(False, None), (True, 90.5)])
def test_cadence_only_where_declared(
    declared: bool, expected: float | None,
) -> None:
    record = codec.decode_indoor_bike_data(bytes.fromhex("44002c0bb500c800"))
    assert isinstance(record, codec.IndoorBikeData)
    capabilities = TrainerCapabilities(
        power=Range(50, 600, 1), resistance=Range(0, 100, 1),
        spin_down=True, cadence=declared)
    sample = codec.trainer_sample(record, capabilities, mono=12.5)
    assert sample.cadence_rpm == expected
    assert (sample.mono, sample.power, sample.speed_kmh) == (12.5, 200, 28.6)
