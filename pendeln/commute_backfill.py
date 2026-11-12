import argparse
import csv
import getpass
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import requests
from garminconnect import Garmin

TIME_ZONE = "Europe/Zurich"
GARMIN_TYPE = "cycling"
GARMIN_TOKENS = os.path.expanduser("~/.garminconnect")
GARMIN_PAUSE_S = 2.0
MATCH_WINDOW = timedelta(minutes=30)
ESTIMATE_MARK = "(est.)"
ICU_URL = "https://intervals.icu/api/v1"
ICU_RIDE_TYPES = {"Ride", "GravelRide"}
ICU_DESCRIPTION = "Backfilled estimate from office clock-in/out times"


@dataclass(frozen=True)
class Commute:
    start: datetime
    name: str
    distance_km: float
    duration_s: int
    load: int


def read_commutes(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return [
            Commute(
                start=datetime.fromisoformat(row["start"]),
                name=row["name"],
                distance_km=float(row["distance_km"]),
                duration_s=int(row["duration_s"]),
                load=int(row["load"]),
            )
            for row in csv.DictReader(handle)
        ]


def date_span(commutes):
    first = min(c.start for c in commutes).date()
    last = max(c.start for c in commutes).date()
    return first, last + timedelta(days=1)


def nearest(start, candidates):
    in_window = [
        (abs(when - start), item)
        for when, item in candidates
        if abs(when - start) <= MATCH_WINDOW
    ]
    if not in_window:
        return None
    return min(in_window, key=lambda pair: pair[0])[1]


def garmin_login():
    if os.path.isdir(GARMIN_TOKENS):
        client = Garmin()
    else:
        client = Garmin(
            input("Garmin email: "),
            getpass.getpass("Garmin password: "),
            prompt_mfa=lambda: input("MFA code: "),
        )
    client.login(GARMIN_TOKENS)
    return client


def garmin_rides(client, first, last):
    rides = client.get_activities_by_date(
        first.isoformat(), last.isoformat(), GARMIN_TYPE
    )
    return [
        (datetime.fromisoformat(ride["startTimeLocal"]), ride)
        for ride in rides
    ]


def garmin_create(client, commute):
    client.create_manual_activity(
        start_datetime=commute.start.strftime("%Y-%m-%dT%H:%M:%S.000"),
        time_zone=TIME_ZONE,
        type_key=GARMIN_TYPE,
        distance_km=commute.distance_km,
        duration_min=commute.duration_s / 60,
        activity_name=commute.name,
    )


def garmin_action(ride, commute):
    if ride is None:
        return "create"
    name = ride.get("activityName") or ""
    if not name.endswith(ESTIMATE_MARK):
        return "skip"
    return "keep" if name == commute.name else "rename"


def garmin_write(client, action, ride, commute):
    if action == "create":
        garmin_create(client, commute)
    else:
        client.set_activity_name(ride["activityId"], commute.name)
    time.sleep(GARMIN_PAUSE_S)


def run_garmin(commutes, apply, limit):
    client = garmin_login()
    existing = garmin_rides(client, *date_span(commutes))
    changes = 0
    for commute in commutes:
        ride = nearest(commute.start, existing)
        action = garmin_action(ride, commute)
        if action == "skip":
            print(f"skip   {commute.start}  recorded: {ride['activityName']}")
        if action in ("skip", "keep"):
            continue
        if changes == limit:
            break
        print(f"{action} {commute.start}  {commute.name}")
        if apply:
            garmin_write(client, action, ride, commute)
        changes += 1
    print(f"{'Applied' if apply else 'Would apply'} {changes} changes")


def icu_session():
    session = requests.Session()
    session.auth = ("API_KEY", getpass.getpass("intervals.icu API key: "))
    return session


def icu_rides(session, first, last):
    response = session.get(
        f"{ICU_URL}/athlete/0/activities",
        params={"oldest": first.isoformat(), "newest": last.isoformat()},
        timeout=30,
    )
    response.raise_for_status()
    return [
        (datetime.fromisoformat(ride["start_date_local"]), ride)
        for ride in response.json()
        if ride.get("type") in ICU_RIDE_TYPES
    ]


def icu_put(session, ride_id, payload):
    response = session.put(
        f"{ICU_URL}/activity/{ride_id}", json=payload, timeout=30
    )
    response.raise_for_status()
    return response.json()


def is_recorded(ride):
    return bool(ride.get("average_heartrate"))


def estimate_payload(commute):
    return {
        "name": commute.name,
        "description": ICU_DESCRIPTION,
        "commute": True,
        "icu_training_load": commute.load,
    }


def icu_apply(session, ride, commute):
    if is_recorded(ride):
        icu_put(session, ride["id"], {"commute": True})
        return
    stored = icu_put(session, ride["id"], estimate_payload(commute))
    if stored.get("icu_training_load") != commute.load:
        raise SystemExit(
            f"Load not applied to {ride['id']}: "
            f"still {stored.get('icu_training_load')}"
        )


def run_icu(commutes, apply, limit):
    session = icu_session()
    rides = icu_rides(session, *date_span(commutes))
    done = 0
    for commute in commutes[:limit]:
        ride = nearest(commute.start, rides)
        if ride is None:
            print(f"miss   {commute.start}  no ride in intervals.icu")
            continue
        action = "flag  " if is_recorded(ride) else "update"
        print(f"{action} {commute.start}  {ride['id']}")
        if apply:
            try:
                icu_apply(session, ride, commute)
            except requests.HTTPError as error:
                print(f"fail   {ride['id']}  {error}")
                continue
        done += 1
    print(f"{'Updated' if apply else 'Would update'} {done} activities")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backfill estimated commutes: create them in Garmin "
        "Connect, then set their load and commute flag in intervals.icu."
    )
    parser.add_argument("step", choices=["garmin", "icu"])
    parser.add_argument("csv_path")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    commutes = sorted(read_commutes(args.csv_path), key=lambda c: c.start)
    steps = {"garmin": run_garmin, "icu": run_icu}
    steps[args.step](commutes, args.apply, args.limit)


if __name__ == "__main__":
    main()
