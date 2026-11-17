"""Run the ride state machine in the shell.

Runs the ride state machine and the sampler: rider commands, the
trainer's power and the strap's heart rate in; trainer commands, journal
records, samples and, on Finish, `ride.fit` and `meta.json` out (3A,
app/ride_controller; APP-301, APP-304, APP-315, APP-601 to APP-606,
APP-801). A ride on a route keeps a copy of the route and is ridden
along it second by second, for the route screen and for the files
(APP-903, APP-908 to APP-910).
"""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

from wow.adapters.store_files import write_atomic
from wow.app.machine_driver import MachineDriver
from wow.app.recorder import Recorder
from wow.core.activity import Activity, Pause, RecordedSample
from wow.core.devices import (
    Erg, HrSample, LinkState, TrainerCapabilities, TrainerSample,
)
from wow.core.metrics import Metrics, ride_metrics
from wow.core.numbers import DEFAULT_ZONES_PCT
from wow.core.ride import (
    ACTIVE, FIRST_POWER_MIN, CancelStart, Discard, Ended, Finish,
    FreeRideLevel, FreeRidePowerStep, HrmLink, IntensityStep, Journal,
    PowerSeen, Recovered, Refused, ResistanceStep, Resume, Ride, RideAction,
    RideEvent, RidePhase, SetTrainer, Skip, Start, SwitchMode, Tick,
    TrainerLink,
)
from wow.core.ride import Pause as PauseRide
from wow.core.replay import Record, rebuild, record_mono, tick_until
from wow.core.route import RouteChoice, RouteError
from wow.core.sampler import (
    Began, HrValue, Paused, Resumed, Restored, Sample, Sampler, SamplerEvent,
    Stopped, TrainerValue,
)
from wow.core.sampler import Tick as SampleTick
from wow.core.timefmt import utc_text
from wow.core.virtual_ride import Track, VirtualRider, rider_of
from wow.core.vocab import Mode, UploadState
from wow.core.workout import Workout
from wow.ports.clock import Clock
from wow.ports.devices import Trainer
from wow.ports.fit import FitWriter

logger = logging.getLogger(__name__)

NO_CAPABILITIES: Final[TrainerCapabilities] = TrainerCapabilities(
    None, None, False, False)
RIDE_LOG_TAIL: Final[float] = 3.0
META: Final[str] = "meta.json"
WORKOUT: Final[str] = "workout.json"
FIT_FILE: Final[str] = "ride.fit"
ROUTE_FILE: Final[str] = "route.gpx"
META_SCHEMA: Final[int] = 1
DEFAULT_RIDER_KG: Final[int] = 75


@dataclass(frozen=True)
class RideSetup:
    """What a ride needs besides the devices."""

    workout: Workout
    ftp: int
    lead_time: float
    raw: bytes | None = None
    source: str = "builtin"
    zones_pct: tuple[int, ...] = DEFAULT_ZONES_PCT
    free_ride_level_pct: int = 0
    upload_on: bool = True
    block_modes: tuple[Mode, ...] = ()
    route: RouteChoice | None = None
    rider_kg: int = DEFAULT_RIDER_KG


@dataclass(frozen=True)
class RouteSummary:
    """A ride's route and, once ridden along it, its distance and climb."""

    name: str
    distance_m: float | None = None
    ascent_m: float | None = None


@dataclass(frozen=True)
class Summary:
    """What the Summary screen shows."""

    ride_id: str
    title: str
    start_utc: str
    metrics: Metrics
    upload: UploadState
    route: RouteSummary | None = None


@dataclass(frozen=True)
class Resumption:
    """A ride read back after a restart, and how to take it up again."""

    ride_dir: Path
    meta: dict[str, object]
    records: list[Record]
    samples: list[Record]
    setup: RideSetup
    crash_mono: float
    shift: float
    outage: float | None


@dataclass
class _Record:
    ride_dir: Path
    setup: RideSetup
    meta: dict[str, object]
    samples: list[RecordedSample] = field(default_factory=list)
    lap_starts: list[float] = field(default_factory=list)
    pauses: list[Pause] = field(default_factory=list)
    paused_at: tuple[float, float] | None = None
    start_utc: datetime | None = None


