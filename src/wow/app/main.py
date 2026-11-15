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
from collections.abc import Callable, Coroutine, Sequence
from importlib import metadata
from datetime import tzinfo
from pathlib import Path
from typing import Any, Final

from wow.adapters.ble_bleak import BleakConnector
from wow.adapters.ble_log import LoggingConnector
from wow.adapters.ble_sim import (
    D100_ADDRESS, HRM_ADDRESS, Faults, SimConnector, SimD100Server,
    SimFaults, SimHrm200Server, SimScheduler, bystanders,
)
from wow.adapters.ble_sim.server import SimServerBase
from wow.adapters.clock_system import SystemClock, default_sync_marker
from wow.app.boot import boot_id
from wow.adapters.fit_garmin import GarminFitWriter
from wow.adapters.intervals_icu import IntervalsIcu
from wow.adapters.led_sysfs import SysfsLed
from wow.app.calibration_controller import CalibrationController
from wow.app.config import (
    Config, Secrets, load_config, load_secrets, load_settings,
)
from wow.app.console import Console
from wow.app.device_manager import DeviceChoice, DeviceManager
from wow.app.ftms_trainer import FtmsTrainer
from wow.app.hrm_link import HrmLink
from wow.app.loop_lag import LoopLagMonitor
from wow.app.recorder import Recorder
from wow.app.recovery import close_cancelled, find_interrupted
from wow.app.housekeeping import CertificateWatch, FreeSpace, disk_free
from wow.app.ride_controller import RideController, Summary
from wow.app.settings_panel import SettingsPanel
from wow.app.upload_worker import UploadWorker
from wow.app.status_led import LedController
from wow.app.timing_log import TimingLog
from wow.app.workout_catalog import (
    Entry, Source, WorkoutCatalog, builtin_entries,
)
from wow.core.ride import RIDING
from wow.core.settings import Settings
from wow.core.workout import Workout
from wow.ports.clock import Clock
from wow.ports.gatt import GattConnector
from wow.ports.led import StatusLed
from wow.ports.upload import ActivityUploader
from wow.core.vocab import UploadState
from wow.ports.workouts import WorkoutProvider
from wow.web.hub import Hub
from wow.web.server import WebServer, http_app, https_app, tls_context

logger = logging.getLogger(__name__)

DEFAULT_CONFIG: Final[Path] = Path("/etc/wow/wow.toml")
SIM_PEDAL_AFTER: Final[float] = 3.0
DISTRIBUTION: Final[str] = "witchesonwheels"

AccountFactory = Callable[[Secrets], IntervalsIcu]
SimDevices = Callable[[SimScheduler], Sequence[SimServerBase]]


