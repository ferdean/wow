"""Keep the rider's settings and serve the Settings screen.

The Settings screen's commands (ICD IF-06, 4.6.5: `settings_set`,
`intervals_account_set`, `device_scan`, `device_choose`): values of
table S inside their ranges, the intervals.icu account, and the trainer
and strap chosen from a scan (APP-114, APP-701 to APP-708, APP-706,
APP-817). Files are written by the recorder's thread (IF-10).
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from wow.app.config import (
    Secrets, garmin_signed_in, save_secrets, save_settings,
)
from wow.app.device_manager import DeviceManager
from wow.core.devices import DeviceKind, FoundDevice
from wow.core.settings import (
    DeviceRef, Rejected, SettingKey, Settings, with_value,
)
from wow.core.view import Json, settings_screen
from wow.core.vocab import Problem

logger = logging.getLogger(__name__)

ACCOUNT_FIELD_MAX: Final[int] = 128
CHOOSABLE: Final[tuple[DeviceKind, ...]] = (DeviceKind.TRAINER,
                                            DeviceKind.HRM)
NOT_ON_SCREEN: Final[frozenset[str]] = frozenset(
    {SettingKey.TRAINER, SettingKey.HRM, SettingKey.ROUTE})


@dataclass(frozen=True)
class _Scan:
    kind: DeviceKind
    running: bool
    found: tuple[FoundDevice, ...] = ()


def _account_field(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > ACCOUNT_FIELD_MAX or any(
            c.isspace() for c in text):
        return None
    return text


class SettingsPanel:
    """The rider's settings and the Settings screen."""

    def __init__(self, data: Path, settings: Settings, account_set: bool,
                 devices: DeviceManager,
                 save: Callable[[Callable[[], None]], None],
                 on_change: Callable[[], None]) -> None:
        self._data = data
        self._settings = settings
        self._account_set = account_set
        self._devices = devices
        self._save = save
        self._on_change = on_change
        self._scan: _Scan | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self.on_account: Callable[[Secrets], None] = lambda _secrets: None

    @property
    def settings(self) -> Settings:
        """Return the settings in force."""
        return self._settings

    @property
    def account_set(self) -> bool:
        """Return whether an intervals.icu account is stored."""
        return self._account_set

    @property
    def garmin_signed_in(self) -> bool:
        """Return whether Garmin Connect tokens are stored."""
        return garmin_signed_in(self._data)

    def screen(self, cert_valid_until: str | None) -> Json:
        """Return the Settings screen."""
        scan = self._scan
        return settings_screen(
            self._settings, self._account_set, cert_valid_until,
            None if scan is None else (scan.kind, scan.running, scan.found),
            self.garmin_signed_in)

    def set(self, key: str, value: object) -> str | None:
        """Change one setting; return the problem, if any."""
        if key in NOT_ON_SCREEN:
            return Problem.BAD_REQUEST
        changed = with_value(self._settings, key, value)
        if isinstance(changed, Rejected):
            logger.warning("setting refused, %s", changed.text())
            return Problem.INVALID_VALUE
        self._store(changed)
        logger.info("setting %s changed", key)
        return None

    def keep_free_ride_level(self, pct: int) -> None:
        """Keep the free-ride level the rider last chose (APP-705)."""
        changed = with_value(self._settings, SettingKey.FREE_RIDE_LEVEL_PCT,
                             pct)
        if isinstance(changed, Settings):
            self._store(changed)

    def keep_route(self, file: str | None) -> None:
        """Keep the route the rider chose on Pre-ride (APP-902)."""
        changed = with_value(self._settings, SettingKey.ROUTE, file)
        if isinstance(changed, Settings):
            self._store(changed)
            logger.info("route chosen: %s", file)

    def set_account(self, athlete_id: object, api_key: object) -> str | None:
        """Store the intervals.icu account; return the problem, if any."""
        athlete, key = _account_field(athlete_id), _account_field(api_key)
        if athlete is None or key is None:
            return Problem.INVALID_VALUE
        secrets = Secrets(athlete, key)
        data = self._data
        self._save(lambda: save_secrets(data, secrets))
        self._account_set = True
        logger.info("intervals.icu account stored")
        self.on_account(secrets)
        return None

    def scan(self, kind: object) -> str | None:
        """Start a scan for a trainer or a strap (APP-114)."""
        if kind not in set(CHOOSABLE):
            return Problem.BAD_REQUEST
        if self._scan is not None and self._scan.running:
            return Problem.INVALID_STATE
        self._scan = _Scan(DeviceKind(str(kind)), True)
        self._spawn(self._run_scan())
        return None

    def choose(self, kind: object, address: object) -> str | None:
        """Use a device from the last scan; return the problem, if any."""
        scan = self._scan
        if scan is None or scan.running or kind != scan.kind:
            return Problem.INVALID_STATE
        found = [f for f in scan.found if f.address == address
                 and f.kind == scan.kind]
        if not found:
            return Problem.BAD_REQUEST
        device = found[0]
        ref = DeviceRef(device.address, device.name)
        self._store(replace(self._settings, trainer=ref)
                    if scan.kind == DeviceKind.TRAINER
                    else replace(self._settings, hrm=ref))
        self._spawn(self._devices.choose(scan.kind, device.address))
        logger.info("%s chosen: %s", scan.kind, device.address)
        return None

    async def close(self) -> None:
        """Stop a running scan."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_scan(self) -> None:
        scan = self._scan
        assert scan is not None
        found = await self._devices.scan()
        self._scan = _Scan(scan.kind, False, tuple(found))
        self._on_change()

    def _store(self, settings: Settings) -> None:
        self._settings = settings
        data = self._data
        self._save(lambda: save_settings(data, settings))

    def _spawn(self, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
