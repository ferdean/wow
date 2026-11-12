"""The whole app of `wow --sim` for L3 and L5 tests: the composition root
with the simulated D100 and HRM 200, the test certificate and a data
directory of the test's own."""

import json
from pathlib import Path
from typing import Any

from wow.adapters.clock_stepped import SteppedClock
from wow.app.config import Config
from wow.app.main import App

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
    clock = SteppedClock()
    app = App(app_config(tmp), clock)
    app.recorder.start()
    try:
        assert app.console.command("open_workout", {"ref": ERG_CHECK}) is None
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
