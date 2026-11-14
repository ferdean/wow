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
from typing import Any

from wow.app.config import RideSettings
from wow.app.device_manager import DeviceManager
from wow.app.ride_controller import RideController, RideSetup
from wow.app.workout_catalog import Entry, Source, WorkoutCatalog
from wow.core.devices import HrSample, LinkState, TrainerSample
from wow.core.plan import Plan, make_plan
from wow.core.view import (
    Json, Latest, PowerAverage, home_screen, plan_message, pre_ride_screen,
    ride_screen, ride_warnings, summary_screen, view_state, workout_card,
)
from wow.ports.clock import Clock
from wow.core.ride import RidePhase
from wow.core.workout import Workout
from wow.core.vocab import CommandName, Mode, Problem, Screen, WarningKind
from wow.core.workout import free_ride_workout

logger = logging.getLogger(__name__)


class Console:
    """The rider's console."""

    def __init__(self, clock: Clock, devices: DeviceManager,
                 rides: RideController, catalog: WorkoutCatalog,
                 settings: RideSettings,
                 on_change: Callable[[], None]) -> None:
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

    @property
    def screen(self) -> str:
        """Return the open screen."""
        return self._screen

    def plan(self) -> Json | None:
        """Return the plan message of the ride, if any."""
        return None if self._plan is None else plan_message(self._plan)

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
        summary = self._rides.summary
        if self._screen == Screen.SUMMARY and summary is not None:
            return summary_screen(summary.ride_id, summary.title,
                                  summary.start_utc, summary.metrics,
                                  summary.upload)
        catalog = self._catalog
        return home_screen([self._card(e) for e in catalog.builtin],
                           [self._card(e) for e in catalog.today()],
                           [self._card(e) for e in catalog.library()])

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
        return warnings

    def _home_open_workout(self, args: Mapping[str, Any]) -> str | None:
        item = self._catalog.find(str(args.get("ref")))
        if item is None:
            return Problem.BAD_REQUEST
        if item.workout is None:
            return Problem.INVALID_STATE
        self._open_pre_ride(item, item.workout)
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
        self.open_home()
        return None

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
