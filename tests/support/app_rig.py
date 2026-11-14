"""The whole app of `wow --sim` for L3 and L5 tests: the composition root
with the simulated D100 and HRM 200, the test certificate and a data
directory of the test's own."""

import json
from datetime import date, tzinfo
from pathlib import Path
from typing import Any

from wow.adapters.ble_sim import SimFaults
from wow.adapters.clock_stepped import SteppedClock
from wow.app.config import Config
from wow.app.main import App
from wow.ports.workouts import ProviderError, WorkoutProvider

ROOT = Path(__file__).resolve().parents[2]
TLS = ROOT / "testdata" / "tls"
INDEX = "<!doctype html><title>wow test page</title>\n"
ERG_CHECK = "builtin:erg-check"


def app_config(tmp: Path) -> Config:
    static = tmp / "static"
    (static / "assets").mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text(INDEX, encoding="utf-8")
    (static / "assets" / "app-1234.js").write_text("export {}\n",
                                                   encoding="utf-8")
    return Config(
        adapter="hci0", simulate=True, host="wow.local", https_port=0,
        http_port=0, cert=TLS / "server.crt", key=TLS / "server.key",
        root_cert=TLS / "root.crt", data=tmp / "data", static=static,
        listen="127.0.0.1")


def ride_dirs(config: Config) -> list[Path]:
    rides = config.data / "rides"
    return sorted(rides.iterdir()) if rides.exists() else []


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line]


async def ride_erg_check(tmp: Path, finish_after: float = 400.0
                         ) -> tuple[App, Path]:
    """Opens the ERG check, starts, pedals 3 s later, finishes, shuts
    down: the files of a short ride, on the stepped clock."""
    return await ride_ref(tmp, ERG_CHECK, finish_after)


async def ride_ref(tmp: Path, ref: str, finish_after: float,
                   provider: WorkoutProvider | None = None,
                   clock: SteppedClock | None = None,
                   zone: tzinfo | None = None) -> tuple[App, Path]:
    """Rides a workout of the catalog from Home to Finish on the stepped
    clock and shuts down: the files of the ride."""
    clock = clock or SteppedClock()
    app = App(app_config(tmp), clock, provider=provider, zone=zone)
    app.recorder.start()
    try:
        if provider is not None:
            await clock.drive(app.catalog.refresh(), limit=60.0)
        assert app.console.command("open_workout", {"ref": ref}) is None
        await clock.advance(15.0)
        assert app.console.command("start", {}) is None
        await clock.advance(finish_after)
        assert app.console.command("finish", {}) is None
        await clock.advance(5.0)
        await clock.drive(app.devices.close(), limit=60.0)
        await clock.drive(app.rides.close(), limit=60.0)
        if app.scheduler is not None:
            await app.scheduler.close()
    finally:
        app.recorder.stop()
    (ride,) = ride_dirs(app.config)
    return app, ride


class RecordedProvider:
    """Workout provider that answers with recorded files, or fails."""

    def __init__(self, events: list[Any], workouts: list[Any]) -> None:
        self.events, self.workouts = events, workouts
        self.failing = False
        self.asked: list[tuple[date, date]] = []

    async def planned(self, oldest: date, newest: date) -> list[Any]:
        self.asked.append((oldest, newest))
        if self.failing:
            raise ProviderError("offline")
        return self.events

    async def library(self) -> list[Any]:
        if self.failing:
            raise ProviderError("offline")
        return self.workouts


class AppSession:
    """The app on the stepped clock, driven command by command."""

    def __init__(self, tmp: Path, provider: WorkoutProvider | None = None,
                 sim_pedal_after: float = 3.0,
                 sim_faults: SimFaults = SimFaults()) -> None:
        self.clock = SteppedClock()
        self.app = App(app_config(tmp), self.clock, provider=provider,
                       sim_pedal_after=sim_pedal_after, sim_faults=sim_faults)
        self.app.recorder.start()

    async def begin(self, ref: str | None) -> None:
        """Open a workout (or a free ride with None) and start it."""
        if self.app.catalog is not None and ref is not None and (
                not ref.startswith("builtin:")):
            await self.clock.drive(self.app.catalog.refresh(), limit=60.0)
        if ref is None:
            assert self.command("open_free_ride") is None
        else:
            assert self.command("open_workout", ref=ref) is None
        await self.clock.advance(15.0)
        assert self.command("start") is None

    def command(self, name: str, **args: Any) -> str | None:
        """Carry out a display command; return the problem, if any."""
        return self.app.console.command(name, args)

    def ride_time(self) -> float:
        """Return the ride time now."""
        return self.app.rides.ride.ride_time(self.clock.monotonic())

    async def until(self, t_ride: float) -> None:
        """Move the clock on until the ride time is reached."""
        while self.ride_time() < t_ride - 1e-6:
            await self.clock.advance(min(1.0, t_ride - self.ride_time()))

    async def close(self) -> Path:
        """Shut down and return the ride directory."""
        await self.clock.advance(5.0)
        await self.clock.drive(self.app.devices.close(), limit=60.0)
        await self.clock.drive(self.app.rides.close(), limit=60.0)
        if self.app.scheduler is not None:
            await self.app.scheduler.close()
        self.app.recorder.stop()
        return ride_dirs(self.app.config)[-1]
