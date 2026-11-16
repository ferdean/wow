"""The status LED (T-HK-03, S-LED-01)."""

from pathlib import Path

import pytest

from tests.support.app_rig import ERG_CHECK, app_config
from wow.adapters.clock_stepped import SteppedClock
from wow.adapters.led_sysfs import SysfsLed
from wow.app.main import App


class FakeLed:
    def __init__(self) -> None:
        self.states: list[bool] = []

    def set(self, on: bool) -> None:
        self.states.append(on)


@pytest.mark.case("T-HK-03")
@pytest.mark.req("APP-826")
@pytest.mark.asyncio
async def test_blinking_without_trainer_steady_with_it_off_after(
        tmp_path: Path) -> None:
    clock = SteppedClock()
    led = FakeLed()
    app = App(app_config(tmp_path), clock, led=led)
    await app.start()
    await clock.advance(3.0)
    blinking = led.states[-6:]
    assert blinking == [True, False] * 3 or blinking == [False, True] * 3
    assert app.console.command("open_workout", {"ref": ERG_CHECK}) is None
    await clock.advance(15.0)
    del led.states[:]
    await clock.advance(3.0)
    assert led.states and all(led.states)
    await clock.drive(app.stop(), limit=60.0)
    assert led.states[-1] is False


@pytest.mark.case("S-LED-01")
def test_sysfs_led_writes_trigger_and_brightness(tmp_path: Path) -> None:
    (tmp_path / "max_brightness").write_text("255\n")
    led = SysfsLed(tmp_path)
    assert (tmp_path / "trigger").read_text() == "none"
    led.set(True)
    assert (tmp_path / "brightness").read_text() == "255"
    led.set(False)
    assert (tmp_path / "brightness").read_text() == "0"
    gone = SysfsLed(tmp_path / "missing")
    gone.set(True)
    assert not (tmp_path / "missing").exists()
