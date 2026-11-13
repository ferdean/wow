"""The links of both devices in the Pre-ride view (L3)."""

from pathlib import Path

import pytest

from tests.support.app_rig import ERG_CHECK, app_config
from wow.adapters.ble_sim import SimHrm200Server
from wow.adapters.clock_stepped import SteppedClock
from wow.app.main import App


@pytest.mark.case("T-VIEW-11")
@pytest.mark.req("APP-102")
@pytest.mark.asyncio
async def test_pre_ride_shows_each_device_state(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SimHrm200Server, "advertising", lambda self: False)
    clock = SteppedClock()
    app = App(app_config(tmp_path), clock)
    app.recorder.start()
    seen = []
    try:
        assert app.console.command("open_workout", {"ref": ERG_CHECK}) is None
        for _ in range(40):
            seen.append(tuple(app.console.view()["links"].values()))
            await clock.advance(0.5)
        await clock.drive(app.devices.close(), limit=60.0)
        await clock.drive(app.rides.close(), limit=60.0)
    finally:
        app.recorder.stop()
    assert seen[0] == ("searching", "searching")
    assert ("connected", "searching") in seen
    assert seen[-1] == ("connected", "not_found")
    assert app.console.view()["screen"]["name"] == "pre_ride"