class RideController:
    """Rides: commands and data in; commands, journal and files out."""

    def __init__(self, clock: Clock, trainer: Trainer, recorder: Recorder,
                 on_change: Callable[[], None], fit_writer: FitWriter,
                 app_version: str) -> None:
        self._clock = clock
        self._trainer = trainer
        self._recorder = recorder
        self._on_change = on_change
        self._fit = fit_writer
        self._version = app_version
        self.on_ended: Callable[[RidePhase], None] = lambda _cause: None
        self.on_free_level: Callable[[int], None] = lambda _pct: None
        self.on_finished: Callable[[Summary], None] = lambda _summary: None
        self.ride = Ride()
        self.summary: Summary | None = None
        self._driver: MachineDriver[RideEvent, RideAction] = MachineDriver(
            self.ride, clock, self._perform, Tick())
        self._sampler = Sampler()
        self._sampling: MachineDriver[SamplerEvent, Sample] = MachineDriver(
            self._sampler, clock, self._samples, SampleTick())
        self._refusal: str | None = None
        self._record: _Record | None = None
        self._setup: RideSetup | None = None
        self._tails: set[asyncio.Task[None]] = set()
        self._rider: VirtualRider | None = None

    def start(self, setup: RideSetup) -> str | None:
        """Start a ride; return the problem, if any."""
        connected = self._trainer.link() == LinkState.CONNECTED
        self._driver.post(TrainerLink(connected))
        capabilities = self._trainer.capabilities() or NO_CAPABILITIES
        self._setup = setup
        self.summary = None
        return self._post(Start(setup.workout, setup.ftp, capabilities,
                                setup.lead_time,
                                free_ride_level_pct=setup.free_ride_level_pct,
                                block_modes=setup.block_modes))

    def cancel(self) -> str | None:
        """Cancel the wait for power; return the problem, if any."""
        return self._post(CancelStart())

    def finish(self) -> str | None:
        """Finish the ride; return the problem, if any."""
        return self._post(Finish())

    def discard(self) -> str | None:
        """Discard the ride; return the problem, if any."""
        return self._post(Discard())

    def pause(self) -> str | None:
        """Pause the ride; return the problem, if any."""
        return self._post(PauseRide())

    def resume(self) -> str | None:
        """Resume the ride; return the problem, if any."""
        return self._post(Resume())

    def skip(self) -> str | None:
        """Skip the rest of the step; return the problem, if any."""
        return self._post(Skip())

    def intensity(self, step: int) -> str | None:
        """Change the intensity by one step; return the problem, if any."""
        return self._post(IntensityStep(step))

    def switch_mode(self, mode: Mode, power: int | None) -> str | None:
        """Switch the block or free ride to a mode; return the problem."""
        return self._post(SwitchMode(mode, power))

    def resistance(self, step: int) -> str | None:
        """Change the resistance by one step; return the problem, if any."""
        return self._post(ResistanceStep(step))

    def free_ride_power(self, step: int) -> str | None:
        """Change the free-ride target by 5 W; return the problem."""
        return self._post(FreeRidePowerStep(step))

    def recover(self, found: Resumption, keep_riding: bool) -> None:
        """Take a ride up again after a restart, or finish it."""
        now = self._clock.monotonic()
        crash = found.crash_mono + found.shift
        ride = rebuild(found.records, found.setup.workout, found.shift, crash)
        self._driver.close()
        self.ride = ride
        self._driver = MachineDriver(ride, self._clock, self._perform, Tick())
        self._setup = found.setup
        self.summary = None
        self._record = _restored(found)
        self._rider = _rider_again(found.setup, self._record)
        self._recorder.open_ride(str(found.meta["ride_id"]))
        self._journal(Journal("recovered", ride.ride_time(crash),
                              {"outage": found.outage}))
        if not keep_riding:
            self._post(Finish())
            return
        actions = ride.handle(TrainerLink(False), crash)
        actions += ride.handle(HrmLink(False), crash)
        self._perform(actions + tick_until(ride, now))
        self._driver.post(Recovered())
        self._restart_sampler(found, now)
        self._driver.post(TrainerLink(
            self._trainer.link() == LinkState.CONNECTED))

    @property
    def setup(self) -> RideSetup | None:
        """Return the setup of the ride last started or taken up."""
        return self._setup

    @property
    def rider(self) -> VirtualRider | None:
        """Return the rider on the route of the ride running, if any."""
        return self._rider

    def ride_id(self) -> str | None:
        """Return the ID of the ride being recorded, if any."""
        current = self._record
        return None if current is None else str(current.meta["ride_id"])

    def trainer_sample(self, sample: TrainerSample) -> None:
        """Take a trainer reading."""
        self._sampling.post(TrainerValue(sample.mono, sample.power,
                                         sample.cadence_rpm))
        if sample.power is not None and sample.power >= FIRST_POWER_MIN and (
                self.ride.phase in ACTIVE):
            self._driver.post(PowerSeen(sample.power))

    def hr_sample(self, sample: HrSample) -> None:
        """Take a heart-rate reading."""
        self._sampling.post(HrValue(sample.mono, sample.heart_rate_bpm))

    def link_changed(self, trainer: LinkState, hrm: LinkState) -> None:
        """Tell the ride about the device links."""
        self._driver.post(TrainerLink(trainer == LinkState.CONNECTED))
        self._driver.post(HrmLink(hrm == LinkState.CONNECTED))

    async def close(self) -> None:
        """Stop the machines and close the files."""
        self._driver.close()
        self._sampling.close()
        await asyncio.gather(*self._tails, return_exceptions=True)

    def _post(self, event: RideEvent) -> str | None:
        self._refusal = None
        self._driver.post(event)
        return self._refusal

    def _perform(self, actions: list[RideAction]) -> None:
        if self._setup is not None and any(
                isinstance(a, Journal) and a.event == "armed"
                for a in actions):
            self._open(self._setup)
        for action in actions:
            match action:
                case SetTrainer(command=command):
                    self._trainer.set_command(command)
                case Journal():
                    self._on_journal(action)
                case Refused(reason=reason):
                    self._refusal = reason
                case Ended(cause=cause):
                    self._end(cause)
                case FreeRideLevel(level_pct=pct):
                    self.on_free_level(pct)
        self._on_change()

    def _on_journal(self, record: Journal) -> None:
        self._journal(record)
        current = self._record
        if current is None:
            return
        if record.event == "ride_started":
            now = self._clock.monotonic()
            current.start_utc = self._clock.utc()
            current.meta["start_utc"] = utc_text(current.start_utc)
            self._write_meta(current)
            self._sampling.post(Began(now))
        elif record.event in ("step_started", "workout_done"):
            if record.t_ride is not None:
                current.lap_starts.append(record.t_ride)
        elif record.event == "paused" and record.t_ride is not None:
            now = self._clock.monotonic()
            current.paused_at = (record.t_ride, now)
            if self._rider is not None:
                self._rider.stop_at(record.t_ride)
            self._sampling.post(Paused(now))
        elif record.event == "resumed" and current.paused_at is not None:
            now = self._clock.monotonic()
            t_ride, since = current.paused_at
            current.pauses.append(Pause(t_ride, now - since))
            current.paused_at = None
            self._sampling.post(Resumed(now))

    def _open(self, setup: RideSetup) -> None:
        stamp = self._clock.utc().strftime("%Y-%m-%dT%H%M%SZ")
        ride_dir = self._recorder.open_ride(stamp)
        upload = UploadState.PENDING if setup.upload_on else UploadState.OFF
        meta: dict[str, object] = {
            "schema": META_SCHEMA, "ride_id": stamp,
            "app_version": self._version, "state": "running",
            "title": setup.workout.name, "source": setup.source,
            "workout_ref": setup.workout.ref, "ftp": setup.ftp,
            "zones_pct": list(setup.zones_pct), "start_utc": None,
            "boot_id": self._recorder.boot_id, "metrics": None,
            "upload": upload,
        }
        self._record = _Record(ride_dir, setup, meta)
        self._sampler = Sampler()
        self._sampling.close()
        self._sampling = MachineDriver(self._sampler, self._clock,
                                       self._samples, SampleTick())
        if setup.raw is not None:
            self._recorder.write_file(ride_dir / WORKOUT, setup.raw)
        if setup.route is not None:
            self._recorder.write_file(ride_dir / ROUTE_FILE, setup.route.gpx)
            meta["route"] = {"file": setup.route.file,
                             "name": setup.route.name}
            meta["rider_kg"] = setup.rider_kg
        self._rider = _rider_of(setup)
        self._write_meta(self._record)

    def _restart_sampler(self, found: Resumption, now: float) -> None:
        self._sampler = Sampler()
        self._sampling.close()
        self._sampling = MachineDriver(self._sampler, self._clock,
                                       self._samples, SampleTick())
        current = self._record
        paused = None if current is None or current.paused_at is None else (
            current.paused_at[1])
        at = now if paused is None else paused
        origin = at - self.ride.ride_time(at)
        first = int(found.samples[-1]["t"]) + 1 if found.samples else 0
        self._sampling.post(Restored(origin, first, paused))

    def _samples(self, samples: list[Sample]) -> None:
        current = self._record
        if current is None:
            return
        for sample in samples:
            command = self.ride.command
            mode = self.ride.mode
            target = command.power if isinstance(command, Erg) else None
            utc = self._utc_at(sample.mono)
            recorded = RecordedSample(sample.t, utc, sample.power,
                                      sample.heart_rate_bpm,
                                      sample.cadence_rpm, target)
            current.samples.append(recorded)
            if self._rider is not None:
                self._rider.ride(sample.t, sample.power)
            self._recorder.sample({
                "t": sample.t, "utc": utc_text(utc), "power": sample.power,
                "hr_bpm": sample.heart_rate_bpm,
                "cadence_rpm": sample.cadence_rpm, "target": target,
                "mode": mode})

    def _end(self, cause: RidePhase) -> None:
        current = self._record
        if current is None:
            self.on_ended(cause)
            return
        now = self._clock.monotonic()
        if current.paused_at is not None:
            t_ride, since = current.paused_at
            current.pauses.append(Pause(t_ride, now - since))
            current.paused_at = None
            self._sampling.post(Resumed(now))
        if cause == RidePhase.FINISHED:
            self._sampling.post(Stopped(now))
        self._record = None
        rider, self._rider = self._rider, None
        if cause == RidePhase.FINISHED:
            self._finish(current, rider)
        else:
            current.meta["state"] = cause.value
            self._write_meta(current)
        task = asyncio.get_running_loop().create_task(
            self._tail(current.ride_dir))
        self._tails.add(task)
        task.add_done_callback(self._tails.discard)
        self.on_ended(cause)

    def _finish(self, current: _Record, rider: VirtualRider | None) -> None:
        setup = current.setup
        samples = current.samples
        metrics = ride_metrics([s.power for s in samples],
                               [s.heart_rate_bpm for s in samples],
                               setup.ftp, setup.zones_pct)
        start = current.start_utc or self._clock.utc()
        route = setup.route
        track = None if rider is None or route is None else rider.track(
            route.name)
        activity = Activity(setup.workout.name, self._version, setup.ftp,
                            start, float(len(samples)), tuple(samples),
                            tuple(current.lap_starts), tuple(current.pauses),
                            metrics, track)
        meta = {**current.meta, "state": "finished",
                "metrics": _metrics_json(metrics),
                "finished_mono_ms": round(self._clock.monotonic() * 1000, 1)}
        if route is not None:
            meta["route"] = _route_json(route, track)
        self.summary = Summary(
            str(current.meta["ride_id"]), setup.workout.name,
            utc_text(start), metrics, UploadState(str(meta["upload"])),
            None if route is None else RouteSummary(
                route.name, None if track is None else track.distance_m,
                None if track is None else track.ascent_m))
        ride_dir, writer, clock = current.ride_dir, self._fit, self._clock

        def write_files() -> None:
            write_atomic(ride_dir / FIT_FILE, writer.encode(activity))
            meta["files_mono_ms"] = round(clock.monotonic() * 1000, 1)
            write_atomic(ride_dir / META, json.dumps(meta).encode())

        self._recorder.run(write_files)
        self.on_finished(self.summary)

    def _write_meta(self, current: _Record) -> None:
        self._recorder.write_file(current.ride_dir / META,
                                  json.dumps(current.meta).encode())

    def _utc_at(self, mono: float) -> datetime:
        return self._clock.utc() - timedelta(
            seconds=self._clock.monotonic() - mono)

    async def _tail(self, ride: Path) -> None:
        try:
            await self._clock.sleep_until(
                self._clock.monotonic() + RIDE_LOG_TAIL)
        finally:
            self._recorder.close_ride(ride)

    def _journal(self, record: Journal) -> None:
        version = {"app_version": self._version} if (
            record.event == "armed") else {}
        self._recorder.journal({
            "t_ride": record.t_ride,
            "utc": utc_text(self._clock.utc()),
            "mono_ms": round(self._clock.monotonic() * 1000, 1),
            "boot_id": self._recorder.boot_id,
            "type": record.event,
            **record.data,
            **version,
        })


