import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

import bluez_release
import ftms_codec as codec
import spike_trainer as spike


def test_indoor_bike_speed_and_power_only() -> None:
    data = bytes.fromhex("4000" "c409" "c800")
    values = codec.decode_indoor_bike(data)
    assert values["speed_kmh"] == pytest.approx(25.0)
    assert values["power_w"] == 200
    assert values["more_data"] == 0


def test_indoor_bike_more_data_has_no_speed() -> None:
    values = codec.decode_indoor_bike(bytes.fromhex("4100" "2c01"))
    assert "speed_kmh" not in values
    assert values["power_w"] == 300
    assert values["more_data"] == 1


@pytest.mark.parametrize("resistance, size", [("3200", 2), ("32", 1)])
def test_indoor_bike_resistance_width_is_given(
        resistance: str, size: int) -> None:
    data = bytes.fromhex("6000" "c409" + resistance + "9600")
    values = codec.decode_indoor_bike(data, size)
    assert values["resistance"] == 50
    assert values["power_w"] == 150
    assert values["extra_bytes"] == 0


@pytest.mark.parametrize("record, speed, power", [
    ("40002f0722004e05161000001c00e803", 18.39, 34),
    ("4000a80ac800de07993544081c006302", 27.28, 200),
    ("4000c90943013807504cbe0b1c009301", 25.05, 323),
])
def test_indoor_bike_d100_records_with_undeclared_bytes(
        record: str, speed: float, power: int) -> None:
    values = codec.decode_indoor_bike(bytes.fromhex(record))
    assert values["speed_kmh"] == pytest.approx(speed)
    assert values["power_w"] == power
    assert values["extra_bytes"] == 10
    assert values["more_data"] == 0


def test_resistance_field_size_follows_range_layout() -> None:
    assert codec.resistance_field_size(6) == 2
    assert codec.resistance_field_size(3) == 1


def test_indoor_bike_cadence_distance_energy_and_times() -> None:
    data = bytes.fromhex(
        "540b" "e803" "a000" "102700" "fa00" "0a00" "6400" "05" "8c"
        "1e00")
    values = codec.decode_indoor_bike(data)
    assert values["speed_kmh"] == pytest.approx(10.0)
    assert values["cadence_rpm"] == 80.0
    assert values["hr_bpm"] == 140
    assert values["distance_m"] == 10000
    assert values["power_w"] == 250
    assert values["energy_kcal"] == 10
    assert values["elapsed_s"] == 30


def test_indoor_bike_rejects_short_record() -> None:
    with pytest.raises(ValueError):
        codec.decode_indoor_bike(bytes.fromhex("4000" "c409"))


def test_cycling_power_with_crank_data() -> None:
    data = bytes.fromhex("2000" "fa00" "0a00" "0004")
    values = codec.decode_cycling_power(data)
    assert values["power_w"] == 250
    assert values["crank_revs"] == 10
    assert values["crank_time_s"] == pytest.approx(1.0)


def test_heart_rate_uint8_and_uint16() -> None:
    assert codec.decode_heart_rate(bytes.fromhex("068c"))["hr_bpm"] == 140
    assert codec.decode_heart_rate(bytes.fromhex("01b400"))["hr_bpm"] == 180


def test_heart_rate_counts_rr_after_energy() -> None:
    data = bytes.fromhex("188c" "0100" "0004" "0004")
    values = codec.decode_heart_rate(data)
    assert values["rr_count"] == 2


def test_response_and_spin_down_band() -> None:
    request, result, params = codec.decode_response(
        bytes.fromhex("801301" "c409" "b80b"))
    assert (request, result) == (codec.SPIN_DOWN, codec.SUCCESS)
    assert codec.decode_spin_down_band(params) == (25.0, 30.0)


def test_status_descriptions() -> None:
    assert codec.describe_status(bytes.fromhex("1404")).endswith(
        "stop pedaling")
    assert codec.describe_status(bytes.fromhex("084a01")).endswith("330 W")
    assert codec.describe_status(bytes.fromhex("ff")) == (
        "control permission lost")


def test_ranges_and_features_from_the_probe() -> None:
    assert codec.decode_range(bytes.fromhex("320058020100")) == (50, 600, 1)
    assert codec.decode_range(bytes.fromhex("000064000100")) == (0, 100, 1)
    assert codec.decode_features(bytes.fromhex("014000000ca00000")) == (
        0x4001, 0xA00C)


def test_commands() -> None:
    assert codec.power_command(330) == bytes.fromhex("054a01")
    assert codec.resistance_command(50, 1) == bytes.fromhex("0432")
    assert codec.resistance_command(50, 2) == bytes.fromhex("043200")


