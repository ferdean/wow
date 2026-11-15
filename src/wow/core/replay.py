"""Rebuild a ride from its journal.

The ride state machine fed again with the events its journal recorded
(AD-09; ICD 4.9.4; APP-809): Start from `armed`, the first power from
`ride_started`, every rider command, the link dropouts, and the Ticks
between them, all at their recorded monotonic times plus a shift. The
rebuilt ride doesn't watch for idleness: the journal holds no power
readings, so the watch starts again when the ride is taken up.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from wow.core.ride import (
    RIDE_FORMS, FreeRidePowerStep, HrmLink, IntensityStep, Pause, PowerSeen,
    ResistanceStep, Resume, Ride, RideEvent, Skip, Start, SwitchMode, Tick,
    TrainerLink,
)
from wow.core.vocab import Mode
from wow.core.workout import Workout

Record = Mapping[str, Any]


def record_mono(record: Record) -> float:
    """Return the monotonic time of a journal record, in seconds."""
    return float(record["mono_ms"]) / 1000


def rebuild(records: Sequence[Record], workout: Workout,
            shift: float = 0.0, until: float | None = None) -> Ride:
    """Return the ride the records describe, ticked on to until."""
    ride = Ride(watch_idle=False)
    for record in records:
        event = _event(record, workout)
        if event is None:
            continue
        now = record_mono(record) + shift
        tick_until(ride, now)
        if isinstance(event, Start):
            ride.handle(TrainerLink(True), now)
            ride.handle(HrmLink(True), now)
        ride.handle(event, now)
    if until is not None:
        tick_until(ride, until)
    return ride


def tick_until(ride: Ride, now: float) -> list[Any]:
    """Run the ride's deadlines up to now; return their actions."""
    actions: list[Any] = []
    deadline = ride.next_deadline()
    while deadline is not None and deadline <= now:
        actions += ride.handle(Tick(), deadline)
        deadline = ride.next_deadline()
    return actions


def _event(record: Record, workout: Workout) -> RideEvent | None:
    kind = record.get("type")
    if kind == "armed":
        capabilities = RIDE_FORMS.load(record["capabilities"])
        return Start(workout, int(record["ftp"]), capabilities,
                     float(record["lead_time"]),
                     free_ride_level_pct=int(
                         record.get("free_ride_level_pct", 0)),
                     block_modes=tuple(Mode(m) for m in
                                       record.get("block_modes", [])))
    if kind == "ride_started":
        return PowerSeen(int(record["power"]))
    if kind in ("dropout_start", "dropout_end"):
        up = kind == "dropout_end"
        return (TrainerLink(up) if record.get("device") == "trainer"
                else HrmLink(up))
    if kind == "command":
        return _command(str(record.get("name")), record.get("args") or {})
    return None


def _command(name: str, args: Mapping[str, Any]) -> RideEvent | None:
    match name:
        case "pause":
            return Pause()
        case "resume":
            return Resume()
        case "skip":
            return Skip()
        case "intensity":
            return IntensityStep(int(args["step"]))
        case "resistance":
            return ResistanceStep(int(args["step"]))
        case "free_ride_power":
            return FreeRidePowerStep(int(args["step"]))
        case "switch_mode":
            power = args.get("power")
            return SwitchMode(Mode(args["mode"]),
                              None if power is None else int(power))
    return None
