"""Connect to Bluetooth devices with bleak and BlueZ.

GattConnector on bleak 3.0.2 and BlueZ (ICD 4.3.3; AD-05, AD-15).

Before every connect the stale BlueZ link to the device is released
(F-33). Disconnect reports that arrive while bleak is still connecting
are dropped: bleak retries an aborted connect inside connect() and
reports the abort as a disconnect (F-32).
"""

from collections.abc import Callable, Sequence

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakDeviceNotFoundError, BleakError

from wow.adapters.bluez_stale import release_stale_link
from wow.ports.gatt import (
    Advertisement, DeviceNotFound, GattClient, GattError, GattTimeout,
    LinkLost, Uuid,
)
from typing import Final

LINK_ERRORS: Final[tuple[type[Exception], ...]] = (
    BleakError, OSError, EOFError)


class BleakConnector:
    """Connector on bleak."""

    def __init__(
        self,
        adapter: str,
        on_stale_release: Callable[[str, str], None] | None = None,
    ) -> None:
        self._adapter = adapter
        self.on_stale_release = on_stale_release
        self._generations: dict[str, int] = {}

    async def scan(
        self, service_uuids: Sequence[Uuid], duration: float
    ) -> list[Advertisement]:
        """Return the devices advertising any of the services."""
        try:
            found = await BleakScanner.discover(
                timeout=duration, return_adv=True,
                service_uuids=list(service_uuids),
                bluez={"adapter": self._adapter})
        except LINK_ERRORS as error:
            raise GattError(f"scan failed: {error!r}") from error
        return [
            Advertisement(
                address=device.address,
                name=data.local_name,
                rssi_dbm=data.rssi,
                service_uuids=tuple(data.service_uuids),
                service_data=dict(data.service_data),
            )
            for device, data in found.values()
        ]

    async def connect(
        self, address: str, timeout: float, on_lost: Callable[[int], None]
    ) -> GattClient:
        """Connect to a device; on_lost gets the connection number."""
        released = await release_stale_link(address, self._adapter)
        if self.on_stale_release is not None:
            self.on_stale_release(address, released)
        generation = self._generations.get(address, 0) + 1
        self._generations[address] = generation
        guard = _DisconnectGuard(generation, on_lost)
        client = BleakClient(address, disconnected_callback=guard.report,
                             timeout=timeout,
                             bluez={"adapter": self._adapter})
        try:
            await client.connect()
        except BleakDeviceNotFoundError as error:
            raise DeviceNotFound(address) from error
        except TimeoutError as error:
            raise GattTimeout(address) from error
        except LINK_ERRORS as error:
            raise GattError(f"connect failed: {error!r}") from error
        guard.armed = True
        return BleakGattClient(client, address, generation, guard)


class _DisconnectGuard:
    def __init__(
        self, generation: int, on_lost: Callable[[int], None]
    ) -> None:
        self.generation = generation
        self.armed = False
        self._on_lost = on_lost

    def report(self, _client: BleakClient) -> None:
        if self.armed:
            self.armed = False
            self._on_lost(self.generation)


class BleakGattClient:
    """Client on bleak."""

    def __init__(
        self,
        client: BleakClient,
        address: str,
        generation: int,
        guard: _DisconnectGuard,
    ) -> None:
        self._client = client
        self._address = address
        self._generation = generation
        self._guard = guard

    @property
    def address(self) -> str:
        """Return the address of the device."""
        return self._address

    @property
    def generation(self) -> int:
        """Return the number of this connection."""
        return self._generation

    def _error(self, error: Exception) -> GattError:
        if not self._client.is_connected:
            return LinkLost(f"{self._address}: {error!r}")
        return GattError(f"{self._address}: {error!r}")

    async def read(self, char: Uuid) -> bytes:
        """Read a characteristic."""
        try:
            return bytes(await self._client.read_gatt_char(char))
        except LINK_ERRORS as error:
            raise self._error(error) from error

    async def write(self, char: Uuid, data: bytes) -> None:
        """Write a characteristic."""
        try:
            await self._client.write_gatt_char(char, data, response=True)
        except LINK_ERRORS as error:
            raise self._error(error) from error

    async def subscribe(
        self, char: Uuid, on_value: Callable[[bytes], None]
    ) -> None:
        """Call on_value for each notification of a characteristic."""
        def received(_char: BleakGATTCharacteristic, data: bytearray) -> None:
            on_value(bytes(data))

        try:
            await self._client.start_notify(char, received)
        except LINK_ERRORS as error:
            raise self._error(error) from error

    async def close(self) -> None:
        """Close the connection."""
        self._guard.armed = False
        try:
            await self._client.disconnect()
        except LINK_ERRORS as error:
            raise GattError(f"{self._address}: {error!r}") from error