def intervals_account(secrets: Secrets) -> IntervalsIcu:
    """Return the intervals.icu client of an account."""
    return IntervalsIcu(secrets.athlete_id, secrets.api_key)


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
                 zone: tzinfo | None = None,
                 sim_faults: SimFaults = SimFaults(),
                 replay: GattConnector | None = None,
                 boot: str | None = None,
                 led: StatusLed | None = None,
                 uploader: ActivityUploader | None = None,
                 free_bytes: Callable[[Path], int] | None = None,
                 account: AccountFactory = intervals_account,
                 sim_trainer: Callable[[SimScheduler], SimD100Server]
                 | None = None,
                 sim_devices: SimDevices | None = None) -> None:
        self.config = config
        self.clock = clock
        self._faults = sim_faults
        self._replay = replay
        self._account_factory = account
        self._sim_trainer = sim_trainer
        self._sim_devices = sim_devices
        settings = load_settings(config.data)
        self.recorder = Recorder(config.data, boot or boot_id())
        self.scheduler: SimScheduler | None = None
        self.d100: SimD100Server | None = None
        self.sim: SimConnector | None = None
        connector, choice = self._bluetooth(settings, sim_pedal_after)
        self.trainer = FtmsTrainer(clock)
        self.hrm = HrmLink(clock)
        self.devices = DeviceManager(connector, clock, self.trainer,
                                     self.hrm, choice)
        self.settings = SettingsPanel(
            config.data, settings, load_secrets(config.data) is not None,
            self.devices, self.recorder.run, self._changed)
        self.settings.on_account = self._use_account
        self.rides = RideController(clock, self.trainer, self.recorder,
                                    self._changed, GarminFitWriter(),
                                    app_version())
        builtin = (builtin_entries() if workouts is None else
                   [Entry(w.ref, Source.BUILTIN, w.name, w, None)
                    for w in workouts])
        self.catalog = WorkoutCatalog(
            clock, provider or self._provider(), config.data / "cache" /
            "intervals.json", builtin, self._changed, zone)
        rides = config.data / "rides"
        self.space = FreeSpace(clock, config.data, free_bytes or disk_free)
        self.uploads = UploadWorker(clock, uploader or self._uploader(),
                                    rides, self._changed)
        self.calibration = CalibrationController(
            clock, self.trainer, self.recorder, config.data / "logs",
            self._changed)
        self.trainer.on_status = self.calibration.status
        self.certificate = CertificateWatch(clock, config.cert)
        self.console = Console(clock, self.devices, self.rides, self.catalog,
                               self.settings, self._changed, self.uploads,
                               self.space, rides, self.calibration,
                               self.certificate)
        self.rides.on_finished = self._finished
        self.rides.on_free_level = self._free_level
        self.trainer.on_sample = self.console.trainer_sample
        self.hrm.on_sample = self.console.hr_sample
        self.trainer.on_link = self.console.link_changed
        self.hrm.on_link = self.console.link_changed
        self.timing = TimingLog(
            clock, self.recorder.timing,
            lambda: self.rides.ride.phase in RIDING, self.trainer.pending)
        self.trainer.on_write = self.timing.written
        self.hub = Hub(clock, self.console, app_version(), self.timing)
        self.lag = LoopLagMonitor(clock)
        self.led = None if led is None else LedController(
            clock, led, self.trainer.link)
        self.web = WebServer()
        self.ports: tuple[int, int] = (0, 0)
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Start the devices and the sites."""
        config = self.config
        self.recorder.start()
        https = await self.web.start(
            https_app(config.static, self.hub.handle, config.data / "rides"),
            config.listen,
            config.https_port, tls_context(config.cert, config.key))
        http = await self.web.start(
            http_app(config.host, https, config.root_cert), config.listen,
            config.http_port)
        self.ports = (https, http)
        self._spawn(self.hub.run())
        self._spawn(self.lag.run())
        self.uploads.load()
        self._spawn(self.uploads.run())
        if self.led is not None:
            self._spawn(self.led.run())
        self._offer_interrupted()
        self.console.open_home()
        logger.info("wow %s started%s", app_version(),
                    " with simulated devices" if config.simulate else "")

    async def stop(self) -> None:
        """Stop in order, the trainer at its lowest level first."""
        self.calibration.close()
        await self.settings.close()
        await self.devices.close()
        await self.timing.close()
        await self.rides.close()
        await self.catalog.close()
        await self.hub.close()
        await self.web.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.led is not None:
            self.led.stop()
        if self.scheduler is not None:
            await self.scheduler.close()
        self.recorder.stop()
        logger.info("wow stopped; worst event-loop lag %.0f ms, %d late",
                    self.lag.worst * 1000, self.lag.late)

    def _offer_interrupted(self) -> None:
        found = find_interrupted(self.config.data / "rides")
        if found is None:
            return
        if not found.started:
            logger.info("ride %s was waiting for power: cancelled",
                        found.ride_id)
            close_cancelled(found)
            return
        logger.info("ride %s was interrupted: offered on Home",
                    found.ride_id)
        self.console.offer(found, self.recorder.boot_id)

    def _provider(self) -> WorkoutProvider | None:
        account = self._account()
        if account is None:
            logger.info("no intervals.icu account: built-in workouts only")
        return account

    def _uploader(self) -> ActivityUploader | None:
        return self._account()

    def _account(self) -> IntervalsIcu | None:
        secrets = load_secrets(self.config.data)
        if secrets is None:
            return None
        return self._account_factory(secrets)

    def _use_account(self, secrets: Secrets) -> None:
        client = self._account_factory(secrets)
        self.catalog.set_provider(client)
        self.uploads.set_uploader(client)
        self.catalog.request_refresh()

    def _finished(self, summary: Summary) -> None:
        if summary.upload == UploadState.PENDING:
            self.uploads.queue(summary.ride_id)

    def _free_level(self, pct: int) -> None:
        self.settings.keep_free_ride_level(pct)

    def _changed(self) -> None:
        self.hub.changed()

    def _spawn(self, work: Coroutine[Any, Any, None]) -> None:
        self._tasks.append(asyncio.get_running_loop().create_task(work))

    def _bluetooth(self, settings: Settings, sim_pedal_after: float
                   ) -> tuple[GattConnector, DeviceChoice]:
        chosen = DeviceChoice(
            None if settings.trainer is None else settings.trainer.address,
            None if settings.hrm is None else settings.hrm.address)
        if self._replay is not None:
            return self._logged(self._replay), DeviceChoice(
                chosen.trainer or D100_ADDRESS, chosen.hrm or HRM_ADDRESS)
        if self.config.simulate:
            faults = self._faults
            scheduler = self.scheduler = SimScheduler(self.clock)
            self.d100 = (SimD100Server(scheduler, pedal_after=sim_pedal_after)
                         if self._sim_trainer is None
                         else self._sim_trainer(scheduler))
            self.d100.faults = Faults(faults.trainer)
            strap = SimHrm200Server(scheduler)
            strap.faults = Faults(faults.strap)
            extra = ([] if self._sim_devices is None
                     else list(self._sim_devices(scheduler)))
            servers = [self.d100, strap, *bystanders(scheduler), *extra]
            for server in servers:
                server.traffic.keep_sent = False
            self.sim = SimConnector(self.clock, servers,
                                    Faults(faults.adapter))
            return self._logged(self.sim), DeviceChoice(
                chosen.trainer or D100_ADDRESS, chosen.hrm or HRM_ADDRESS)
        bleak = BleakConnector(self.config.adapter)
        connector = self._logged(bleak)
        bleak.on_stale_release = connector.stale_release
        return connector, chosen

    def _logged(self, inner: GattConnector) -> LoggingConnector:
        return LoggingConnector(inner, self.clock, self.recorder.ble,
                                lambda address: self.devices.role_of(address))


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
    led = None if config.led is None else SysfsLed(config.led)
    sys.exit(asyncio.run(serve(App(config, clock, led=led))))


if __name__ == "__main__":
    main()