def test_target_plan_sends_early_and_merges_equal_targets() -> None:
    steps = [codec.Step(60, 150), codec.Step(30, 330), codec.Step(30, 330),
             codec.Step(30, 140)]
    assert codec.target_plan(steps, 2.5) == [
        (0.0, 150), (57.5, 330), (117.5, 140)]


def test_shorter_profile_keeps_the_closing_steps() -> None:
    steps = codec.step_profile(5, reps=3)
    assert codec.total_seconds(steps) == 16 * 60
    assert [s.watts for s in steps[-4:]] == [220, 325, 220, 140]


def test_reps_option_is_bounded() -> None:
    assert spike.parse_args(
        ["steps", "--trainer", "AA", "--reps", "3"]).reps == 3
    with pytest.raises(SystemExit):
        spike.parse_args(["steps", "--trainer", "AA", "--reps", "9"])


def test_current_step_and_profile_length() -> None:
    steps = codec.step_profile(5)
    assert codec.total_seconds(steps) == 19 * 60
    assert codec.current_step(steps, 0) == 0
    assert codec.current_step(steps, 300) == 1
    assert codec.current_step(steps, 19 * 60) is None


def test_sweep_levels() -> None:
    assert codec.sweep_levels(0, 100) == [0, 25, 50, 75, 100]


class FakeChar:
    def __init__(self, uuid: str) -> None:
        self.uuid = uuid


class FakeTrainer:
    """Answers control point writes the way an FTMS trainer would."""

    flap_on_connect = False

    def __init__(self, address: str, disconnected_callback: Any = None,
                 timeout: float = 10.0) -> None:
        self.is_connected = False
        self.callbacks: dict[str, Any] = {}
        self.written: list[bytes] = []
        self.on_disconnect = disconnected_callback
        self.silent = False
        self.reads = {
            spike.FEATURE: bytes.fromhex("014000000ca00000"),
            spike.POWER_RANGE: bytes.fromhex("320058020100"),
            spike.RESISTANCE_RANGE: bytes.fromhex("000064000100"),
            spike.BATTERY: bytes.fromhex("50"),
        }

    async def connect(self) -> None:
        if self.flap_on_connect:
            self.on_disconnect(self)
        self.is_connected = True

    async def disconnect(self) -> None:
        was_connected, self.is_connected = self.is_connected, False
        if was_connected:
            self.on_disconnect(self)

    async def start_notify(self, uuid: str, callback: Any) -> None:
        self.callbacks[uuid] = callback

    async def read_gatt_char(self, uuid: str) -> bytearray:
        return bytearray(self.reads.get(uuid, b"D100"))

    async def write_gatt_char(self, uuid: str, data: bytes,
                              response: bool | None = None) -> None:
        self.written.append(bytes(data))
        if self.silent:
            return
        answer = bytes([0x80, data[0], self.result(bytes(data))])
        if data[0] == codec.SPIN_DOWN:
            answer += bytes.fromhex("c409b80b")
        callback = self.callbacks[spike.CONTROL_POINT]
        asyncio.get_running_loop().call_soon(
            callback, FakeChar(spike.CONTROL_POINT), bytearray(answer))

    @staticmethod
    def result(data: bytes) -> int:
        if data[0] == codec.SET_RESISTANCE and len(data) == 2:
            return codec.INVALID_PARAMETER
        return codec.SUCCESS


class FlappingTrainer(FakeTrainer):
    flap_on_connect = True


async def no_stale_link(address: str) -> str:
    return "not connected"


def make_trainer(tmp_path: Path,
                 factory: type[FakeTrainer] = FakeTrainer) -> spike.Trainer:
    log = spike.RunLog(tmp_path / "log.jsonl")
    return spike.Trainer("AA:BB", log, spike.Live(), factory=factory,
                         releaser=no_stale_link)


def events(tmp_path: Path, name: str) -> list[dict[str, Any]]:
    lines = (tmp_path / "log.jsonl").read_text().splitlines()
    return [r for r in map(json.loads, lines) if r.get("name") == name]


def test_trainer_commands_and_resistance_fallback(tmp_path: Path) -> None:
    async def scenario() -> None:
        trainer = make_trainer(tmp_path)
        await trainer.connect()
        assert await trainer.request_control() == codec.SUCCESS
        assert await trainer.set_power(200) == codec.SUCCESS
        assert await trainer.set_resistance(50) == codec.SUCCESS
        assert trainer.resistance_size == 2
        assert await trainer.spin_down() == (codec.SUCCESS, (25.0, 30.0))
        await trainer.close()
        assert trainer.client.written[-1] == bytes.fromhex("040000")

    asyncio.run(scenario())


def test_trainer_reports_no_response(tmp_path: Path) -> None:
    async def scenario() -> None:
        trainer = make_trainer(tmp_path)
        await trainer.connect()
        trainer.client.silent = True
        result = await trainer.command(bytes([0x00]), timeout=0.05)
        assert result == (codec.NO_RESPONSE, b"")

    asyncio.run(scenario())


