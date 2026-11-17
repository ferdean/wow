"""Serve the display over WebSockets.

Display connections (ICD IF-06; 3A, web/hub): a complete view on every
change, at most 10 and at least 1 a second, the plan and route messages
before the first view that needs them; commands with their acks,
pings, and the page's paint reports and viewport (APP-802, APP-803,
APP-807). Tap and paint times go to the timing log (ICD 4.6.7).
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
KEPT_VIEWS: Final[int] = 64

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

    def route(self) -> Json | None:
        """Return the route message of the ride, if any."""
        ...

    def command(self, name: str, args: Mapping[str, Any]) -> str | None:
        """Carry out a command; return the problem, if any."""
        ...


class TimingSink(Protocol):
    """Where tap and paint times go."""

    def received(self) -> tuple[float, bool]:
        """Return when a command arrived and whether a procedure pends."""
        ...

    def tap(self, name: str, tap_ms: object, rtt_ms: object,
            arrival: tuple[float, bool]) -> None:
        """Note a carried-out command."""
        ...

    def painted(self, seq: int, data_ms: float | None, sent_ms: float,
                paint_ms: object, rtt_ms: object) -> None:
        """Note a painted view."""
        ...


@dataclass(frozen=True)
class Command:
    """A command from the page."""

    id: int
    name: str
    args: Mapping[str, Any]
    tap_mono_ms: object = None
    rtt_ms: object = None


@dataclass(frozen=True)
class Ping:
    """A latency probe from the page."""

    id: int
    t_page_ms: float


@dataclass(frozen=True)
class Painted:
    """The page reports that it painted a view."""

    seq: int
    paint_mono_ms: object = None
    rtt_ms: object = None


@dataclass(frozen=True)
class Viewport:
    """The page reports the size it has (A-56)."""

    width: object
    height: object


@dataclass(frozen=True)
class Malformed:
    """A message that could not be read."""

    id: int | None
    reason: str


Up = Command | Ping | Painted | Viewport | Malformed


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
        return Command(known_id, name, args, message.get("tap_mono_ms"),
                       message.get("rtt_ms"))
    if kind == "ping":
        stamp = message.get("t_page_ms")
        if known_id is None or not isinstance(stamp, (int, float)) or (
                isinstance(stamp, bool)):
            return Malformed(known_id, "bad ping")
        return Ping(known_id, float(stamp))
    if kind == "painted" and _whole(message.get("seq")):
        return Painted(int(message["seq"]), message.get("paint_mono_ms"),
                       message.get("rtt_ms"))
    if kind == "viewport":
        return Viewport(message.get("width"), message.get("height"))
    return Malformed(known_id, f"unknown message type {kind!r}")


class _Client:
    def __init__(self, socket: Socket) -> None:
        self.socket = socket
        self.seq = 0
        self.plan_id: str | None = None
        self.route_id: str | None = None
        self.stamps: dict[int, tuple[float | None, float]] = {}


class Hub:
    """The display connections."""

    def __init__(self, clock: Clock, source: ViewSource,
                 app_version: str, timing: TimingSink | None = None) -> None:
        self._clock = clock
        self._source = source
        self._app_version = app_version
        self._timing = timing
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
                              self._source.plan(), self._source.route())
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
        route = self._source.route()
        for client in list(self._clients):
            await self._send_view(client, view, plan, route)

    async def _send_view(self, client: _Client, view: Json,
                         plan: Json | None, route: Json | None) -> None:
        plan_id = None if plan is None else str(plan["plan_id"])
        if plan is not None and plan_id != client.plan_id:
            await self._send(client, plan)
        client.plan_id = plan_id
        route_id = None if route is None else str(route["route_id"])
        if route is not None and route_id != client.route_id:
            await self._send(client, route)
        client.route_id = route_id
        client.seq += 1
        sent_ms = round(self._clock.monotonic() * 1000, 1)
        client.stamps[client.seq] = (view.get("data_mono_ms"), sent_ms)
        client.stamps.pop(client.seq - KEPT_VIEWS, None)
        await self._send(client, {
            "type": "view", "seq": client.seq, "sent_mono_ms": sent_ms,
            **view})

    async def _send(self, client: _Client, message: Json) -> None:
        try:
            await client.socket.send_str(json.dumps(message))
        except (ConnectionError, RuntimeError) as error:
            logger.info("display gone: %r", error)
            self._clients.discard(client)

    async def _receive(self, client: _Client, text: str) -> None:
        match parse_up(text):
            case Command() as command:
                timing = self._timing
                arrival = None if timing is None else timing.received()
                error = self._source.command(command.name, command.args)
                if error is not None:
                    logger.warning("command %s refused: %s", command.name,
                                   error)
                elif timing is not None and arrival is not None:
                    timing.tap(command.name, command.tap_mono_ms,
                               command.rtt_ms, arrival)
                await self._send(client, _ack(command.id, error))
                self.changed()
            case Ping(id=ping_id, t_page_ms=stamp):
                await self._send(client, {
                    "type": "pong", "id": ping_id, "t_page_ms": stamp,
                    "pi_mono_ms": round(self._clock.monotonic() * 1000, 1)})
            case Painted(seq=seq, paint_mono_ms=paint, rtt_ms=rtt):
                stamps = client.stamps.get(seq)
                if self._timing is not None and stamps is not None:
                    self._timing.painted(seq, stamps[0], stamps[1], paint,
                                         rtt)
            case Viewport(width=width, height=height):
                logger.info("display viewport %.20s x %.20s", width, height)
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
