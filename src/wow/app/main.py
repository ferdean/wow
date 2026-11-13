"""Compose and run the app.

wow: the composition root (3A, app/main). Reads the configuration,
wires the real or simulated Bluetooth adapter, starts the web sites and
shuts down in order, the trainer at its lowest level first (APP-320,
APP-819).

    wow --config /etc/wow/wow.toml
    wow --config wow.toml --sim
"""

import argparse
import asyncio
import dataclasses
import logging
import signal
import sys
from collections.abc import Coroutine, Sequence
from importlib import metadata
from datetime import tzinfo
from pathlib import Path
from typing import Any, Final

from wow.adapters.ble_bleak import BleakConnector
from wow.adapters.ble_log import LoggingConnector
from wow.adapters.ble_sim import (
    D100_ADDRESS, HRM_ADDRESS, SimConnector, SimD100Server, SimHrm200Server,
    SimScheduler,
)
from wow.adapters.clock_system import SystemClock, default_sync_marker
from wow.app.boot import boot_id
from wow.adapters.fit_garmin import GarminFitWriter
from wow.adapters.intervals_icu import IntervalsIcu
from wow.app.config import (
    Config, RideSettings, load_config, load_secrets, load_settings,
)
from wow.app.console import Console
from wow.app.device_manager import DeviceChoice, DeviceManager
from wow.app.ftms_trainer import FtmsTrainer
from wow.app.hrm_link import HrmLink
from wow.app.loop_lag import LoopLagMonitor
from wow.app.recorder import Recorder
from wow.app.ride_controller import RideController
from wow.app.workout_catalog import (
    Entry, Source, WorkoutCatalog, builtin_entries,
)
from wow.core.workout import Workout
from wow.ports.clock import Clock
from wow.ports.gatt import GattConnector
from wow.ports.workouts import WorkoutProvider
from wow.web.hub import Hub
from wow.web.server import WebServer, http_app, https_app, tls_context

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: Final[Path] = Path("/etc/wow/wow.toml")
SIM_PEDAL_AFTER: Final[float] = 3.0
DISTRIBUTION: Final[str] = "witchesonwheels"


def app_version() -> str:
    """Return the installed version."""
    try:
        return metadata.version(DISTRIBUTION)
    except metadata.PackageNotFoundError:
        return "0+unknown"


class App:
    """The wired app."""

    def __init__(self, config: Config, clock: Clock,
                 sim_pedal_after: float = SIM_PEDAL_AFTER,
                 workouts: Sequence[Workout] | None = None,
                 provider: WorkoutProvider | None = None,
                 zone: tzinfo | None = None) -> None:
        self.config = config
        self.clock = clock
        settings = load_settings(config.data)
        self.recorder = Recorder(config.data, boot_id())
        self.scheduler: SimScheduler | None = None
        self.d100: SimD100Server | None = None
        self.sim: SimConnector | None = None
        connector, choice = self._bluetooth(settings, sim_pedal_after)
        self.trainer = FtmsTrainer(clock)
        self.hrm = HrmLink(clock)
        self.devices = DeviceManager(connector, clock, self.trainer,
                                     self.hrm, choice)
        self.rides = RideController(clock, self.trainer, self.recorder,
                                    self._changed, GarminFitWriter(),
                                    app_version())
        builtin = (builtin_entries() if workouts is None else
                   [Entry(w.ref, Source.BUILTIN, w.name, w, None)
                    for w in workouts])
        self.catalog = WorkoutCatalog(
            clock, provider or self._provider(), config.data / "cache" /
            "intervals.json", builtin, self._changed, zone)
        self.console = Console(clock, self.devices, self.rides, self.catalog,
                               settings, self._changed)
        self.trainer.on_sample = self.console.trainer_sample
        self.hrm.on_sample = self.console.hr_sample
        self.trainer.on_link = self.console.link_changed
        self.hrm.on_link = self.console.link_changed
        self.hub = Hub(clock, self.console, app_version())
        self.lag = LoopLagMonitor(clock)
        self.web = WebServer()
        self.ports: tuple[int, int] = (0, 0)
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Start the devices and the sites."""
        config = self.config
        self.recorder.start()
        https = await self.web.start(
            https_app(config.static, self.hub.handle), config.listen,
            config.https_port, tls_context(config.cert, config.key))
        http = await self.web.start(
            http_app(config.host, https, config.root_cert), config.listen,
            config.http_port)
        self.ports = (https, http)
        self._spawn(self.hub.run())
        self._spawn(self.lag.run())
        self.console.open_home()
        logger.info("wow %s started%s", app_version(),
                    " with simulated devices" if config.simulate else "")

    async def stop(self) -> None:
        """Stop in order, the trainer at its lowest level first."""
        await self.devices.close()
        await self.rides.close()
        await self.catalog.close()
        await self.hub.close()
        await self.web.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.scheduler is not None:
            await self.scheduler.close()
        self.recorder.stop()
        logger.info("wow stopped; worst event-loop lag %.0f ms, %d late",
                    self.lag.worst * 1000, self.lag.late)

    def _provider(self) -> WorkoutProvider | None:
        secrets = load_secrets(self.config.data)
        if secrets is None:
            logger.info("no intervals.icu account: built-in workouts only")
            return None
        return IntervalsIcu(secrets.athlete_id, secrets.api_key)

    def _changed(self) -> None:
        self.hub.changed()

    def _spawn(self, work: Coroutine[Any, Any, None]) -> None:
        self._tasks.append(asyncio.get_running_loop().create_task(work))

    def _bluetooth(self, settings: RideSettings, sim_pedal_after: float
                   ) -> tuple[GattConnector, DeviceChoice]:
        if self.config.simulate:
            self.scheduler = SimScheduler(self.clock)
            self.d100 = SimD100Server(self.scheduler,
                                      pedal_after_erg=sim_pedal_after)
            self.sim = SimConnector(
                self.clock, [self.d100, SimHrm200Server(self.scheduler)])
            inner: GattConnector = self.sim
            choice = DeviceChoice(D100_ADDRESS, HRM_ADDRESS)
            return self._logged(inner, choice), choice
        choice = DeviceChoice(settings.trainer, settings.hrm)
        bleak = BleakConnector(self.config.adapter)
        connector = self._logged(bleak, choice)
        bleak.on_stale_release = connector.stale_release
        return connector, choice

    def _logged(self, inner: GattConnector,
                choice: DeviceChoice) -> LoggingConnector:
        roles = {address.upper(): role for role, address in (
            ("trainer", choice.trainer), ("hrm", choice.hrm)) if address}
        return LoggingConnector(
            inner, self.clock, self.recorder.ble,
            lambda address: roles.get(address.upper(), "other"))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(prog="wow", description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--sim", action="store_true",
                        help="simulated D100 and HRM 200 (APP-819)")
    return parser.parse_args(argv)


async def serve(app: App) -> int:
    """Run the app until a stop signal; return the exit code."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await app.start()
    try:
        await stop.wait()
    finally:
        await app.stop()
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    """Run the app from the command line."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s "
                               "%(message)s")
    args = parse_args(argv)
    config = load_config(args.config)
    if args.sim:
        config = dataclasses.replace(config, simulate=True)
    clock = SystemClock(default_sync_marker())
    sys.exit(asyncio.run(serve(App(config, clock))))


if __name__ == "__main__":
    main()