def _rider_of(setup: RideSetup) -> VirtualRider | None:
    if setup.route is None:
        return None
    try:
        route = setup.route.route()
    except RouteError as error:
        logger.warning("route %s not ridden live: %s", setup.route.file,
                       error)
        return None
    return VirtualRider(route, rider_of(setup.rider_kg))


def _rider_again(setup: RideSetup, record: _Record) -> VirtualRider | None:
    rider = _rider_of(setup)
    if rider is None:
        return None
    stops = [p.t_ride for p in record.pauses]
    if record.paused_at is not None:
        stops.append(record.paused_at[0])
    for stop in stops:
        rider.stop_at(stop)
    for sample in record.samples:
        rider.ride(sample.t, sample.power)
    return rider


def _route_json(route: RouteChoice, track: Track | None) -> dict[str, object]:
    ridden: dict[str, object] = {} if track is None else {
        "distance_m": round(track.distance_m, 1),
        "ascent_m": round(track.ascent_m, 1),
        "descent_m": round(track.descent_m, 1),
        "max_speed_mps": round(track.max_speed_mps, 3)}
    return {"file": route.file, "name": route.name, **ridden}


def _metrics_json(metrics: Metrics) -> dict[str, object]:
    return {
        "duration": metrics.duration, "avg_power": metrics.avg_power,
        "max_power": metrics.max_power, "np": metrics.np,
        "intensity_factor": metrics.intensity_factor, "tss": metrics.tss,
        "work_kj": metrics.work_kj,
        "time_in_zone": list(metrics.time_in_zone),
        "avg_hr_bpm": metrics.avg_hr_bpm, "max_hr_bpm": metrics.max_hr_bpm,
    }


def _restored(found: Resumption) -> _Record:
    record = _Record(found.ride_dir, found.setup, dict(found.meta))
    record.samples = [RecordedSample(
        int(s["t"]), _utc(str(s["utc"])), s.get("power"), s.get("hr_bpm"),
        s.get("cadence_rpm"), s.get("target")) for s in found.samples]
    for item in found.records:
        kind, t_ride = item.get("type"), item.get("t_ride")
        mono = record_mono(item) + found.shift
        if kind in ("step_started", "workout_done") and t_ride is not None:
            record.lap_starts.append(float(t_ride))
        elif kind == "paused" and t_ride is not None:
            record.paused_at = (float(t_ride), mono)
        elif kind == "resumed" and record.paused_at is not None:
            t_paused, since = record.paused_at
            record.pauses.append(Pause(t_paused, mono - since))
            record.paused_at = None
    start = found.meta.get("start_utc")
    record.start_utc = None if start is None else _utc(str(start))
    return record


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
