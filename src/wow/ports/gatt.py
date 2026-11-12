"""Define the Bluetooth ports; the app is the GATT client.

Bluetooth ports: the app is the GATT client (ICD IF-03, 4.3.2; AD-21).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

Uuid = str


@dataclass(frozen=True)
class Advertisement:
    """A device seen while scanning."""

    address: str
    name: str | None
    rssi_dbm: int
    service_uuids: tuple[Uuid, ...]
    service_data: Mapping[Uuid, bytes]


class GattError(Exception):
    """Base of Bluetooth failures."""

    pass


class LinkLost(GattError):
    """The link to the device was lost."""

    pass


class GattTimeout(GattError):
    """The device did not answer in time."""

    pass


class DeviceNotFound(GattError):
    """The device was not found."""

    pass


class GattClient(Protocol):
    """A connection to one device."""

    @property
    def address(self) -> str:
        """Return the address of the device."""
        ...

    @property
    def generation(self) -> int:
        """Return the number of this connection."""
        ...

    async def read(self, char: Uuid) -> bytes:
        """Read a characteristic."""
        ...

    async def write(self, char: Uuid, data: bytes) -> None:
        """Write a characteristic, with or without a response."""
        ...

    async def subscribe(
        self, char: Uuid, on_value: Callable[[bytes], None]
    ) -> None:
        """Call on_value for each notification of a characteristic."""
        ...

    async def close(self) -> None:
        """Close the connection."""
        ...


class GattConnector(Protocol):
    """Finds and connects to devices."""

    async def scan(
        self, service_uuids: Sequence[Uuid], duration: float
    ) -> list[Advertisement]:
        """Return the devices advertising any of the services."""
        ...

    async def connect(
        self, address: str, timeout: float, on_lost: Callable[[int], None]
    ) -> GattClient:
        """Connect to a device; on_lost gets the connection number."""
        ...
