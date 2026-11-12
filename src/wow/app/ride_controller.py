"""Run the ride state machine in the shell.

Runs the ride state machine: rider commands and the trainer's power in,
trainer commands and journal records out (3A, app/ride_controller;
APP-301, APP-304, APP-801).
"""

import asyncio
from collections.abc import Callable
from pathlib import Path

from wow.app.machine_driver import MachineDriver
from wow.app.recorder import Recorder
from wow.core.devices import LinkState, TrainerCapabilities, TrainerSample
from wow.core.ride import (
    CancelStart, Ended, Finish, Journal, PowerSeen, Refused, Ride,
    RideAction, RideEvent, RidePhase, SetTrainer, Start, Tick, TrainerLink,
)
from wow.core.timefmt import utc_text
from wow.core.workout import Workout
from wow.ports.clock import Clock
from wow.ports.devices import Trainer
from typing import Final

NO_CAPABILITIES: Final[TrainerCapabilities] = TrainerCapabilities(
    None, None, False, False)
RIDE_LOG_TAIL: Final[float] = 3.0


class RideController:
    """Rides: commands and power in, commands and journal out."""

    def __init__(self, clock: Clock, trainer: Trainer, recorder: Recorder,
                 on_change: Callable[[], None]) -> None:
        self._clock = clock
        self._trainer = trainer
        self._recorder = recorder
        self._on_change = on_change
        self.on_ended: Callable[[RidePhase], None] = lambda _cause: None
        self.ride = Ride()
        self._driver: MachineDriver[RideEvent, RideAction] = MachineDriver(
            self.ride, clock, self._perform, Tick())
        self._refusal: str | None = None
        self._ride_dir: Path | None = None
        self._tails: set[asyncio.Task[None]] = set()

    def start(self, workout: Workout, ftp: int,
              lead_time: float) -> str | None:
        """Start a ride; return the problem, if any."""
        connected = self._trainer.link() == LinkState.CONNECTED
        self._driver.post(TrainerLink(connected))
        capabilities = self._trainer.capabilities() or NO_CAPABILITIES
        return self._post(Start(workout, ftp, capabilities, lead_time))

    def cancel(self) -> str | None:
        """Cancel the wait for power; return the problem, if any."""
        return self._post(CancelStart())

    def finish(self) -> str | None:
        """Finish the ride; return the problem, if any."""
        return self._post(Finish())

    def trainer_sample(self, sample: TrainerSample) -> None:
        """Take a trainer reading."""
        if self.ride.phase == RidePhase.ARMED and sample.power is not None:
            self._driver.post(PowerSeen(sample.power))

    async def close(self) -> None:
        """Stop the ride machine and close the files."""
        self._driver.close()
        await asyncio.gather(*self._tails, return_exceptions=True)

    def _post(self, event: RideEvent) -> str | None:
        self._refusal = None
        self._driver.post(event)
        return self._refusal

    def _perform(self, actions: list[RideAction]) -> None:
        if any(isinstance(a, Journal) and a.event == "armed"
               for a in actions):
            stamp = self._clock.utc().strftime("%Y-%m-%dT%H%M%SZ")
            self._ride_dir = self._recorder.open_ride(stamp)
        for action in actions:
            match action:
                case SetTrainer(command=command):
                    self._trainer.set_command(command)
                case Journal():
                    self._journal(action)
                case Refused(reason=reason):
                    self._refusal = reason
                case Ended(cause=cause):
                    self._end(cause)
        self._on_change()

    def _end(self, cause: RidePhase) -> None:
        ride, self._ride_dir = self._ride_dir, None
        if ride is not None:
            task = asyncio.get_running_loop().create_task(self._tail(ride))
            self._tails.add(task)
            task.add_done_callback(self._tails.discard)
        self.on_ended(cause)

    async def _tail(self, ride: Path) -> None:
        try:
            await self._clock.sleep_until(
                self._clock.monotonic() + RIDE_LOG_TAIL)
        finally:
            self._recorder.close_ride(ride)

    def _journal(self, record: Journal) -> None:
        self._recorder.journal({
            "t_ride": record.t_ride,
            "utc": utc_text(self._clock.utc()),
            "mono_ms": round(self._clock.monotonic() * 1000, 1),
            "boot_id": self._recorder.boot_id,
            "type": record.event,
            **record.data,
        })
