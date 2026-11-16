"""A display on the real WebSocket, for L5 and L6 tests."""

import asyncio
import json
import ssl
import time
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from tests.support.app_rig import TLS
from wow.ports.clock import Clock
from wow.app.main import App


def trusting() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=TLS / "root.crt")


class Page:
    """A display on the real WebSocket."""

    def __init__(self, socket: aiohttp.ClientWebSocketResponse) -> None:
        self.socket = socket
        self.received: list[tuple[float, dict[str, Any]]] = []
        self._next_id = 0

    async def command(self, name: str, **args: Any) -> dict[str, Any]:
        self._next_id += 1
        await self.socket.send_str(json.dumps(
            {"type": "command", "id": self._next_id, "name": name,
             "args": args}))
        return await self.wait_for(lambda m: m["type"] == "ack"
                                   and m["id"] == self._next_id)

    async def wait_for(self, wanted: Any, timeout: float = 5.0
                       ) -> dict[str, Any]:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            message = await self.receive(end - time.monotonic())
            if message is not None and wanted(message):
                return message
        raise AssertionError("message not received")

    async def receive(self, timeout: float) -> dict[str, Any] | None:
        try:
            message = await self.socket.receive_json(timeout=max(timeout,
                                                                 0.01))
        except TimeoutError:
            return None
        self.received.append((time.monotonic(), message))
        return dict(message)

    async def collect(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            await self.receive(end - time.monotonic())

    def views(self) -> list[tuple[float, dict[str, Any]]]:
        return [(t, m) for t, m in self.received if m["type"] == "view"]


async def open_page(app: App, session: aiohttp.ClientSession) -> Page:
    https, _ = app.ports
    socket = await session.ws_connect(f"wss://127.0.0.1:{https}/ws",
                                      ssl=trusting())
    page = Page(socket)
    first = await page.receive(5.0)
    assert first is not None and first["type"] == "hello"
    return page


class FakeSocket:
    """A page's socket on the test clock, for the hub."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self.sent: list[tuple[float, dict[str, Any]]] = []
        self.incoming: asyncio.Queue[str | None] = asyncio.Queue()
        self.closed = False

    async def send_str(self, data: str) -> None:
        self.sent.append((self._clock.monotonic(), json.loads(data)))

    async def close(self, *, code: int = 1000, message: bytes = b"") -> bool:
        self.closed = True
        await self.incoming.put(None)
        return True

    async def messages(self) -> AsyncIterator[str]:
        while (text := await self.incoming.get()) is not None:
            yield text

    def of_type(self, kind: str) -> list[tuple[float, dict[str, Any]]]:
        return [(t, m) for t, m in self.sent if m["type"] == kind]
