"""Show the app's state on the status LED.

The status LED (3A; APP-826): blinking while no trainer is connected,
steady while the trainer is connected, off once the app stops.
"""

from collections.abc import Callable
from typing import Final

from wow.core.devices import LinkState
from wow.ports.clock import Clock
from wow.ports.led import StatusLed

BLINK: Final[float] = 0.5


class LedController:
    """Keeps the LED in step with the trainer link."""

    def __init__(self, clock: Clock, led: StatusLed,
                 trainer: Callable[[], LinkState]) -> None:
        self._clock = clock
        self._led = led
        self._trainer = trainer
        self._lit = False

    async def run(self) -> None:
        """Update the LED until cancelled."""
        while True:
            if self._trainer() == LinkState.CONNECTED:
                self._lit = True
            else:
                self._lit = not self._lit
            self._led.set(self._lit)
            await self._clock.sleep_until(self._clock.monotonic() + BLINK)

    def stop(self) -> None:
        """Switch the LED off."""
        self._lit = False
        self._led.set(False)
