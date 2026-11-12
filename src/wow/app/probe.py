"""Probe the Bluetooth devices from the command line.

wow-probe: the Bluetooth foundation of slice SL-01 on the real D100 and
HRM 200, or on the simulator. Connects both, takes control of the
trainer, holds an ERG target, prints one line a second, releases the
trainer at its lowest level and writes the Bluetooth log (IF-11).
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from wow.adapters.ble_bleak import BleakConnector
from wow.adapters.ble_log import BleLogRecord, LoggingConnector, record_line
from wow.adapters.ble_sim import (
    D100_ADDRESS, HRM_ADDRESS, SimConnector, SimD100Server, SimHrm200Server,
    SimScheduler,
)
from wow.adapters.clock_system import SystemClock, default_sync_marker
from wow.app.device_manager import DeviceChoice, DeviceManager
from wow.app.ftms_trainer import FtmsTrainer
from wow.app.hrm_link import HrmLink
from wow.core.devices import Erg, HrSample, TrainerSample
from wow.ports.clock import Clock
from wow.ports.gatt import GattConnector
from typing import Final

CONTROL_WAIT: Final[float] = 40.0


@dataclass
class Readings:
    """The latest readings."""

    power: int | None = None
    speed_kmh: float | None = None
    heart_rate_bpm: int | None = None
    power_samples: int = 0
    lines: list[str] = field(default_factory=list)

    def trainer(self, sample: TrainerSample) -> None:
        """Take a trainer reading."""
        self.power, self.speed_kmh = sample.power, sample.speed_kmh
        self.power_samples += sample.power is not None

    def strap(self, sample: HrSample) -> None:
        """Take a strap reading."""
        self.heart_rate_bpm = sample.heart_rate_bpm


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the command line."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    parser = argparse.ArgumentParser(prog="wow-probe", description=__doc__)
    parser.add_argument("--trainer", default=D100_ADDRESS)
    parser.add_argument("--hrm", default=HRM_ADDRESS)
    parser.add_argument("--adapter", default="hci0")
    parser.add_argument("--watts", type=int, default=150)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--log", type=Path,
                        default=Path(f"probe-{stamp}.jsonl"))
    parser.add_argument("--simulate", action="store_true")
    return parser.parse_args(argv)


def status_line(elapsed: float, trainer: FtmsTrainer, hrm: HrmLink,
                readings: Readings) -> str:
    """Return the line printed each second."""
    return (f"{elapsed:5.0f} s | trainer {trainer.link():9} "
            f"control {'yes' if trainer.in_control() else 'no ':3} "
            f"answers {'yes' if trainer.responding() else 'no ':3} | "
            f"{_show(readings.power, 'W')} {_show(readings.speed_kmh, 'km/h')}"
            f" | strap {hrm.link():9} {_show(readings.heart_rate_bpm, 'bpm')}"
            f" battery {_show(hrm.battery_pct(), '%')}")


def _show(value: float | None, unit: str) -> str:
    return f"{'--' if value is None else value} {unit}"


async def probe(
    args: argparse.Namespace,
    clock: Clock,
    connector: GattConnector,
    out: Callable[[str], None] = print,
) -> int:
    """Connect both devices, hold a target and print readings."""
    readings = Readings()
    trainer = FtmsTrainer(clock, on_sample=readings.trainer)
    hrm = HrmLink(clock, on_sample=readings.strap)
    manager = DeviceManager(connector, clock, trainer, hrm,
                            DeviceChoice(args.trainer, args.hrm))
    manager.open_pre_ride()
    started = clock.monotonic()
    while not trainer.in_control():
        if clock.monotonic() - started > CONTROL_WAIT:
            out(status_line(clock.monotonic() - started, trainer, hrm,
                            readings))
            out("FAIL: no control of the trainer")
            await manager.close()
            return 1
        await clock.sleep_until(clock.monotonic() + 1.0)
    trainer.set_command(Erg(args.watts))
    hold_start = clock.monotonic()
    while clock.monotonic() - hold_start < args.seconds:
        await clock.sleep_until(clock.monotonic() + 1.0)
        out(status_line(clock.monotonic() - started, trainer, hrm, readings))
    await manager.close()
    passed = readings.power_samples > 0
    out("PASS: control taken, power received, trainer released at its "
        "lowest level" if passed else "FAIL: no power received")
    return 0 if passed else 1


async def run(args: argparse.Namespace) -> int:
    """Run the probe on the real or simulated devices."""
    clock = SystemClock(default_sync_marker())
    roles = {args.trainer.upper(): "trainer", args.hrm.upper(): "hrm"}
    with args.log.open("a", encoding="utf-8") as log:
        def sink(record: BleLogRecord) -> None:
            log.write(record_line(record) + "\n")

        def role_of(address: str) -> str:
            return roles.get(address.upper(), "other")

        if args.simulate:
            scheduler = SimScheduler(clock)
            inner: GattConnector = SimConnector(
                clock, [SimD100Server(scheduler), SimHrm200Server(scheduler)])
            connector = LoggingConnector(inner, clock, sink, role_of)
        else:
            bleak = BleakConnector(args.adapter)
            connector = LoggingConnector(bleak, clock, sink, role_of)
            bleak.on_stale_release = connector.stale_release
        result = await probe(args, clock, connector)
        if args.simulate:
            await scheduler.close()
    print(f"Bluetooth log: {args.log}")
    return result


def main(argv: Sequence[str] | None = None) -> None:
    """Run the probe from the command line."""
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(asyncio.run(run(parse_args(argv))))
