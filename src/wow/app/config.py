"""Load the installation configuration and ride settings.

The installation's configuration (`wow.toml`) and, until slice SL-10
brings the settings screen, the few settings a ride needs (ICD IF-10).
"""

import json
import logging
import stat
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Final

from wow.core.numbers import DEFAULT_ZONES_PCT

logger = logging.getLogger(__name__)

DEFAULT_FTP: Final[int] = 250
DEFAULT_LEAD_TIME: Final[float] = 1.0


@dataclass(frozen=True)
class Config:
    """Installation configuration read from wow.toml."""

    adapter: str
    simulate: bool
    host: str
    https_port: int
    http_port: int
    cert: Path
    key: Path
    root_cert: Path
    data: Path
    static: Path
    listen: str | None = None


@dataclass(frozen=True)
class RideSettings:
    """Settings a ride needs."""

    ftp: int
    lead_time: float
    trainer: str | None
    hrm: str | None
    zones_pct: tuple[int, ...] = DEFAULT_ZONES_PCT
    free_ride_level_pct: int = 0
    upload_on: bool = True


@dataclass(frozen=True)
class Secrets:
    """The intervals.icu account (APP-706, APP-817)."""

    athlete_id: str
    api_key: str = field(repr=False)


def default_static() -> Path:
    """Return the directory of the built display."""
    return Path(str(resources.files("wow.web").joinpath("static")))


def load_config(path: Path) -> Config:
    """Load the configuration file."""
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    bluetooth = raw.get("bluetooth", {})
    web = raw.get("web", {})
    paths = raw.get("paths", {})
    return Config(
        adapter=bluetooth.get("adapter", "hci0"),
        simulate=bool(bluetooth.get("simulate", False)),
        host=web.get("host", "wow.local"),
        https_port=int(web.get("https_port", 443)),
        http_port=int(web.get("http_port", 80)),
        cert=Path(web["cert"]),
        key=Path(web["key"]),
        root_cert=Path(web["root_cert"]),
        data=Path(paths.get("data", "/var/lib/wow")),
        static=Path(web["static"]) if "static" in web else default_static(),
        listen=web.get("listen"),
    )


def _address(entry: Any) -> str | None:
    if isinstance(entry, dict) and isinstance(entry.get("address"), str):
        return str(entry["address"])
    return None


def load_settings(data: Path) -> RideSettings:
    """Load the ride settings from the data directory."""
    path = data / "settings.json"
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return RideSettings(
        ftp=int(raw.get("ftp", DEFAULT_FTP)),
        lead_time=float(raw.get("lead_time", DEFAULT_LEAD_TIME)),
        trainer=_address(raw.get("trainer")),
        hrm=_address(raw.get("hrm")),
        zones_pct=tuple(int(z) for z in raw.get("zones_pct",
                                                DEFAULT_ZONES_PCT)),
        free_ride_level_pct=int(raw.get("free_ride_level_pct", 0)),
        upload_on=bool(raw.get("upload_on", True)),
    )


def load_secrets(data: Path) -> Secrets | None:
    """Load the intervals.icu account, if one is stored."""
    path = data / "secrets.json"
    if not path.exists():
        return None
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.warning("%s is readable by others: chmod 600 it", path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    athlete, key = raw.get("intervals_athlete_id"), raw.get(
        "intervals_api_key")
    if not isinstance(athlete, str) or not isinstance(key, str):
        logger.warning("%s lacks the athlete ID or the API key", path)
        return None
    return Secrets(athlete, key)
