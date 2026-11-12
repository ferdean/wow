"""Read the heart-rate strap over a GATT client.

The heart-rate strap on a GattClient: battery read, heart rate and
battery subscriptions (ICD IF-02, 4.2.3; APP-111, APP-113).
"""

import logging
from collections.abc import Callable

from wow.core import hr_codec, uuids
from wow.core.devices import HrSample, LinkState
from wow.core.ftms_codec import Dropped
from wow.ports.clock import Clock
from wow.ports.gatt import GattClient, GattError

logger = logging.getLogger(__name__)


class HrmLink:
    """The strap on its GATT client."""

    def __init__(
        self,
        clock: Clock,
        on_sample: Callable[[HrSample], None] | None = None,
    ) -> None:
        self._clock = clock
        self._client: GattClient | None = None
        self._link: LinkState = LinkState.NOT_CONFIGURED
        self._battery_pct: int | None = None
        self.on_sample = on_sample or (lambda _sample: None)

    def link(self) -> LinkState:
        """Return the link state."""
        return self._link

    def set_link(self, state: LinkState) -> None:
        """Set the link state."""
        self._link = state

    def battery_pct(self) -> int | None:
        """Return the battery level, if known."""
        return self._battery_pct

    async def attach(self, client: GattClient) -> None:
        """Take over a connected client and subscribe."""
        self._on_battery(await client.read(uuids.BATTERY_LEVEL))
        await client.subscribe(uuids.HEART_RATE_MEASUREMENT,
                               self._on_heart_rate)
        await client.subscribe(uuids.BATTERY_LEVEL, self._on_battery)
        self._client = client

    def detach(self) -> None:
        """Forget the client after the link was lost."""
        self._client = None

    async def close(self) -> None:
        """Stop reading."""
        client, self._client = self._client, None
        if client is None:
            return
        try:
            await client.close()
        except GattError as error:
            logger.warning("closing the strap link failed: %r", error)

    def _on_heart_rate(self, data: bytes) -> None:
        decoded = hr_codec.decode_heart_rate(data)
        if isinstance(decoded, Dropped):
            logger.warning("heart rate dropped (%s): %s", decoded.reason,
                           decoded.data.hex())
            return
        self.on_sample(HrSample(self._clock.monotonic(),
                                decoded.heart_rate_bpm, decoded.rr))

    def _on_battery(self, data: bytes) -> None:
        decoded = hr_codec.decode_battery_level(data)
        if isinstance(decoded, Dropped):
            logger.warning("battery level dropped: %s", decoded.data.hex())
            return
        if decoded.battery_pct is None:
            logger.warning("strap battery level out of range: raw %d",
                           decoded.raw)
        self._battery_pct = decoded.battery_pct
