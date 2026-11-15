"""Carry the display commands to the controllers.

The rider's console: which screen is open, the display's commands
carried to the controllers, and the view state put together from
core/view (ICD IF-06, 4.6.3 and 4.6.5; IM-23).

Home with today's, the library's and the built-in workouts, Pre-ride,
the ride screen from Start to Finish, and the Summary after Finish.
"""

import dataclasses
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from wow.app.calibration_controller import CalibrationController
from wow.app.config import RideSettings
from wow.app.device_manager import DeviceManager
from wow.app.history import (
    delete_ride, kept_rides, metrics_of, read_meta, ride_path,
)
from wow.app.housekeeping import FreeSpace
from wow.app.recovery import Interrupted, outage, resumption
from wow.app.ride_controller import RideController, RideSetup, Summary
from wow.app.upload_worker import UploadWorker
from wow.app.workout_catalog import Entry, Source, WorkoutCatalog
from wow.core.devices import HrSample, LinkState, TrainerSample
from wow.core.plan import Plan, make_plan
from wow.core.view import (
    Json, Latest, PowerAverage, calibration_screen, history_entry,
    history_screen, home_screen,
    plan_message, pre_ride_screen, recovery_offer, ride_screen,
    ride_warnings, summary_screen, view_state, workout_card,
)
from wow.ports.clock import Clock
from wow.core.ride import ACTIVE, RidePhase
from wow.core.workout import Workout
from wow.core.vocab import (
    CommandName, Mode, Problem, Screen, UploadState, WarningKind,
)
from wow.core.workout import free_ride_workout

logger = logging.getLogger(__name__)


