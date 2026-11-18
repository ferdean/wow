"""Carry the display commands to the controllers.

The rider's console: which screen is open, the display's commands
carried to the controllers, and the view state put together from
core/view (ICD IF-06, 4.6.3 and 4.6.5; IM-23).

Home with today's, the library's and the built-in workouts, Pre-ride
with the route choice, the ride screen from Start to Finish, the Summary
after Finish, past rides, Calibration and Settings; the devices are kept
while Pre-ride, a ride or Calibration is open (APP-110). Rides on
simulated devices are never uploaded (APP-613), to intervals.icu or to
Garmin Connect.
"""

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from wow.app.calibration_controller import CalibrationController
from wow.app.device_manager import DeviceManager
from wow.app.history import (
    delete_ride, kept_rides, metrics_of, read_meta, ride_path,
)
from wow.app.housekeeping import CertificateWatch, FreeSpace
from wow.app.recovery import Interrupted, outage, resumption
from wow.app.ride_controller import (
    RideController, RideSetup, RouteSummary, Summary,
)
from wow.app.route_catalog import RouteCatalog
from wow.app.settings_panel import SettingsPanel
from wow.app.upload_worker import UploadWorker
from wow.app.workout_catalog import Entry, Source, WorkoutCatalog
from wow.core.devices import HrSample, LinkState, TrainerSample
from wow.core.plan import Plan, make_plan
from wow.core.numbers import round_half_up
from wow.core.view import (
    Json, Latest, PowerAverage, battery_warning, calibration_screen,
    certificate_warning, clock_warning, history_entry, history_screen,
    home_screen, plan_message, pre_ride_screen, recovery_offer, ridden_route,
    ride_screen, ride_warnings, route_live, route_map, route_option,
    summary_screen, view_state, workout_card,
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
                 panel: SettingsPanel, on_change: Callable[[], None],
                 uploads: UploadWorker, garmin_uploads: UploadWorker,
                 space: FreeSpace,
                 rides_dir: Path, calibration: CalibrationController,
                 certificate: CertificateWatch, routes: RouteCatalog,
                 uploads_allowed: bool = True) -> None:
        self._clock = clock
        self._devices = devices
        self._rides = rides
        rides.on_ended = self.ride_ended
        self._catalog = catalog
        self._panel = panel
        self._certificate = certificate
        self._on_change = on_change
        self._screen = Screen.HOME
        self._plan: Plan | None = None
        self._entry: Entry | None = None
        self._block_modes: list[Mode] = []
        self._power = PowerAverage()
        self._hr = Latest()
        self._cadence = Latest()
        self._unsynced_at_start = False
        self._data_mono: float | None = None
        self._interrupted: Interrupted | None = None
        self._boot = ""
        self._uploads = uploads
        self._space = space
        self._rides_dir = rides_dir
        self._past: Summary | None = None
        self._calibration = calibration
        self._routes = routes
        self._uploads_allowed = uploads_allowed
        self._garmin_uploads = garmin_uploads
        self._map: Json | None = None

    @property
    def screen(self) -> str:
        """Return the open screen."""
        return self._screen

    def plan(self) -> Json | None:
        """Return the plan message, at the ride's intensity while riding."""
        if self._plan is None:
            return None
        riding = self._screen == Screen.RIDE
        intensity = self._rides.ride.intensity_pct if riding else 100
        return plan_message(self._plan, self._zones(riding),
                            intensity_pct=intensity)

    def route(self) -> Json | None:
        """Return the route message while a ride on a route is shown."""
        rider, setup = self._rides.rider, self._rides.setup
        if self._screen != Screen.RIDE or rider is None or setup is None or (
                setup.route is None):
            return None
        choice = setup.route
        if self._map is None or self._map["route_id"] != choice.route_id:
            self._map = route_map(choice.route_id, choice.name, rider.route)
        return self._map

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
        self._hold()
        self._on_change()
        return result

    def trainer_sample(self, sample: TrainerSample) -> None:
        """Take a trainer reading."""
        self._power.add(sample.mono, sample.power)
        if sample.cadence_rpm is not None:
            self._cadence.add(sample.mono, round_half_up(sample.cadence_rpm))
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
        self._hold()

    def _hold(self) -> None:
        self._devices.hold(self._ride_active() or self._screen in (
            Screen.PRE_RIDE, Screen.RIDE, Screen.CALIBRATION))

    def _zones(self, riding: bool) -> tuple[int, ...]:
        setup = self._rides.setup
        if riding and setup is not None:
            return setup.zones_pct
        return self._panel.settings.zones_pct

    def _screen_state(self, now: float, trainer: LinkState) -> Json:
        if self._screen == Screen.RIDE:
            return ride_screen(self._rides.ride, now, self._power.value(now),
                               self._hr.value(now), self._zones(True),
                               self._cadence.value(now), self._live_route())
        if self._screen == Screen.SETTINGS:
            return self._panel.screen(self._certificate.valid_until)
        if self._screen == Screen.PRE_RIDE and self._plan is not None:
            chosen = self._routes.find(self._panel.settings.route)
            return pre_ride_screen(
                self._plan, trainer, self._block_modes, self._is_free(),
                [route_option(r.file, r.name, r.length_m, r.ascent_m)
                 for r in self._routes.routes],
                None if chosen is None else chosen.file)
        summary = self._past or self._rides.summary
        if self._screen == Screen.SUMMARY and summary is not None:
            route = summary.route
            return summary_screen(summary.ride_id, summary.title,
                                  summary.start_utc, summary.metrics,
                                  self._upload(summary.ride_id,
                                               summary.upload),
                                  self._past is not None,
                                  None if route is None else ridden_route(
                                      route.name, route.distance_m,
                                      route.ascent_m),
                                  self._garmin(summary.ride_id,
                                               summary.garmin_upload,
                                               self._panel.garmin_signed_in))
        if self._screen == Screen.HISTORY:
            return history_screen(self._history(), self._space.free_mb())
        if self._screen == Screen.CALIBRATION:
            return self._calibration_state(now, trainer)
        catalog = self._catalog
        return home_screen([self._card(e) for e in catalog.builtin],
                           [self._card(e) for e in catalog.today()],
                           [self._card(e) for e in catalog.library()],
                           self._recovery(now))

    def _live_route(self) -> Json | None:
        rider, setup = self._rides.rider, self._rides.setup
        if rider is None or setup is None or setup.route is None:
            return None
        last = rider.last
        return route_live(
            setup.route.route_id, rider.route,
            0.0 if last is None else last.distance_m,
            0.0 if last is None else last.speed_mps,
            self._rides.ride.phase == RidePhase.PAUSED)

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

    def _garmin(self, ride_id: str, known: str,
                signed_in: bool) -> str | None:
        state = self._garmin_uploads.state(ride_id) or known
        return None if state == UploadState.OFF and not signed_in else state

    def _history(self) -> list[Json]:
        entries = []
        signed_in = self._panel.garmin_signed_in
        for meta in kept_rides(self._rides_dir):
            ride_id = str(meta["ride_id"])
            metrics = meta.get("metrics")
            entries.append(history_entry(
                ride_id, meta.get("start_utc"), str(meta.get("title")),
                None if not isinstance(metrics, dict) else metrics_of(
                    metrics),
                self._upload(ride_id, str(meta.get("upload", "off"))),
                self._garmin(ride_id, str(meta.get("garmin_upload", "off")),
                             signed_in)))
        return entries

    def _card(self, item: Entry) -> Json:
        settings = self._panel.settings
        plan = (None if item.workout is None
                else make_plan(item.workout, settings.ftp))
        return workout_card(item.workout, plan, item.source, item.ref,
                            item.name, settings.zones_pct)

    def _device_warnings(self) -> list[Json]:
        synchronised = self._clock.synchronised()
        if self._screen == Screen.RIDE:
            synchronised = synchronised and not self._unsynced_at_start
        return [*battery_warning(self._devices.hrm.battery_pct(),
                                 self._panel.settings.battery_warn_pct),
                *clock_warning(synchronised)]

    def _warnings(self) -> list[Json]:
        trainer = sorted(self._devices.trainer.warnings())
        if self._screen == Screen.RIDE:
            return ride_warnings(self._rides.ride, trainer,
                                 self._device_warnings())
        warnings: list[Json] = [{"kind": kind} for kind in trainer]
        if self._screen == Screen.PRE_RIDE:
            warnings += self._device_warnings()
        if self._screen == Screen.HOME:
            warnings += clock_warning(self._clock.synchronised())
            warnings += certificate_warning(self._certificate.days_left())
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
        self._plan = make_plan(workout, self._panel.settings.ftp)
        self._block_modes = [Mode.ERG] * len(workout.blocks)
        self._screen = Screen.PRE_RIDE
        self._devices.open_pre_ride()
        self._routes.request_refresh()

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

    def _pre_ride_set_route(self, args: Mapping[str, Any]) -> str | None:
        file = args.get("file")
        if file is not None and self._routes.find(str(file)) is None:
            return Problem.BAD_REQUEST
        self._panel.keep_route(None if file is None else str(file))
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
                             UploadState(str(meta.get("upload", "off"))),
                             _route_of(meta.get("route")),
                             UploadState(str(meta.get("garmin_upload",
                                                      "off"))))
        self._screen = Screen.SUMMARY
        return None

    def _history_upload_retry(self, args: Mapping[str, Any]) -> str | None:
        return self._retry(str(args.get("ride_id")))

    def _summary_upload_retry(self, args: Mapping[str, Any]) -> str | None:
        return self._retry(str(args.get("ride_id")))

    def _retry(self, ride_id: str) -> str | None:
        return None if self._uploads.retry(ride_id) else Problem.BAD_REQUEST

    def _history_garmin_upload_retry(self, args: Mapping[str, Any]
                                     ) -> str | None:
        return self._garmin_retry(str(args.get("ride_id")))

    def _summary_garmin_upload_retry(self, args: Mapping[str, Any]
                                     ) -> str | None:
        return self._garmin_retry(str(args.get("ride_id")))

    def _garmin_retry(self, ride_id: str) -> str | None:
        return (None if self._garmin_uploads.retry(ride_id)
                else Problem.BAD_REQUEST)

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
        uploading = (self._uploads.state(ride_id),
                     self._garmin_uploads.state(ride_id))
        if ride_id in busy or UploadState.UPLOADING in uploading:
            return Problem.INVALID_STATE
        return None if delete_ride(self._rides_dir, ride_id) else (
            Problem.BAD_REQUEST)

    def _pre_ride_start(self, _args: Mapping[str, Any]) -> str | None:
        if self._plan is None or self._entry is None:
            return Problem.INVALID_STATE
        settings = self._panel.settings
        route = self._routes.find(settings.route)
        refused = self._rides.start(RideSetup(
            self._plan.workout, self._plan.ftp, settings.lead_time,
            raw=self._entry.raw, source=self._entry.source,
            zones_pct=settings.zones_pct,
            free_ride_level_pct=settings.free_ride_level_pct,
            upload_on=settings.upload_on and self._uploads_allowed,
            garmin_upload_on=(settings.garmin_upload_on
                              and self._uploads_allowed),
            block_modes=tuple(self._block_modes),
            route=None if route is None else route.choice(),
            rider_kg=settings.rider_kg))
        if refused is not None:
            logger.info("start refused: %s", refused)
            return Problem.INVALID_STATE
        self._unsynced_at_start = not self._clock.synchronised()
        if self._unsynced_at_start:
            logger.warning("ride started with the clock not synchronised")
        self._screen = Screen.RIDE
        return None

    def _home_open_settings(self, _args: Mapping[str, Any]) -> str | None:
        self._screen = Screen.SETTINGS
        return None

    def _settings_back(self, _args: Mapping[str, Any]) -> str | None:
        self.open_home()
        return None

    def _settings_settings_set(self, args: Mapping[str, Any]) -> str | None:
        return self._panel.set(str(args.get("key")), args.get("value"))

    def _settings_intervals_account_set(self, args: Mapping[str, Any]
                                        ) -> str | None:
        return self._panel.set_account(args.get("athlete_id"),
                                       args.get("api_key"))

    def _settings_device_scan(self, args: Mapping[str, Any]) -> str | None:
        return self._panel.scan(args.get("kind"))

    def _settings_device_choose(self, args: Mapping[str, Any]
                                ) -> str | None:
        return self._panel.choose(args.get("kind"), args.get("address"))

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


def _route_of(value: object) -> RouteSummary | None:
    if not isinstance(value, dict):
        return None
    distance, ascent = value.get("distance_m"), value.get("ascent_m")
    return RouteSummary(
        str(value.get("name")),
        float(distance) if isinstance(distance, (int, float)) else None,
        float(ascent) if isinstance(ascent, (int, float)) else None)


def _refusal(problem: str | None) -> str | None:
    return None if problem is None else Problem.INVALID_STATE


def _step(args: Mapping[str, Any]) -> int | str:
    step = args.get("step")
    if step not in (1, -1) or isinstance(step, bool):
        return Problem.BAD_REQUEST
    return int(step)
