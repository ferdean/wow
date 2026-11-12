"""Serve the display over WebSockets.

Display connections (ICD IF-06; 3A, web/hub): a complete view on every
change, at most 10 and at least 1 a second; commands, pings and paint
reports from the page (APP-803, APP-807).

Slice SL-02: views, plans, commands with their acks, pings. Tap and paint
times go to `timing.jsonl` from SL-11.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol

from aiohttp import WSMsgType, web

from wow.ports.clock import Clock
from wow.core.vocab import Problem

logger = logging.getLogger(__name__)

PROTOCOL: Final[int] = 1
MIN_GAP: Final[float] = 0.1
MAX_GAP: Final[float] = 1.0
HEARTBEAT: Final[float] = 5.0

Json = dict[str, Any]


class Socket(Protocol):
    """The part of a WebSocket the hub uses."""

    async def send_str(self, data: str) -> None:
        """Send a text message."""
        ...

    async def close(self, *, code: int = ..., message: bytes = ...
                    ) -> bool:
        """Close the socket."""
        ...


class ViewSource(Protocol):
    """Where the hub gets what it sends and where commands go."""

    def view(self) -> Json:
        """Return the current view state."""
        ...

    def plan(self) -> Json | None:
        """Return the plan message of the ride, if any."""
        ...

    def command(self, name: str, args: Mapping[str, Any]) -> str | None:
        """Carry out a command; return the problem, if any."""
        ...


@dataclass(frozen=True)
class Command:
    """A command from the page."""

    id: int
    name: str
    args: Mapping[str, Any]


@dataclass(frozen=True)
class Ping:
    """A latency probe from the page."""

    id: int
    t_page_ms: float


@dataclass(frozen=True)
class Painted:
    """The page reports that it painted a view."""

    seq: int


@dataclass(frozen=True)
class Malformed:
    """A message that could not be read."""

    id: int | None
    reason: str


Up = Command | Ping | Painted | Malformed


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_up(text: str) -> Up:
    """Parse a message from the page."""
    try:
        message = json.loads(text)
    except ValueError:
        return Malformed(None, "not JSON")
    if not isinstance(message, dict):
        return Malformed(None, "not an object")
    raw_id = message.get("id")
    known_id = raw_id if _whole(raw_id) else None
    kind = message.get("type")
    if kind == "command":
        name, args = message.get("name"), message.get("args", {})
        if known_id is None or not isinstance(name, str) or not isinstance(
                args, dict):
            return Malformed(known_id, "bad command")
        return Command(known_id, name, args)
    if kind == "ping":
        stamp = message.get("t_page_ms")
        if known_id is None or not isinstance(stamp, (int, float)) or (
                isinstance(stamp, bool)):
            return Malformed(known_id, "bad ping")
        return Ping(known_id, float(stamp))
    if kind == "painted" and _whole(message.get("seq")):
        return Painted(int(message["seq"]))
    return Malformed(known_id, f"unknown message type {kind!r}")


class _Client:
    def __init__(self, socket: Socket) -> None:
        self.socket = socket
        self.seq = 0
        self.plan_id: str | None = None


class Hub:
    """The display connections."""

    def __init__(self, clock: Clock, source: ViewSource,
                 app_version: str) -> None:
        self._clock = clock
        self._source = source
        self._app_version = app_version
        self._clients: set[_Client] = set()
        self._dirty = False
        self._wake = asyncio.Event()

    @property
    def clients(self) -> int:
        """Return the number of connected pages."""
        return len(self._clients)

    def changed(self) -> None:
        """Tell the hub the view changed."""
        self._dirty = True
        self._wake.set()

    async def run(self) -> None:
        """Push views to the pages until closed."""
        while True:
            await self._send_views()
            sent = self._clock.monotonic()
            await self._wait_for_change(sent + MAX_GAP)
            await self._clock.sleep_until(sent + MIN_GAP)

    async def close(self) -> None:
        """Close all pages and stop."""
        for client in list(self._clients):
            await client.socket.close(code=1001, message=b"shutting down")
        self._clients.clear()

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        """Serve one WebSocket request."""
        socket = web.WebSocketResponse(heartbeat=HEARTBEAT)
        await socket.prepare(request)
        await self.serve(socket, _texts(socket))
        return socket

    async def serve(self, socket: Socket, messages: AsyncIterator[str]
                    ) -> None:
        """Serve one page from its socket and messages."""
        client = _Client(socket)
        await self._send(client, {"type": "hello",
                                  "app_version": self._app_version,
                                  "protocol": PROTOCOL})
        await self._send_view(client, self._source.view(),
                              self._source.plan())
        self._clients.add(client)
        try:
            async for text in messages:
                await self._receive(client, text)
        finally:
            self._clients.discard(client)

    async def _wait_for_change(self, deadline: float) -> None:
        if self._dirty:
            return
        self._wake.clear()
        sleeper = asyncio.ensure_future(self._clock.sleep_until(deadline))
        waiter = asyncio.ensure_future(self._wake.wait())
        try:
            await asyncio.wait({sleeper, waiter},
                               return_when=asyncio.FIRST_COMPLETED)
        finally:
            sleeper.cancel()
            waiter.cancel()

    async def _send_views(self) -> None:
        self._dirty = False
        if not self._clients:
            return
        view, plan = self._source.view(), self._source.plan()
        for client in list(self._clients):
            await self._send_view(client, view, plan)

    async def _send_view(self, client: _Client, view: Json,
                         plan: Json | None) -> None:
        plan_id = None if plan is None else str(plan["plan_id"])
        if plan is not None and plan_id != client.plan_id:
            await self._send(client, plan)
        client.plan_id = plan_id
        client.seq += 1
        await self._send(client, {
            "type": "view", "seq": client.seq,
            "sent_mono_ms": round(self._clock.monotonic() * 1000, 1),
            **view})

    async def _send(self, client: _Client, message: Json) -> None:
        try:
            await client.socket.send_str(json.dumps(message))
        except (ConnectionError, RuntimeError) as error:
            logger.info("display gone: %r", error)
            self._clients.discard(client)

    async def _receive(self, client: _Client, text: str) -> None:
        match parse_up(text):
            case Command(id=command_id, name=name, args=args):
                error = self._source.command(name, args)
                if error is not None:
                    logger.warning("command %s refused: %s", name, error)
                await self._send(client, _ack(command_id, error))
                self.changed()
            case Ping(id=ping_id, t_page_ms=stamp):
                await self._send(client, {
                    "type": "pong", "id": ping_id, "t_page_ms": stamp,
                    "pi_mono_ms": round(self._clock.monotonic() * 1000, 1)})
            case Painted():
                pass
            case Malformed(id=bad_id, reason=reason):
                logger.warning("display message refused (%s): %.200s",
                               reason, text)
                if bad_id is not None:
                    await self._send(client, _ack(bad_id, Problem.BAD_REQUEST))


async def _texts(socket: web.WebSocketResponse) -> AsyncIterator[str]:
    async for message in socket:
        if message.type == WSMsgType.TEXT:
            yield str(message.data)


def _ack(command_id: int, error: str | None) -> Json:
    ack: Json = {"type": "ack", "id": command_id, "ok": error is None}
    if error is not None:
        ack["error"] = error
    return ack