def test_trainer_reconnects_and_recovers(tmp_path: Path) -> None:
    async def scenario() -> None:
        trainer = make_trainer(tmp_path)
        await trainer.connect()
        recovered = asyncio.Event()

        async def on_recovered() -> None:
            await trainer.request_control()
            recovered.set()

        task = asyncio.create_task(trainer.keep_alive(on_recovered))
        trainer.client.is_connected = False
        trainer.client.on_disconnect(trainer.client)
        await asyncio.wait_for(recovered.wait(), 1.0)
        assert trainer.connected and trainer.has_control
        task.cancel()

    asyncio.run(scenario())


def test_describe_reads_the_ranges(tmp_path: Path) -> None:
    async def scenario() -> None:
        trainer = make_trainer(tmp_path)
        await trainer.connect()
        lines = await trainer.describe()
        assert "features: machine 0x00004001 target 0x0000a00c" in lines
        assert trainer.resistance_range == (0, 100, 1)

    asyncio.run(scenario())


def test_repeated_status_is_reported_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        trainer = make_trainer(tmp_path)
        await trainer.connect()
        heard: list[bytes] = []
        trainer.status_listener = heard.append
        callback = trainer.client.callbacks[spike.MACHINE_STATUS]
        for payload in ("08c800", "08c800", "08c800", "0732"):
            callback(FakeChar(spike.MACHINE_STATUS),
                     bytearray.fromhex(payload))
        assert heard == [bytes.fromhex("08c800"), bytes.fromhex("0732")]

    asyncio.run(scenario())


def test_d100_record_updates_live_speed(tmp_path: Path) -> None:
    async def scenario() -> None:
        trainer = make_trainer(tmp_path)
        await trainer.connect()
        await trainer.describe()
        callback = trainer.client.callbacks[spike.INDOOR_BIKE]
        callback(FakeChar(spike.INDOOR_BIKE),
                 bytearray.fromhex("40002f0722004e05161000001c00e803"))
        assert trainer.live.get("ibd.speed_kmh") == pytest.approx(18.39)
        assert trainer.ibd_resistance_size == 2

    asyncio.run(scenario())


def test_disconnect_reported_inside_connect_is_ignored(
        tmp_path: Path) -> None:
    async def scenario() -> None:
        trainer = make_trainer(tmp_path, FlappingTrainer)
        await trainer.connect()
        assert not trainer.lost.is_set()
        assert events(tmp_path, "disconnect_ignored")[0]["connecting"]

    asyncio.run(scenario())


def test_disconnect_from_an_old_client_is_ignored(tmp_path: Path) -> None:
    async def scenario() -> None:
        trainer = make_trainer(tmp_path)
        await trainer.connect()
        old = trainer.client
        await trainer.connect()
        old.on_disconnect(old)
        assert not trainer.lost.is_set()
        assert events(tmp_path, "disconnect_ignored")[0]["stale"]

    asyncio.run(scenario())


def test_forced_drop_is_recovered(tmp_path: Path) -> None:
    async def scenario() -> None:
        trainer = make_trainer(tmp_path)
        await trainer.connect()
        recovered = asyncio.Event()

        async def on_recovered() -> None:
            recovered.set()

        task = asyncio.create_task(trainer.keep_alive(on_recovered))
        await trainer.drop()
        await asyncio.wait_for(recovered.wait(), 1.0)
        assert trainer.connected
        assert events(tmp_path, "disconnected")[0]["planned"] is False
        assert len(events(tmp_path, "stale_release")) == 2
        task.cancel()

    asyncio.run(scenario())


def test_release_outcomes_and_device_path() -> None:
    assert bluez_release.device_path("94:05:bb:03:5d:9d") == (
        "/org/bluez/hci0/dev_94_05_BB_03_5D_9D")
    assert bluez_release.outcome(None) == "released"
    assert bluez_release.outcome(bluez_release.NOT_CONNECTED) == (
        "not connected")
    assert bluez_release.outcome("org.bluez.Error.Failed").startswith("error")


def test_ride_options_for_drops_and_crash() -> None:
    args = spike.parse_args(["ride", "--trainer", "AA", "--drop-at", "60",
                             "--drop-at", "120", "--crash-at", "200"])
    assert args.drop_at == [60.0, 120.0]
    assert args.crash_at == 200.0


def test_notification_updates_live_power(tmp_path: Path) -> None:
    async def scenario() -> None:
        trainer = make_trainer(tmp_path)
        await trainer.connect()
        callback = trainer.client.callbacks[spike.INDOOR_BIKE]
        callback(FakeChar(spike.INDOOR_BIKE),
                 bytearray.fromhex("4000c409c800"))
        assert trainer.live.get("ibd.power_w") == 200

    asyncio.run(scenario())
