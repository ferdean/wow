"""Write FIT activity files with the Garmin FIT SDK.

The FIT writer (3A, adapters/fit_garmin; ICD IF-12; APP-601, APP-604,
APP-605, APP-815): one Record per ride second, timer events around
pauses, one Lap per step, and a Session with the metrics of table M.
The target power of each second is the developer field `target_power`
(A-28). A ride on a route (APP-904) adds speed, distance, altitude and
position to every Record, distance and speeds to the Laps and the
Session, the climbing to the Session, and is a virtual ride.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from statistics import fmean
from typing import Any, Final

from garmin_fit_sdk import Encoder, Profile

from wow.core.activity import Activity, RecordedSample
from wow.core.numbers import exact, round_half_up
from wow.core.virtual_ride import Track, TrackPoint

MESG: Final[dict[str, int]] = Profile["mesg_num"]
FIT_EPOCH: Final[datetime] = datetime.fromisoformat(
    "1989-12-31T00:00:00+00:00")
TARGET_FIELD: Final[str] = "target_power"
TARGET_KEY: Final[int] = 0
UINT16_BASE_TYPE: Final[int] = 0x84
APPLICATION_ID: Final[list[int]] = list(b"WitchesOnWheels!")
SPORT: Final[dict[str, str]] = {"sport": "cycling",
                                "sub_sport": "indoor_cycling"}
VIRTUAL: Final[dict[str, str]] = {"sport": "cycling",
                                  "sub_sport": "virtual_activity"}
SEMICIRCLES_PER_DEGREE: Final[float] = 2 ** 31 / 180

Message = dict[str, Any]


def software_version(version: str) -> int:
    """Return a version as major × 100 + minor, as FIT stores it."""
    parts = [int(p) for p in version.split(".")[:2] if p.isdigit()]
    major, minor = (parts + [0, 0])[:2]
    return major * 100 + minor


def encode_activity(activity: Activity) -> bytes:
    """Return the FIT file of an activity."""
    developer = _developer_messages()
    descriptions: Any = {TARGET_KEY: {
        "developer_data_id_mesg": developer[0],
        "field_description_mesg": developer[1]}}
    encoder = Encoder(descriptions)
    for message in [*_header(activity), *developer, *_body(activity)]:
        encoder.write_mesg(message)
    return bytes(encoder.close())


class GarminFitWriter:
    """FIT writer on the Garmin FIT SDK."""

    def encode(self, activity: Activity) -> bytes:
        """Return the FIT file of an activity."""
        return encode_activity(activity)


def _header(activity: Activity) -> list[Message]:
    start = activity.start_utc
    return [
        {"mesg_num": MESG["FILE_ID"], "type": "activity",
         "manufacturer": "development", "product": 0, "serial_number": 1,
         "time_created": start},
        {"mesg_num": MESG["FILE_CREATOR"],
         "software_version": software_version(activity.app_version)},
        {"mesg_num": MESG["DEVICE_INFO"], "timestamp": start,
         "device_index": "creator", "manufacturer": "development",
         "product": 0,
         "product_name": f"WitchesOnWheels {activity.app_version}"},
    ]


def _developer_messages() -> tuple[Message, Message]:
    return (
        {"mesg_num": MESG["DEVELOPER_DATA_ID"], "developer_data_index": 0,
         "application_id": APPLICATION_ID, "application_version": 1},
        {"mesg_num": MESG["FIELD_DESCRIPTION"], "developer_data_index": 0,
         "field_definition_number": 0, "fit_base_type_id": UINT16_BASE_TYPE,
         "field_name": TARGET_FIELD, "units": "watts",
         "native_mesg_num": MESG["RECORD"]},
    )


def _sport(activity: Activity) -> dict[str, str]:
    return SPORT if activity.track is None else VIRTUAL


def _body(activity: Activity) -> list[Message]:
    out: list[Message] = [_timer(activity.start_utc, "start")]
    pauses = sorted(activity.pauses, key=lambda p: p.t_ride)
    track = {} if activity.track is None else activity.track.by_second()
    for sample in activity.samples:
        while pauses and pauses[0].t_ride <= sample.t:
            pause = pauses.pop(0)
            stop = activity.utc_at(pause.t_ride) - timedelta(
                seconds=pause.duration)
            out += [_timer(stop, "stop_all"),
                    _timer(activity.utc_at(pause.t_ride), "start")]
        out.append(_record(sample) | _place(track.get(sample.t)))
    end = activity.end_utc
    out.append(_timer(end, "stop_all"))
    laps = activity.laps()
    for index, (low, high) in enumerate(laps):
        lap_start, lap_end = activity.utc_at(low), activity.utc_at(high)
        samples = activity.samples_between(low, high)
        out.append({
            "mesg_num": MESG["LAP"], "message_index": index,
            "event": "lap", "event_type": "stop", "lap_trigger": "manual",
            "start_time": lap_start, "timestamp": lap_end,
            "total_elapsed_time": (lap_end - lap_start).total_seconds(),
            "total_timer_time": high - low, **_sport(activity),
            **_averages(samples),
            **_motion([track[s.t] for s in samples if s.t in track],
                      _distance_before(track, samples), high - low)})
    out.append(_session(activity, len(laps)))
    out.append({
        "mesg_num": MESG["ACTIVITY"], "timestamp": end,
        "total_timer_time": activity.duration, "num_sessions": 1,
        "type": "manual", "event": "activity", "event_type": "stop",
        "local_timestamp": _local_fit_time(end)})
    return out


def _timer(at: datetime, event_type: str) -> Message:
    return {"mesg_num": MESG["EVENT"], "timestamp": at, "event": "timer",
            "event_type": event_type}


def _record(sample: RecordedSample) -> Message:
    record: Message = {"mesg_num": MESG["RECORD"], "timestamp": sample.utc}
    if sample.power is not None:
        record["power"] = sample.power
    if sample.heart_rate_bpm is not None:
        record["heart_rate"] = sample.heart_rate_bpm
    if sample.cadence_rpm is not None:
        record["cadence"] = round_half_up(exact(sample.cadence_rpm))
    if sample.target is not None:
        record["developer_fields"] = {TARGET_KEY: sample.target}
    return record


def _place(point: TrackPoint | None) -> Message:
    if point is None:
        return {}
    return {"distance": point.distance_m, "speed": point.speed_mps,
            "enhanced_speed": point.speed_mps,
            "altitude": point.altitude_m,
            "enhanced_altitude": point.altitude_m,
            "position_lat": _semicircles(point.lat),
            "position_long": _semicircles(point.lon)}


def _semicircles(degrees: float) -> int:
    return round(degrees * SEMICIRCLES_PER_DEGREE)


def _distance_before(track: dict[int, TrackPoint],
                     samples: Sequence[RecordedSample]) -> float:
    if not samples:
        return 0.0
    before = track.get(samples[0].t - 1)
    return 0.0 if before is None else before.distance_m


def _motion(points: Sequence[TrackPoint], start_m: float,
            seconds: float) -> Message:
    if not points:
        return {}
    distance = points[-1].distance_m - start_m
    fastest = max(p.speed_mps for p in points)
    average = distance / seconds if seconds > 0 else 0.0
    return {"total_distance": distance, "avg_speed": average,
            "enhanced_avg_speed": average, "max_speed": fastest,
            "enhanced_max_speed": fastest}


def _climbing(track: Track | None) -> Message:
    if track is None:
        return {}
    return {"total_ascent": round_half_up(exact(track.ascent_m)),
            "total_descent": round_half_up(exact(track.descent_m))}


def _averages(samples: Sequence[RecordedSample]) -> Message:
    values: Message = {}
    power = [s.power for s in samples if s.power is not None]
    heart = [s.heart_rate_bpm for s in samples
             if s.heart_rate_bpm is not None]
    if power:
        values |= {"avg_power": round_half_up(exact(fmean(power))),
                   "max_power": max(power), "total_work": sum(power)}
    if heart:
        values |= {"avg_heart_rate": round_half_up(exact(fmean(heart))),
                   "max_heart_rate": max(heart)}
    return values


def _session(activity: Activity, laps: int) -> Message:
    metrics = activity.metrics
    end = activity.end_utc
    session: Message = {
        "mesg_num": MESG["SESSION"], "message_index": 0, "event": "session",
        "event_type": "stop", "trigger": "activity_end",
        **_sport(activity),
        "start_time": activity.start_utc, "timestamp": end,
        "total_elapsed_time": (end - activity.start_utc).total_seconds(),
        "total_timer_time": activity.duration, "first_lap_index": 0,
        "num_laps": laps, "threshold_power": activity.ftp,
        "total_work": round_half_up(exact(metrics.work_kj * 1000)),
        **_averages(activity.samples), **_climbing(activity.track),
        **_motion(() if activity.track is None else activity.track.points,
                  0.0, activity.duration)}
    if metrics.np is not None and metrics.intensity_factor is not None:
        session |= {"normalized_power": round_half_up(exact(metrics.np)),
                    "intensity_factor": round(metrics.intensity_factor, 3)}
    if metrics.tss is not None:
        session["training_stress_score"] = round(metrics.tss, 1)
    return session


def _local_fit_time(at: datetime) -> int:
    offset = at.astimezone().utcoffset() or timedelta()
    return int((at - FIT_EPOCH + offset).total_seconds())
