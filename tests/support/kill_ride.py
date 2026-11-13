"""A real-time simulated ride for T-REC-03, killed by the test.

    python -m tests.support.kill_ride <directory>

Starts the app with the simulated devices, rides the built-in 30/30 ERG
check from Pre-ride, prints "started" and rides on until killed.
"""

import asyncio
import sys
from pathlib import Path

from tests.support.app_rig import ERG_CHECK, app_config
from wow.adapters.clock_system import SystemClock
from wow.app.main import App
from wow.core.devices import LinkState


async def ride(directory: Path) -> None:
    app = App(app_config(directory), SystemClock(None), sim_pedal_after=1.0)
    await app.start()
    assert app.console.command("open_workout", {"ref": ERG_CHECK}) is None
    while app.devices.trainer.link() != LinkState.CONNECTED:
        await asyncio.sleep(0.1)
    assert app.console.command("start", {}) is None
    print("started", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(ride(Path(sys.argv[1])))
