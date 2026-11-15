"""Run the spin-down calibration in the shell.

The calibration controller (3A, app/calibration_controller; ICD S-5;
APP-501 to APP-506): starts a spin-down when no ride holds the trainer,
feeds it the trainer's answer, statuses and speed, logs each result with
its date, time and bytes in `logs/calibration.jsonl`, and remembers when
the trainer asked for a spin-down.
"""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Final

from wow.app.machine_driver import MachineDriver
from wow.app.recorder import Recorder
from wow.app.recovery import read_lines
from wow.core.devices import Erg, LinkState, Resistance, TrainerSample
from wow.core.ftms_codec import STATUS_SPIN_DOWN, SpinDownStatus
from wow.core.spindown import (
    Answered, Begin, Cancel, Phase, RequestSpinDown, Result, SetLowest,
    Speed, SpinDownAction, SpinDownEvent, SpinDownMachine, Status, Tick,
)
from wow.core.timefmt import utc_text
from wow.core.vocab import Problem
from wow.ports.clock import Clock
from wow.app.ftms_trainer import FtmsTrainer

logger = logging.getLogger(__name__)

LOG_NAME: Final[str] = "calibration.jsonl"


class CalibrationController:
    """Spin-downs on the trainer."""

    def __init__(self, clock: Clock, trainer: FtmsTrainer,
                 recorder: Recorder, logs: Path,
                 on_change: Callable[[], None]) -> None:
        self._clock = clock
        self._trainer = trainer
        self._recorder = recorder
        self._log = logs / LOG_NAME
        self._on_change = on_change
        self.machine = SpinDownMachine()
        self._driver: MachineDriver[SpinDownEvent, SpinDownAction] = (
            MachineDriver(self.machine, clock, self._perform, Tick()))
        self.requested = False
        self.last: tuple[str, bool] | None = None
        trainer.on_spin_down = self._answered
        for record in read_lines(self._log):
            self.last = (str(record["utc"]), bool(record["ok"]))

    def running(self) -> bool:
        """Return whether a spin-down is under way."""
        return self.machine.phase in (Phase.STARTING, Phase.SPEED_UP,
                                      Phase.STOP_PEDALING)

    def start(self, ride_active: bool) -> str | None:
        """Start a spin-down; return the problem, if any (APP-505)."""
        if ride_active:
            return Problem.RIDE_RUNNING
        if self._trainer.link() != LinkState.CONNECTED:
            return Problem.TRAINER_MISSING
        self._driver.post(Begin())
        return None

    def cancel(self) -> None:
        """Stop a spin-down under way."""
        self._driver.post(Cancel())

    def sample(self, sample: TrainerSample) -> None:
        """Take the trainer's speed."""
        if self.running():
            self._driver.post(Speed(sample.speed_kmh))

    def status(self, data: bytes) -> None:
        """Take a Fitness Machine Status forwarded by the trainer."""
        if data[:2] == bytes([STATUS_SPIN_DOWN, SpinDownStatus.REQUESTED]):
            logger.info("the trainer asks for a spin-down")
            self.requested = True
            self._on_change()
            return
        self._driver.post(Status(data))

    def close(self) -> None:
        """Stop the time limit."""
        self._driver.close()

    def _answered(self, result: int,
                  band: tuple[float, float] | None) -> None:
        self._driver.post(Answered(result, band))

    def _perform(self, actions: list[SpinDownAction]) -> None:
        for action in actions:
            match action:
                case RequestSpinDown():
                    self._trainer.spin_down()
                case SetLowest():
                    self._lowest()
                case Result(ok=ok, outcome=outcome, data=data):
                    self._result(ok, outcome, data)
        self._on_change()

    def _lowest(self) -> None:
        capabilities = self._trainer.capabilities()
        if capabilities is None:
            return
        if capabilities.resistance is not None:
            self._trainer.set_command(
                Resistance(capabilities.resistance.minimum))
        elif capabilities.power is not None:
            self._trainer.set_command(Erg(capabilities.power.minimum))

    def _result(self, ok: bool, outcome: str, data: bytes) -> None:
        utc = utc_text(self._clock.utc())
        self.last = (utc, ok)
        if ok:
            self.requested = False
        logger.info("spin-down %s: %s", outcome, data.hex())
        line = json.dumps({"utc": utc, "ok": ok, "outcome": outcome,
                           "hex": data.hex()})
        path = self._log

        def append() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

        self._recorder.run(append)
