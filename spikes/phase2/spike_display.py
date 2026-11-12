"""Phase 2 display spike S8: screen wake lock and Wi-Fi round trips on the
iPhone. Throwaway: not app code."""

from __future__ import annotations

import argparse
import json
import math
import socket
import ssl
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TextIO, cast
from urllib.parse import parse_qs, urlsplit

VERSION = "spike-0.1.7"
PAGE = Path(__file__).resolve().with_name("spike_display.html")
MAX_BEAT_GAP_S = 15.0
P95_LIMIT_MS = 200.0
STATUS_EVERY_S = 60.0
MAX_BODY = 1 << 20

Clock = Callable[[], float]
Printer = Callable[[str], None]


def utc_now() -> str:
    stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return stamp.replace("+00:00", "Z")


def minutes_seconds(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60:02d}:{whole % 60:02d}"


def percentile(values: Sequence[float], share: float) -> float:
    """Nearest rank: the smallest value with at least `share` of all values
    at or below it."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    return ordered[max(1, math.ceil(share * len(ordered))) - 1]


def finite(value: float) -> float | None:
    return None if math.isinf(value) else round(value, 1)


def round_trip_summary(rtts: Sequence[float],
                       failed: int) -> dict[str, Any]:
    """A failed round trip counts as slower than any that arrived."""
    ranked = [*rtts, *([math.inf] * failed)]
    if not ranked:
        return {"count": 0, "failed": 0, "p50_ms": None, "p95_ms": None,
                "max_ms": None}
    return {
        "count": len(ranked),
        "failed": failed,
        "p50_ms": finite(percentile(ranked, 0.50)),
        "p95_ms": finite(percentile(ranked, 0.95)),
        "max_ms": round(max(rtts), 1) if rtts else None,
    }


def longest_gap(stamps: Sequence[float]) -> float:
    return max((later - earlier
                for earlier, later in zip(stamps, stamps[1:])), default=0.0)


def redirect_target(host_header: str | None, path: str, port: int,
                    fallback: str) -> str:
    host = urlsplit(f"//{host_header}").hostname if host_header else None
    host = host or fallback
    if ":" in host:
        host = f"[{host}]"
    return f"https://{host}:{port}{path}"


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool | None
    detail: str


def checks(report: dict[str, Any], target_minutes: float) -> list[Check]:
    tapped = [lock for lock in report["locks"] if lock["trigger"] == "tap"]
    again = [lock for lock in report["locks"]
             if lock["trigger"] == "visible"]
    trips = report["round_trips"]
    screen_on = (report["duration_s"] >= target_minutes * 60
                 and report["longest_gap_s"] <= MAX_BEAT_GAP_S
                 and not report["hidden_at"])
    hidden = ", ".join(report["hidden_at"]) or "never"
    p95 = trips["p95_ms"]
    return [
        Check("A-17 wake lock granted on tap",
              any(lock["ok"] for lock in tapped) if tapped else False,
              describe_locks(tapped) or "no tap request seen"),
        Check(f"A-17 screen on for {target_minutes:g} min", screen_on,
              f"ran {minutes_seconds(report['duration_s'])}, longest gap "
              f"between beats {report['longest_gap_s']:.1f} s, page hidden "
              f"{hidden}"),
        Check("A-17 lock back after the page was hidden",
              any(lock["ok"] for lock in again) if again else None,
              describe_locks(again) or "not tried yet"),
        Check(f"A-34 round trip p95 <= {P95_LIMIT_MS:g} ms",
              p95 is not None and p95 <= P95_LIMIT_MS,
              f"{trips['count']} trips, p50 {trips['p50_ms']} ms, p95 "
              f"{p95} ms, max {trips['max_ms']} ms, failed "
              f"{trips['failed']}"),
    ]


def describe_locks(locks: Sequence[dict[str, Any]]) -> str:
    return "; ".join("granted" if lock["ok"] else f"refused ({lock['error']})"
                     for lock in locks)


def report_lines(report: dict[str, Any], target_minutes: float) -> list[str]:
    marks = {True: "PASS", False: "FAIL", None: "----"}
    lines = ["", "S8 result"]
    for check in checks(report, target_minutes):
        lines.append(f"  {marks[check.passed]}  {check.name}: {check.detail}")
    probe = [lock for lock in report["locks"] if lock["trigger"] == "load"]
    if probe:
        lines.append(f"  info  wake lock without a tap: "
                     f"{describe_locks(probe)}")
    return lines


@dataclass
class Session:
    """What the page reported, timed by the server's clock."""

    target_minutes: float
    clock: Clock = time.monotonic
    started: float | None = None
    stopped: float | None = None
    beats: list[float] = field(default_factory=list)
    rtts: list[float] = field(default_factory=list)
    failed: int = 0
    locks: list[dict[str, Any]] = field(default_factory=list)
    releases: list[dict[str, Any]] = field(default_factory=list)
    hidden_at: list[str] = field(default_factory=list)
    last_status: float = 0.0
    guard: threading.Lock = field(default_factory=threading.Lock,
                                  repr=False, compare=False)

    @property
    def running(self) -> bool:
        return self.started is not None and self.stopped is None

    def elapsed(self) -> float:
        if self.started is None:
            return 0.0
        end = self.stopped if self.stopped is not None else self.clock()
        return end - self.started

    def record(self, message: dict[str, Any]) -> list[str]:
        """Applies one message from the page; returns console lines."""
        handlers = {
            "load": self._on_load,
            "start": self._on_start,
            "lock": self._on_lock,
            "release": self._on_release,
            "visibility": self._on_visibility,
            "beat": self._on_beat,
            "stop": self._on_stop,
        }
        handler = handlers.get(str(message.get("type")))
        if handler is None:
            return [f"Unknown message from the page: {message}"]
        with self.guard:
            return handler(message)

    def report(self) -> dict[str, Any]:
        stamps = list(self.beats)
        if self.started is not None:
            stamps.append(self.stopped if self.stopped is not None
                          else self.clock())
        return {
            "duration_s": round(self.elapsed(), 1),
            "beats": max(len(self.beats) - 1, 0),
            "longest_gap_s": round(longest_gap(stamps), 1),
            "hidden_at": list(self.hidden_at),
            "locks": list(self.locks),
            "releases": list(self.releases),
            "round_trips": round_trip_summary(self.rtts, self.failed),
        }

    def _on_load(self, message: dict[str, Any]) -> list[str]:
        return [f"Page loaded: secure context {message.get('secure')}, "
                f"wake lock API {message.get('api')}",
                f"  {message.get('agent')}"]

    def _on_start(self, message: dict[str, Any]) -> list[str]:
        now = self.clock()
        self.started, self.stopped, self.last_status = now, None, now
        self.beats, self.rtts, self.failed = [now], [], 0
        self.hidden_at, self.releases = [], []
        self.locks = [lock for lock in self.locks
                      if lock["trigger"] == "load"]
        return [f"Run started; leave the phone untouched for "
                f"{self.target_minutes:g} min, then tap Stop."]

    def _on_lock(self, message: dict[str, Any]) -> list[str]:
        lock = {"trigger": str(message.get("trigger")),
                "ok": bool(message.get("ok")),
                "error": message.get("error"),
                "at": minutes_seconds(self.elapsed())}
        self.locks.append(lock)
        outcome = "granted" if lock["ok"] else f"refused: {lock['error']}"
        return [f"{lock['at']}  wake lock ({lock['trigger']}): {outcome}"]

    def _on_release(self, message: dict[str, Any]) -> list[str]:
        release = {"at": minutes_seconds(self.elapsed()),
                   "visibility": message.get("visibility")}
        self.releases.append(release)
        return [f"{release['at']}  wake lock released "
                f"(page {release['visibility']})"]

    def _on_visibility(self, message: dict[str, Any]) -> list[str]:
        state = message.get("state")
        at = minutes_seconds(self.elapsed())
        if self.running and state == "hidden":
            self.hidden_at.append(at)
        return [f"{at}  page {state}"]

    def _on_beat(self, message: dict[str, Any]) -> list[str]:
        if not self.running:
            return []
        now = self.clock()
        self.beats.append(now)
        self.rtts.extend(float(value) for value in message.get("rtt", []))
        self.failed += int(message.get("failed", 0))
        if now - self.last_status < STATUS_EVERY_S:
            return []
        self.last_status = now
        trips = round_trip_summary(self.rtts, self.failed)
        return [f"{minutes_seconds(self.elapsed())}  beats "
                f"{len(self.beats) - 1}, longest gap "
                f"{longest_gap(self.beats):.1f} s, round trips "
                f"{trips['count']}, p95 {trips['p95_ms']} ms, failed "
                f"{trips['failed']}, lock {message.get('lock')}"]

    def _on_stop(self, message: dict[str, Any]) -> list[str]:
        if not self.running:
            return ["Stop without a running test."]
        self.stopped = self.clock()
        return [*report_lines(self.report(), self.target_minutes),
                "Now switch to another app for about 10 s and come back; "
                "then press Ctrl+C here."]


class JsonLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file: TextIO = path.open("a", encoding="utf-8")
        self._guard = threading.Lock()

    def write(self, kind: str, **fields: Any) -> None:
        record = {"utc": utc_now(),
                  "mono_ms": time.monotonic_ns() // 1_000_000, "kind": kind}
        with self._guard:
            self._file.write(json.dumps({**record, **fields}) + "\n")
            self._file.flush()

    def close(self) -> None:
        self._file.close()


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes = b""
    content_type: str = "text/plain; charset=utf-8"
    headers: tuple[tuple[str, str], ...] = ()


class App:
    def __init__(self, session: Session, log: JsonLog, page: str,
                 root_cert: bytes, host: str, https_port: int,
                 out: Printer = print) -> None:
        self.session = session
        self.log = log
        self.page = page
        self.root_cert = root_cert
        self.host = host
        self.https_port = https_port
        self.out = out

    def index(self) -> Reply:
        body = self.page.replace("__TARGET_MINUTES__",
                                 f"{self.session.target_minutes:g}")
        return Reply(200, body.encode(), "text/html; charset=utf-8")

    def ping(self, query: str) -> Reply:
        number = parse_qs(query).get("n", ["0"])[0]
        return Reply(200, json.dumps({"n": number}).encode(),
                     "application/json")

    def event(self, body: bytes) -> Reply:
        try:
            message = json.loads(body)
        except ValueError:
            return Reply(400, b"not JSON")
        if not isinstance(message, dict):
            return Reply(400, b"not an object")
        self.log.write("page", message=message)
        for line in self.session.record(message):
            self.out(line)
        return Reply(204)

    def certificate(self) -> Reply:
        return Reply(200, self.root_cert, "application/x-x509-ca-cert",
                     (("Content-Disposition",
                       'attachment; filename="wow-root.crt"'),))

    def redirect(self, host_header: str | None, path: str) -> Reply:
        target = redirect_target(host_header, path, self.https_port,
                                 self.host)
        return Reply(301, b"", headers=(("Location", target),))

    def tls_failed(self, client: str, error: Exception) -> None:
        self.log.write("tls_error", client=client, error=repr(error))
        if "ALERT" in str(error):
            self.out(f"TLS handshake from {client} refused by the client "
                     f"({error}). If the page doesn't open, the iPhone "
                     f"doesn't trust the root yet.")

    def dropped(self, client: str, error: Exception) -> None:
        self.log.write("connection_dropped", client=client,
                       error=repr(error))

    def finish(self) -> None:
        report = self.session.report()
        self.log.write("report", **report)
        for line in report_lines(report, self.session.target_minutes):
            self.out(line)


class DisplayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int],
                 handler: type[BaseHTTPRequestHandler], app: App,
                 context: ssl.SSLContext | None) -> None:
        self.address_family = (socket.AF_INET6 if ":" in address[0]
                               else socket.AF_INET)
        self.app = app
        self.context = context
        super().__init__(address, handler)

    def server_bind(self) -> None:
        if self.address_family == socket.AF_INET6:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY,
                                   0)
        super().server_bind()

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Safari resets idle keep-alive connections when the page is
        hidden or reloaded; that is normal, so it only goes to the log."""
        error = sys.exc_info()[1]
        if isinstance(error, ConnectionError):
            self.app.dropped(str(client_address[0]), error)
            return
        super().handle_error(request, client_address)

    def finish_request(self, request: Any, client_address: Any) -> None:
        """The handshake runs here, in the request's own thread, so one
        slow or refusing client can't hold up the others."""
        if self.context is None:
            super().finish_request(request, client_address)
            return
        try:
            request.settimeout(10)
            secure = self.context.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError) as error:
            self.app.tls_failed(str(client_address[0]), error)
            return
        try:
            super().finish_request(secure, client_address)
        finally:
            secure.close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "wow-spike"
    timeout = 120

    @property
    def app(self) -> App:
        return cast(DisplayServer, self.server).app

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def send(self, reply: Reply) -> None:
        self.send_response(reply.status)
        self.send_header("Cache-Control", "no-store")
        if reply.status != 204:
            self.send_header("Content-Type", reply.content_type)
            self.send_header("Content-Length", str(len(reply.body)))
        for name, value in reply.headers:
            self.send_header(name, value)
        self.end_headers()
        if reply.body and self.command != "HEAD":
            self.wfile.write(reply.body)


