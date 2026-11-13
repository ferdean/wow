"""Read workouts from intervals.icu.

The intervals.icu adapter (3A, adapters/intervals_icu; ICD IF-08,
4.8.2; APP-201, APP-210, APP-818): HTTP basic authentication with the
user `API_KEY`, one 20 s timeout per call.
"""

from datetime import date
from typing import Any, Final

import aiohttp

from wow.ports.workouts import ProviderError

BASE_URL: Final[str] = "https://intervals.icu/api/v1"
HTTP_TIMEOUT: Final[float] = 20.0
API_USER: Final[str] = "API_KEY"


class IntervalsIcu:
    """Workout provider on the intervals.icu API."""

    def __init__(self, athlete_id: str, api_key: str,
                 base_url: str = BASE_URL) -> None:
        self._athlete = athlete_id
        self._headers = {
            "Authorization": aiohttp.encode_basic_auth(API_USER, api_key)}
        self._base = base_url.rstrip("/")

    async def planned(self, oldest: date, newest: date) -> list[Any]:
        """Return the calendar events between two local dates."""
        return await self._get(
            f"/athlete/{self._athlete}/events",
            {"oldest": oldest.isoformat(), "newest": newest.isoformat()})

    async def library(self) -> list[Any]:
        """Return the workouts of the library."""
        return await self._get(f"/athlete/{self._athlete}/workouts", {})

    async def _get(self, path: str, params: dict[str, str]) -> list[Any]:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        try:
            async with aiohttp.ClientSession(headers=self._headers,
                                             timeout=timeout) as session:
                async with session.get(self._base + path,
                                       params=params) as response:
                    response.raise_for_status()
                    body = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as error:
            raise ProviderError(f"{path}: {error!r}") from error
        if not isinstance(body, list):
            raise ProviderError(f"{path}: expected a list")
        return body