class Console:
    """The rider's console."""

    def __init__(self, clock: Clock, devices: DeviceManager,
                 rides: RideController, catalog: WorkoutCatalog,
                 settings: RideSettings, on_change: Callable[[], None],
                 uploads: UploadWorker, space: FreeSpace,
                 rides_dir: Path, calibration: CalibrationController
                 ) -> None:
        self._clock = clock
        self._devices = devices
        self._rides = rides
        rides.on_ended = self.ride_ended
        self._catalog = catalog
        self._settings = settings
        self._ftp = settings.ftp
        self._on_change = on_change
        self._screen = Screen.HOME
        self._plan: Plan | None = None
        self._entry: Entry | None = None
        self._block_modes: list[Mode] = []
        self._power = PowerAverage()
        self._hr = Latest()
        self._data_mono: float | None = None
        self._interrupted: Interrupted | None = None
        self._boot = ""
        self._uploads = uploads
        self._space = space
        self._rides_dir = rides_dir
        self._past: Summary | None = None
        self._calibration = calibration

    @property
    def screen(self) -> str:
        """Return the open screen."""
        return self._screen

    def plan(self) -> Json | None:
        """Return the plan message, at the ride's intensity while riding."""
        if self._plan is None:
            return None
        intensity = (self._rides.ride.intensity_pct
                     if self._screen == Screen.RIDE else 100)
        return plan_message(self._plan, intensity_pct=intensity)

    def view(self) -> Json:
        """Return the current view state."""
        now = self._clock.monotonic()
        data_ms = None if self._data_mono is None else round(
            self._data_mono * 1000, 1)
        trainer = self._devices.trainer.link()
        hrm = self._devices.hrm.link()
        battery = self._devices.hrm.battery_pct()
        return view_state(self._screen_state(now, trainer), trainer, hrm,
                          battery, self._warnings(), data_ms)

    def command(self, name: str, args: Mapping[str, Any]) -> str | None:
        """Carry out a command; return the problem, if any."""
        if name not in set(CommandName):
            return Problem.BAD_REQUEST
        handler = getattr(self, f"_{self._screen}_{name}", None)
        if handler is None:
            return Problem.INVALID_STATE
        result: str | None = handler(args)
        self._on_change()
        return result

    def trainer_sample(self, sample: TrainerSample) -> None:
        """Take a trainer reading."""
        self._power.add(sample.mono, sample.power)
        self._data_mono = sample.mono
        self._rides.trainer_sample(sample)
        self._calibration.sample(sample)
        self._on_change()

    def hr_sample(self, sample: HrSample) -> None:
        """Take a heart-rate reading."""
        self._hr.add(sample.mono, sample.heart_rate_bpm)
        self._data_mono = sample.mono
        self._rides.hr_sample(sample)
        self._on_change()

    def link_changed(self, _state: LinkState) -> None:
        """Pass the device links on to the ride."""
        self._rides.link_changed(self._devices.trainer.link(),
                                 self._devices.hrm.link())
        self._on_change()

    def set_free_ride_level(self, pct: int) -> None:
        """Keep the free-ride level the rider chose (APP-705)."""
        self._settings = dataclasses.replace(self._settings,
                                             free_ride_level_pct=pct)

    def offer(self, found: Interrupted, boot_id: str) -> None:
        """Offer on Home to continue or finish an interrupted ride."""
        self._interrupted, self._boot = found, boot_id

    def open_home(self) -> None:
        """Show Home and refresh the workouts."""
        self._screen, self._plan, self._entry = Screen.HOME, None, None
        self._catalog.request_refresh()

    def ride_ended(self, cause: RidePhase) -> None:
        """Handle the end of a ride."""
        logger.info("ride ended: %s", cause)
        if cause == RidePhase.CANCELLED:
            self._screen = Screen.PRE_RIDE
            self._devices.open_pre_ride()
        elif self._rides.summary is not None:
            self._screen = Screen.SUMMARY
        else:
            self.open_home()

    def _screen_state(self, now: float, trainer: LinkState) -> Json:
        if self._screen == Screen.RIDE:
            return ride_screen(self._rides.ride, now, self._power.value(now),
                               self._hr.value(now))
        if self._screen == Screen.PRE_RIDE and self._plan is not None:
            return pre_ride_screen(self._plan, trainer, self._block_modes,
                                   self._is_free())
        summary = self._past or self._rides.summary
        if self._screen == Screen.SUMMARY and summary is not None:
            return summary_screen(summary.ride_id, summary.title,
                                  summary.start_utc, summary.metrics,
                                  self._upload(summary.ride_id,
                                               summary.upload),
                                  self._past is not None)
        if self._screen == Screen.HISTORY:
            return history_screen(self._history(), self._space.free_mb())
        if self._screen == Screen.CALIBRATION:
            return self._calibration_state(now, trainer)
        catalog = self._catalog
        return home_screen([self._card(e) for e in catalog.builtin],
                           [self._card(e) for e in catalog.today()],
                           [self._card(e) for e in catalog.library()],
                           self._recovery(now))

    def _recovery(self, now: float) -> Json | None:
        found = self._interrupted
        if found is None:
            return None
        start = found.meta.get("start_utc")
        return recovery_offer(found.ride_id,
                              None if start is None else str(start),
                              self._outage(found, now))

    def _outage(self, found: Interrupted, now: float) -> float | None:
        return outage(found, now, self._clock.utc(), self._boot,
                      self._clock.synchronised())

    def _calibration_state(self, now: float, trainer: LinkState) -> Json:
        machine = self._calibration.machine
        blocked = (Problem.RIDE_RUNNING if self._ride_active() else
                   None if trainer == LinkState.CONNECTED
                   else Problem.TRAINER_MISSING)
        return calibration_screen(machine.phase, machine.band_kmh,
                                  machine.speed_kmh, machine.elapsed(now),
                                  self._calibration.last, blocked)

    def _ride_active(self) -> bool:
        return self._rides.ride.phase in ACTIVE

    def _upload(self, ride_id: str, known: str) -> str:
        return self._uploads.state(ride_id) or known

    def _history(self) -> list[Json]:
        entries = []
        for meta in kept_rides(self._rides_dir):
            ride_id = str(meta["ride_id"])
            metrics = meta.get("metrics")
            entries.append(history_entry(
                ride_id, meta.get("start_utc"), str(meta.get("title")),
                None if not isinstance(metrics, dict) else metrics_of(
                    metrics),
                self._upload(ride_id, str(meta.get("upload", "off")))))
        return entries

    def _card(self, item: Entry) -> Json:
        plan = (None if item.workout is None
                else make_plan(item.workout, self._ftp))
        return workout_card(item.workout, plan, item.source, item.ref,
                            item.name)

    def _warnings(self) -> list[Json]:
        trainer = sorted(self._devices.trainer.warnings())
        if self._screen == Screen.RIDE:
            return ride_warnings(self._rides.ride, trainer)
        warnings: list[Json] = [{"kind": kind} for kind in trainer]
        offline = self._catalog.offline_since
        if self._screen == Screen.HOME and offline is not None:
            warnings.append({"kind": WarningKind.WORKOUTS_OFFLINE,
                             "downloaded_utc": offline})
        if self._screen == Screen.HOME and self._calibration.requested and (
                not self._ride_active()):
            warnings.append({"kind": WarningKind.SPINDOWN_REQUESTED})
        if self._screen in (Screen.HOME, Screen.HISTORY) and (
                self._space.low()):
            warnings.append({"kind": WarningKind.STORAGE_LOW,
                             "free_mb": self._space.free_mb()})
        return warnings

    def _home_open_workout(self, args: Mapping[str, Any]) -> str | None:
        item = self._catalog.find(str(args.get("ref")))
        if item is None:
            return Problem.BAD_REQUEST
        if item.workout is None:
            return Problem.INVALID_STATE
        self._open_pre_ride(item, item.workout)
        return None

    def _home_recovery_continue(self, _args: Mapping[str, Any]
                                ) -> str | None:
        return self._recover(True)

    def _home_recovery_finish(self, _args: Mapping[str, Any]
                              ) -> str | None:
        return self._recover(False)

    def _recover(self, keep_riding: bool) -> str | None:
        found = self._interrupted
        if found is None or self._rides.ride.phase in ACTIVE:
            return Problem.INVALID_STATE
        now = self._clock.monotonic()
        gone = self._outage(found, now)
        if keep_riding and gone is None:
            return Problem.INVALID_STATE
        self._interrupted = None
        workout = found.setup.workout
        source = Source(found.setup.source)
        self._entry = Entry(workout.ref, source, workout.name, workout, None)
        self._plan = make_plan(workout, found.setup.ftp)
        if keep_riding:
            self._screen = Screen.RIDE
            self._devices.open_pre_ride()
        self._rides.recover(resumption(found, now, gone, keep_riding),
                            keep_riding)
        return None

    def _home_open_free_ride(self, _args: Mapping[str, Any]) -> str | None:
        workout = free_ride_workout()
        self._open_pre_ride(Entry(workout.ref, Source.FREE_RIDE,
                                  workout.name, workout, None), workout)
        return None

    def _open_pre_ride(self, item: Entry, workout: Workout) -> None:
        self._entry = item
        self._plan = make_plan(workout, self._ftp)
        self._block_modes = [Mode.ERG] * len(workout.blocks)
        self._screen = Screen.PRE_RIDE
        self._devices.open_pre_ride()

    def _is_free(self) -> bool:
        return self._entry is not None and (
            self._entry.source == Source.FREE_RIDE)

    def _pre_ride_set_block_mode(self, args: Mapping[str, Any]
                                 ) -> str | None:
        block, mode = args.get("block"), args.get("mode")
        if self._is_free() or not isinstance(block, int) or not (
                0 <= block < len(self._block_modes)) or mode not in set(Mode):
            return Problem.BAD_REQUEST
        self._block_modes[block] = Mode(mode)
        return None

    def _pre_ride_back(self, _args: Mapping[str, Any]) -> str | None:
        self.open_home()
        return None

    def _summary_back(self, _args: Mapping[str, Any]) -> str | None:
        if self._past is not None:
            self._past = None
            self._screen = Screen.HISTORY
        else:
            self.open_home()
        return None

    def _home_open_calibration(self, _args: Mapping[str, Any]
                               ) -> str | None:
        self._screen = Screen.CALIBRATION
        self._devices.open_pre_ride()
        return None

    def _calibration_calibration_start(self, _args: Mapping[str, Any]
                                       ) -> str | None:
        problem = self._calibration.start(self._ride_active())
        return None if problem is None else Problem.INVALID_STATE

    def _calibration_calibration_cancel(self, _args: Mapping[str, Any]
                                        ) -> str | None:
        self._calibration.cancel()
        return None

    def _calibration_back(self, _args: Mapping[str, Any]) -> str | None:
        self._calibration.cancel()
        self.open_home()
        return None

    def _home_open_history(self, _args: Mapping[str, Any]) -> str | None:
        self._screen = Screen.HISTORY
        return None

    def _history_back(self, _args: Mapping[str, Any]) -> str | None:
        self.open_home()
        return None

    def _history_open_ride(self, args: Mapping[str, Any]) -> str | None:
        ride_dir = ride_path(self._rides_dir, str(args.get("ride_id")))
        meta = None if ride_dir is None else read_meta(ride_dir)
        metrics = None if meta is None else meta.get("metrics")
        if meta is None or not isinstance(metrics, dict):
            return Problem.BAD_REQUEST
        self._past = Summary(str(meta["ride_id"]), str(meta.get("title")),
                             str(meta.get("start_utc")), metrics_of(metrics),
                             UploadState(str(meta.get("upload", "off"))))
        self._screen = Screen.SUMMARY
        return None

    def _history_upload_retry(self, args: Mapping[str, Any]) -> str | None:
        return self._retry(str(args.get("ride_id")))

    def _summary_upload_retry(self, args: Mapping[str, Any]) -> str | None:
        return self._retry(str(args.get("ride_id")))

    def _retry(self, ride_id: str) -> str | None:
        return None if self._uploads.retry(ride_id) else Problem.BAD_REQUEST

    def _history_delete_ride(self, args: Mapping[str, Any]) -> str | None:
        return self._delete(str(args.get("ride_id")))

    def _summary_delete_ride(self, args: Mapping[str, Any]) -> str | None:
        if self._past is None or self._past.ride_id != args.get("ride_id"):
            return Problem.INVALID_STATE
        problem = self._delete(self._past.ride_id)
        if problem is None:
            self._past = None
            self._screen = Screen.HISTORY
        return problem

    def _delete(self, ride_id: str) -> str | None:
        interrupted = self._interrupted
        busy = {self._rides.ride_id(),
                None if interrupted is None else interrupted.ride_id}
        if ride_id in busy or self._uploads.state(ride_id) == (
                UploadState.UPLOADING):
            return Problem.INVALID_STATE
        return None if delete_ride(self._rides_dir, ride_id) else (
            Problem.BAD_REQUEST)

    def _pre_ride_start(self, _args: Mapping[str, Any]) -> str | None:
        if self._plan is None or self._entry is None:
            return Problem.INVALID_STATE
        settings = self._settings
        refused = self._rides.start(RideSetup(
            self._plan.workout, self._ftp, settings.lead_time,
            raw=self._entry.raw, source=self._entry.source,
            zones_pct=settings.zones_pct,
            free_ride_level_pct=settings.free_ride_level_pct,
            upload_on=settings.upload_on,
            block_modes=tuple(self._block_modes)))
        if refused is not None:
            logger.info("start refused: %s", refused)
            return Problem.INVALID_STATE
        self._screen = Screen.RIDE
        return None

    def _ride_cancel_start(self, _args: Mapping[str, Any]) -> str | None:
        return Problem.INVALID_STATE if self._rides.cancel() else None

    def _ride_finish(self, _args: Mapping[str, Any]) -> str | None:
        return _refusal(self._rides.finish())

    def _ride_discard(self, _args: Mapping[str, Any]) -> str | None:
        return _refusal(self._rides.discard())

    def _ride_pause(self, _args: Mapping[str, Any]) -> str | None:
        return _refusal(self._rides.pause())

    def _ride_resume(self, _args: Mapping[str, Any]) -> str | None:
        return _refusal(self._rides.resume())

    def _ride_skip(self, _args: Mapping[str, Any]) -> str | None:
        return _refusal(self._rides.skip())

    def _ride_intensity(self, args: Mapping[str, Any]) -> str | None:
        step = _step(args)
        return step if isinstance(step, str) else _refusal(
            self._rides.intensity(step))

    def _ride_resistance(self, args: Mapping[str, Any]) -> str | None:
        step = _step(args)
        return step if isinstance(step, str) else _refusal(
            self._rides.resistance(step))

    def _ride_free_ride_power(self, args: Mapping[str, Any]) -> str | None:
        step = _step(args)
        return step if isinstance(step, str) else _refusal(
            self._rides.free_ride_power(step))

    def _ride_switch_mode(self, args: Mapping[str, Any]) -> str | None:
        mode = args.get("mode")
        if mode not in set(Mode):
            return Problem.BAD_REQUEST
        power = self._power.value(self._clock.monotonic())
        return _refusal(self._rides.switch_mode(Mode(mode), power))


def _refusal(problem: str | None) -> str | None:
    return None if problem is None else Problem.INVALID_STATE


def _step(args: Mapping[str, Any]) -> int | str:
    step = args.get("step")
    if step not in (1, -1) or isinstance(step, bool):
        return Problem.BAD_REQUEST
    return int(step)
