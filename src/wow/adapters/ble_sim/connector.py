"""Connect in-process to simulated GATT servers.

In-process GattConnector over simulated GATT servers (ICD 4.3.4).
"""

from collections.abc import Callable, Sequence

from wow.adapters.ble_sim.server import GattServer
from wow.ports.clock import Clock
from wow.ports.gatt import (
    Advertisement, DeviceNotFound, GattClient, GattError, LinkLost, Uuid,
)
from typing import Final

CONNECT_TIME: Final[float] = 2.3
SCAN_POLL: Final[float] = 0.25
READ_TIME: Final[float] = 0.03
WRITE_TIMES: Final[tuple[float, ...]] = (0.095, 0.195)


class SimConnector:
    """Connector over simulated servers."""

    def __init__(self, clock: Clock, servers: Sequence[GattServer]) -> None:
        self._clock = clock
        self._servers = {s.advertisement().address.upper(): s for s in servers}
        self._generations: dict[str, int] = {}
        self._clients: dict[str, SimClient] = {}

    async def scan(
        self, service_uuids: Sequence[Uuid], duration: float
    ) -> list[Advertisement]:
        """Return the simulated devices that advertise."""
        await self._clock.sleep_until(self._clock.monotonic() + duration)
        wanted = set(service_uuids)
        return [
            server.advertisement()
            for server in self._servers.values()
            if server.advertising()
            and (not wanted
                 or wanted & set(server.advertisement().service_uuids))
        ]

    async def connect(
        self, address: str, timeout: float, on_lost: Callable[[int], None]
    ) -> GattClient:
        """Connect to a simulated device."""
        server = await self._advertising(address,
                                         self._clock.monotonic() + timeout)
        await self._clock.sleep_until(self._clock.monotonic() + CONNECT_TIME)
        generation = self._generations.get(address.upper(), 0) + 1
        self._generations[address.upper()] = generation
        server.on_connect()
        client = SimClient(self._clock, server, address, generation, on_lost)
        self._clients[address.upper()] = client
        return client

    def lose_link(self, address: str) -> None:
        """Drop the link to a device, as if it went out of range."""
        client = self._clients.get(address.upper())
        if client is not None:
            client.lose_link()

    async def _advertising(self, address: str, deadline: float) -> GattServer:
        while True:
            now = self._clock.monotonic()
            server = self._servers.get(address.upper())
            in_time = now + CONNECT_TIME <= deadline
            if server is not None and server.advertising() and in_time:
                return server
            if now >= deadline:
                raise DeviceNotFound(address)
            await self._clock.sleep_until(min(now + SCAN_POLL, deadline))


class SimClient:
    """Client of one simulated device."""

    def __init__(
        self,
        clock: Clock,
        server: GattServer,
        address: str,
        generation: int,
        on_lost: Callable[[int], None],
    ) -> None:
        self._clock = clock
        self._server = server
        self._address = address
        self._generation = generation
        self._on_lost = on_lost
        self._connected = True
        self._writes = 0

    @property
    def address(self) -> str:
        """Return the address of the device."""
        return self._address

    @property
    def generation(self) -> int:
        """Return the number of this connection."""
        return self._generation

    @property
    def connected(self) -> bool:
        """Return whether the link is up."""
        return self._connected

    async def read(self, char: Uuid) -> bytes:
        """Read a characteristic."""
        self._check()
        await self._clock.sleep_until(self._clock.monotonic() + READ_TIME)
        self._check()
        try:
            return self._server.on_read(char)
        except KeyError as error:
            raise GattError(f"no readable characteristic {char}") from error

    async def write(self, char: Uuid, data: bytes) -> None:
        """Write a characteristic."""
        self._check()
        try:
            self._server.on_write(char, data)
        except KeyError as error:
            raise GattError(f"no writable characteristic {char}") from error
        took = WRITE_TIMES[self._writes % len(WRITE_TIMES)]
        self._writes += 1
        await self._clock.sleep_until(self._clock.monotonic() + took)
        self._check()

    async def subscribe(
        self, char: Uuid, on_value: Callable[[bytes], None]
    ) -> None:
        """Call on_value for each notification of a characteristic."""
        self._check()

        def deliver(data: bytes) -> None:
            if self._connected:
                on_value(data)

        try:
            self._server.on_subscribe(char, deliver)
        except KeyError as error:
            raise GattError(f"cannot subscribe to {char}") from error

    async def close(self) -> None:
        """Close the connection."""
        if self._connected:
            self._connected = False
            self._server.on_disconnect()

    def lose_link(self) -> None:
        """Drop the link, as if the device went out of range."""
        if self._connected:
            self._connected = False
            self._server.on_disconnect()
            self._on_lost(self._generation)

    def _check(self) -> None:
        if not self._connected:
            raise LinkLost(self._address)
