"""A display on the real WebSocket, for L5 and L6 tests."""

import json
import ssl
import time
from typing import Any

import aiohttp

from tests.support.app_rig import TLS
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
