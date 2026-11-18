"""Load the configuration; keep the settings and the account.

The installation's configuration (`wow.toml`), and the rider's settings
and intervals.icu account in the data directory (ICD IF-10; APP-706,
APP-707, APP-708, APP-817): both files are replaced atomically, and
`secrets.json` is created readable by the app's user only. The Garmin
Connect tokens live in `garmin/`, written by `wow-garmin login`.
"""

import json
import logging
import stat
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Final

from wow.adapters.store_files import write_atomic
from wow.core.settings import SCHEMA, Settings, settings_json, settings_of

logger = logging.getLogger(__name__)

SETTINGS_FILE: Final[str] = "settings.json"
SECRETS_FILE: Final[str] = "secrets.json"
SECRETS_MODE: Final[int] = 0o600
GARMIN_DIR: Final[str] = "garmin"
GARMIN_TOKEN_FILE: Final[str] = "garmin_tokens.json"


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
    led: Path | None = None


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
    system = raw.get("system", {})
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
        led=Path(system["led"]) if "led" in system else None,
    )


def load_settings(data: Path) -> Settings:
    """Load the settings; defaults for anything missing or unusable."""
    path = data / SETTINGS_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError) as error:
        logger.warning("%s unreadable, defaults used: %r", path, error)
        return Settings()
    if not isinstance(raw, dict):
        logger.warning("%s is not an object, defaults used", path)
        return Settings()
    settings, rejected = settings_of(raw)
    for problem in rejected:
        logger.warning("%s: default kept for %s", path, problem.text())
    return settings


def save_settings(data: Path, settings: Settings) -> None:
    """Replace the settings file atomically (APP-707)."""
    write_atomic(data / SETTINGS_FILE,
                 (json.dumps(settings_json(settings), indent=2)
                  + "\n").encode())


def load_secrets(data: Path) -> Secrets | None:
    """Load the intervals.icu account, if one is stored."""
    path = data / SECRETS_FILE
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


def save_secrets(data: Path, secrets: Secrets) -> None:
    """Store the intervals.icu account, readable by the app only."""
    write_atomic(data / SECRETS_FILE, json.dumps({
        "schema": SCHEMA, "intervals_athlete_id": secrets.athlete_id,
        "intervals_api_key": secrets.api_key}).encode(), mode=SECRETS_MODE)


def garmin_tokens(data: Path) -> Path:
    """Return the directory that holds the Garmin Connect tokens."""
    return data / GARMIN_DIR


def garmin_signed_in(data: Path) -> bool:
    """Return whether `wow-garmin login` has stored tokens."""
    return (garmin_tokens(data) / GARMIN_TOKEN_FILE).is_file()