class SecureHandler(Handler):
    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/":
            self.send(self.app.index())
        elif url.path == "/ping":
            self.send(self.app.ping(url.query))
        elif url.path == "/root.crt":
            self.send(self.app.certificate())
        else:
            self.send(Reply(404, b"not found"))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if urlsplit(self.path).path != "/event" or length > MAX_BODY:
            self.send(Reply(404, b"not found"))
            return
        self.send(self.app.event(self.rfile.read(length)))


class PlainHandler(Handler):
    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/root.crt":
            self.send(self.app.certificate())
        else:
            self.send(self.app.redirect(self.headers.get("Host"),
                                        self.path))


def tls_context(cert: Path, key: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    return context


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="wow.local")
    parser.add_argument("--bind", default="::" if socket.has_ipv6
                        else "0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    parser.add_argument("--plain-port", type=int, default=8080)
    parser.add_argument("--certs", type=Path, default=Path("certs"))
    parser.add_argument("--minutes", type=float, default=20.0)
    parser.add_argument("--logdir", type=Path, default=Path("logs"))
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args(sys.argv[1:])
    cert, key = args.certs / "server.crt", args.certs / "server.key"
    root = args.certs / "root.crt"
    if not all(path.exists() for path in (cert, key, root)):
        sys.exit(f"No certificates in {args.certs}; run "
                 f"'uv run spike_certs.py' first.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = JsonLog(args.logdir / f"display-{stamp}.jsonl")
    log.write("event", name="start", version=VERSION, argv=sys.argv[1:],
              python=sys.version.split()[0])
    app = App(Session(args.minutes), log, PAGE.read_text(),
              root.read_bytes(), args.host, args.port)
    secure = DisplayServer((args.bind, args.port), SecureHandler, app,
                           tls_context(cert, key))
    plain = DisplayServer((args.bind, args.plain_port), PlainHandler, app,
                          None)
    threading.Thread(target=plain.serve_forever, daemon=True).start()
    print(f"Logging to {log.path}")
    print(f"Root certificate: http://{args.host}:{args.plain_port}/root.crt")
    print(f"Test page:        https://{args.host}:{args.port}/")
    try:
        secure.serve_forever()
    except KeyboardInterrupt:
        app.finish()
    finally:
        plain.shutdown()
        secure.server_close()
        plain.server_close()
        log.write("event", name="end")
        log.close()


if __name__ == "__main__":
    main()
