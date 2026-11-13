"""Run the ride state machine in the shell.

Runs the ride state machine and the sampler: rider commands, the
trainer's power and the strap's heart rate in; trainer commands, journal
records, samples and, on Finish, `ride.fit` and `meta.json` out (3A,
app/ride_controller; APP-301, APP-304, APP-315, APP-601 to APP-606,
APP-801).
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
from wow.core.activity import Activity, RecordedSample
from wow.core.devices import (
    HrSample, LinkState, TrainerCapabilities, TrainerSample,
)
from wow.core.metrics import Metrics, ride_metrics
from wow.core.numbers import DEFAULT_ZONES_PCT
from wow.core.ride import (
    CancelStart, Ended, Finish, HrmLink, Journal, PowerSeen, Refused, Ride,
    RideAction, RideEvent, RidePhase, SetTrainer, Start, Tick, TrainerLink,
)
from wow.core.sampler import (
    Began, HrValue, Sample, Sampler, SamplerEvent, Stopped, TrainerValue,
)
from wow.core.sampler import Tick as SampleTick
from wow.core.timefmt import utc_text
from wow.core.vocab import UploadState
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
META_SCHEMA: Final[int] = 1


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


@dataclass(frozen=True)
class Summary:
    """What the Summary screen shows."""

    ride_id: str
    title: str
    start_utc: str
    metrics: Metrics
    upload: UploadState


@dataclass
class _Record:
    ride_dir: Path
    setup: RideSetup
    meta: dict[str, object]
    samples: list[RecordedSample] = field(default_factory=list)
    lap_starts: list[float] = field(default_factory=list)
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

    def start(self, setup: RideSetup) -> str | None:
        """Start a ride; return the problem, if any."""
        connected = self._trainer.link() == LinkState.CONNECTED
        self._driver.post(TrainerLink(connected))
        capabilities = self._trainer.capabilities() or NO_CAPABILITIES
        self._setup = setup
        return self._post(Start(setup.workout, setup.ftp, capabilities,
                                setup.lead_time,
                                free_ride_level_pct=setup.free_ride_level_pct))

    def cancel(self) -> str | None:
        """Cancel the wait for power; return the problem, if any."""
        return self._post(CancelStart())

    def finish(self) -> str | None:
        """Finish the ride; return the problem, if any."""
        return self._post(Finish())

    def trainer_sample(self, sample: TrainerSample) -> None:
        """Take a trainer reading."""
        self._sampling.post(TrainerValue(sample.mono, sample.power,
                                         sample.cadence_rpm))
        if self.ride.phase == RidePhase.ARMED and sample.power is not None:
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
        self._write_meta(self._record)

    def _samples(self, samples: list[Sample]) -> None:
        current = self._record
        if current is None:
            return
        for sample in samples:
            mode, target = self.ride.target_at(sample.t)
            utc = self._utc_at(sample.mono)
            recorded = RecordedSample(sample.t, utc, sample.power,
                                      sample.heart_rate_bpm,
                                      sample.cadence_rpm, target)
            current.samples.append(recorded)
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
        if cause == RidePhase.FINISHED:
            self._sampling.post(Stopped(self._clock.monotonic()))
        self._record = None
        if cause == RidePhase.FINISHED:
            self._finish(current)
        else:
            current.meta["state"] = cause.value
            self._write_meta(current)
        task = asyncio.get_running_loop().create_task(
            self._tail(current.ride_dir))
        self._tails.add(task)
        task.add_done_callback(self._tails.discard)
        self.on_ended(cause)

    def _finish(self, current: _Record) -> None:
        setup = current.setup
        samples = current.samples
        metrics = ride_metrics([s.power for s in samples],
                               [s.heart_rate_bpm for s in samples],
                               setup.ftp, setup.zones_pct)
        start = current.start_utc or self._clock.utc()
        activity = Activity(setup.workout.name, self._version, setup.ftp,
                            start, float(len(samples)), tuple(samples),
                            tuple(current.lap_starts), (), metrics)
        meta = {**current.meta, "state": "finished",
                "metrics": _metrics_json(metrics),
                "finished_mono_ms": round(self._clock.monotonic() * 1000, 1)}
        self.summary = Summary(str(current.meta["ride_id"]),
                               setup.workout.name, utc_text(start), metrics,
                               UploadState(str(meta["upload"])))
        ride_dir, writer, clock = current.ride_dir, self._fit, self._clock

        def write_files() -> None:
            write_atomic(ride_dir / FIT_FILE, writer.encode(activity))
            meta["files_mono_ms"] = round(clock.monotonic() * 1000, 1)
            write_atomic(ride_dir / META, json.dumps(meta).encode())

        self._recorder.run(write_files)

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


def _metrics_json(metrics: Metrics) -> dict[str, object]:
    return {
        "duration": metrics.duration, "avg_power": metrics.avg_power,
        "max_power": metrics.max_power, "np": metrics.np,
        "intensity_factor": metrics.intensity_factor, "tss": metrics.tss,
        "work_kj": metrics.work_kj,
        "time_in_zone": list(metrics.time_in_zone),
        "avg_hr_bpm": metrics.avg_hr_bpm, "max_hr_bpm": metrics.max_hr_bpm,
    }
