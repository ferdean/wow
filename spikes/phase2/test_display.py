import json
import shutil
import socket
import struct
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

import spike_certs
import spike_display as display

needs_openssl = pytest.mark.skipif(shutil.which("openssl") is None,
                                   reason="openssl command not installed")


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_percentile_is_nearest_rank() -> None:
    values = list(range(1, 101))
    assert display.percentile(values, 0.95) == 95
    assert display.percentile(values, 0.50) == 50
    assert display.percentile([7.0], 0.95) == 7.0


def test_percentile_needs_values() -> None:
    with pytest.raises(ValueError):
        display.percentile([], 0.95)


def test_failed_round_trips_count_as_slowest() -> None:
    summary = display.round_trip_summary([10.0] * 94, failed=6)
    assert summary["count"] == 100
    assert summary["p50_ms"] == 10.0
    assert summary["p95_ms"] is None
    assert summary["max_ms"] == 10.0


def test_round_trip_summary_without_samples() -> None:
    summary = display.round_trip_summary([], failed=0)
    assert summary["count"] == 0
    assert summary["p95_ms"] is None


def test_longest_gap() -> None:
    assert display.longest_gap([0.0, 5.0, 16.5, 20.0]) == 11.5
    assert display.longest_gap([3.0]) == 0.0


@pytest.mark.parametrize("host, expected", [
    ("wow.local:8080", "https://wow.local:8443/x?y=1"),
    ("192.168.1.20:8080", "https://192.168.1.20:8443/x?y=1"),
    ("[fe80::1]:8080", "https://[fe80::1]:8443/x?y=1"),
    (None, "https://wow.local:8443/x?y=1"),
])
def test_redirect_target(host: str | None, expected: str) -> None:
    assert display.redirect_target(host, "/x?y=1", 8443,
                                   "wow.local") == expected


def run_session(clock: FakeClock, minutes: float, beat_s: float,
                rtt: float) -> display.Session:
    session = display.Session(target_minutes=20, clock=clock)
    session.record({"type": "lock", "trigger": "load", "ok": False,
                    "error": "NotAllowedError: no gesture"})
    session.record({"type": "start"})
    session.record({"type": "lock", "trigger": "tap", "ok": True})
    end = clock.now + minutes * 60
    while clock.now + beat_s <= end:
        clock.now += beat_s
        session.record({"type": "beat", "rtt": [rtt] * 20, "failed": 0,
                        "lock": True})
    clock.now = end
    session.record({"type": "stop"})
    return session


def by_name(session: display.Session) -> dict[str, display.Check]:
    return {check.name.split(" ", 1)[1]: check
            for check in display.checks(session.report(), 20)}


def test_twenty_quiet_minutes_pass() -> None:
    session = run_session(FakeClock(), minutes=20.1, beat_s=5.0, rtt=30.0)
    results = by_name(session)
    assert results["wake lock granted on tap"].passed is True
    assert results["screen on for 20 min"].passed is True
    assert results["lock back after the page was hidden"].passed is None
    assert results["round trip p95 <= 200 ms"].passed is True


def test_screen_lock_shows_as_gap_and_hidden_page() -> None:
    clock = FakeClock()
    session = run_session(clock, minutes=10, beat_s=5.0, rtt=30.0)
    session.stopped = None
    session.record({"type": "visibility", "state": "hidden"})
    clock.now += 90
    session.record({"type": "beat", "rtt": [], "failed": 0})
    for _ in range(120):
        clock.now += 5
        session.record({"type": "beat", "rtt": [], "failed": 0})
    session.record({"type": "stop"})
    report = session.report()
    assert report["hidden_at"] == ["10:00"]
    assert report["longest_gap_s"] == 90.0
    assert by_name(session)["screen on for 20 min"].passed is False


def test_slow_wifi_fails_round_trip_check() -> None:
    session = run_session(FakeClock(), minutes=20.1, beat_s=5.0, rtt=250.0)
    assert by_name(session)["round trip p95 <= 200 ms"].passed is False


def test_lock_back_after_hidden_counts_after_stop() -> None:
    session = run_session(FakeClock(), minutes=20.1, beat_s=5.0, rtt=30.0)
    session.record({"type": "visibility", "state": "hidden"})
    session.record({"type": "visibility", "state": "visible"})
    session.record({"type": "lock", "trigger": "visible", "ok": True})
    results = by_name(session)
    assert results["lock back after the page was hidden"].passed is True
    assert results["screen on for 20 min"].passed is True


def test_beats_before_start_are_ignored() -> None:
    session = display.Session(target_minutes=20, clock=FakeClock())
    assert session.record({"type": "beat", "rtt": [5.0]}) == []
    assert session.report()["round_trips"]["count"] == 0


def test_unknown_message_is_reported() -> None:
    session = display.Session(target_minutes=20)
    assert "Unknown" in session.record({"type": "nonsense"})[0]


def test_report_mentions_probe_without_tap() -> None:
    session = run_session(FakeClock(), minutes=20.1, beat_s=5.0, rtt=30.0)
    lines = display.report_lines(session.report(), 20)
    assert any("without a tap" in line and "NotAllowedError" in line
               for line in lines)


@pytest.fixture
def certs(tmp_path: Path) -> spike_certs.Files:
    if shutil.which("openssl") is None:
        pytest.skip("openssl command not installed")
    files, made_root = spike_certs.make(tmp_path / "certs", "wow.local",
                                        new_root=False, constraints="full")
    assert made_root
    return files


def text_of(cert: Path) -> str:
    return spike_certs.run(["openssl", "x509", "-noout", "-text", "-in",
                            str(cert)])


@needs_openssl
def test_server_certificate_meets_apple_rules(
        certs: spike_certs.Files) -> None:
    text = text_of(certs.server_cert)
    assert "DNS:wow.local" in text
    assert "TLS Web Server Authentication" in text
    assert "sha256WithRSAEncryption" in text
    assert "Public-Key: (2048 bit)" in text
    assert spike_certs.SERVER_DAYS <= 825


@needs_openssl
def test_root_is_a_constrained_ca(certs: spike_certs.Files) -> None:
    text = text_of(certs.root_cert)
    assert "CA:TRUE" in text
    assert "Permitted:" in text and "DNS:wow.local" in text


@needs_openssl
def test_second_run_keeps_the_root(certs: spike_certs.Files) -> None:
    before = certs.root_cert.read_bytes()
    _, made_root = spike_certs.make(certs.folder, "wow.local",
                                    new_root=False, constraints="full")
    assert not made_root
    assert certs.root_cert.read_bytes() == before


@needs_openssl
def test_root_cannot_vouch_for_other_names(
        certs: spike_certs.Files, tmp_path: Path) -> None:
    rogue = tmp_path / "rogue"
    rogue.mkdir()
    for name in ("root.key", "root.crt"):
        shutil.copy(certs.folder / name, rogue / name)
    with pytest.raises(RuntimeError, match="subtree"):
        spike_certs.make(rogue, "bank.example", new_root=False,
                         constraints="full")


@pytest.fixture
def served(certs: spike_certs.Files,
           tmp_path: Path) -> Iterator[tuple[int, int, list[str]]]:
    lines: list[str] = []
    log = display.JsonLog(tmp_path / "logs" / "display.jsonl")
    app = display.App(display.Session(20), log, display.PAGE.read_text(),
                      certs.root_cert.read_bytes(), "wow.local", 0,
                      out=lines.append)
    context = display.tls_context(certs.server_cert, certs.server_key)
    secure = display.DisplayServer(("127.0.0.1", 0), display.SecureHandler,
                                   app, context)
    plain = display.DisplayServer(("127.0.0.1", 0), display.PlainHandler,
                                  app, None)
    app.https_port = secure.server_address[1]
    for server in (secure, plain):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield secure.server_address[1], plain.server_address[1], lines
    for server in (secure, plain):
        server.shutdown()
        server.server_close()
    log.close()


def exchange(port: int, request: bytes,
             context: ssl.SSLContext | None) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        stream = (context.wrap_socket(raw, server_hostname="wow.local")
                  if context else raw)
        stream.sendall(request)
        chunks = []
        while chunk := stream.recv(65536):
            chunks.append(chunk)
        return b"".join(chunks)


def trusting(root: Path) -> ssl.SSLContext:
    return ssl.create_default_context(cafile=str(root))


def get(path: str) -> bytes:
    return (f"GET {path} HTTP/1.1\r\nHost: wow.local\r\n"
            f"Connection: close\r\n\r\n").encode()


@needs_openssl
def test_page_served_over_verified_tls(
        served: tuple[int, int, list[str]],
        certs: spike_certs.Files) -> None:
    secure_port, _, _ = served
    reply = exchange(secure_port, get("/"), trusting(certs.root_cert))
    assert reply.startswith(b"HTTP/1.1 200")
    assert b"navigator.wakeLock.request" in reply
    assert b"const TARGET_MINUTES = 20;" in reply


@needs_openssl
def test_ping_and_event(served: tuple[int, int, list[str]],
                        certs: spike_certs.Files) -> None:
    secure_port, _, lines = served
    context = trusting(certs.root_cert)
    assert b'{"n": "7"}' in exchange(secure_port, get("/ping?n=7"), context)
    body = json.dumps({"type": "lock", "trigger": "tap",
                       "ok": True}).encode()
    request = (b"POST /event HTTP/1.1\r\nHost: wow.local\r\n"
               b"Content-Type: application/json\r\nConnection: close\r\n"
               + f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    assert exchange(secure_port, request, context).startswith(
        b"HTTP/1.1 204")
    assert any("wake lock (tap): granted" in line for line in lines)


@needs_openssl
def test_untrusting_client_is_reported(
        served: tuple[int, int, list[str]]) -> None:
    secure_port, _, lines = served
    with pytest.raises(ssl.SSLCertVerificationError):
        exchange(secure_port, get("/"), ssl.create_default_context())
    for _ in range(50):
        if lines:
            break
        threading.Event().wait(0.02)
    assert any("trust the root" in line for line in lines)


@needs_openssl
def test_plain_port_serves_root_and_redirects(
        served: tuple[int, int, list[str]],
        certs: spike_certs.Files) -> None:
    secure_port, plain_port, _ = served
    reply = exchange(plain_port, get("/root.crt"), None)
    assert b"application/x-x509-ca-cert" in reply
    assert certs.root_cert.read_bytes() in reply
    moved = exchange(plain_port, get("/"), None)
    assert moved.startswith(b"HTTP/1.1 301")
    assert f"Location: https://wow.local:{secure_port}/".encode() in moved


@needs_openssl
def test_client_reset_is_logged_not_printed(
        served: tuple[int, int, list[str]], certs: spike_certs.Files,
        capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    secure_port, _, _ = served
    raw = socket.create_connection(("127.0.0.1", secure_port), timeout=5)
    stream = trusting(certs.root_cert).wrap_socket(
        raw, server_hostname="wow.local")
    stream.sendall(b"GET /ping HTTP/1.1\r\nHost: wow.local\r\n")
    stream.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                      struct.pack("ii", 1, 0))
    stream.close()
    log = tmp_path / "logs" / "display.jsonl"
    for _ in range(100):
        if "connection_dropped" in log.read_text():
            break
        threading.Event().wait(0.02)
    assert "connection_dropped" in log.read_text()
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("mode, permitted, excluded", [
    ("full", True, True),
    ("dns", True, False),
    ("none", False, False),
])
def test_constraint_modes(mode: str, permitted: bool,
                          excluded: bool) -> None:
    config = spike_certs.root_config("wow.local", mode)
    assert f"(wow.local, {mode})" in config
    assert ("permitted;DNS:wow.local" in config) is permitted
    assert ("excluded;IP" in config) is excluded


@needs_openssl
@pytest.mark.parametrize("mode", ["dns", "none"])
def test_other_modes_issue_a_valid_chain(mode: str, tmp_path: Path) -> None:
    files, made_root = spike_certs.make(tmp_path / mode, "wow.local",
                                        new_root=True, constraints=mode)
    assert made_root
    assert f"wow.local, {mode}" in text_of(files.root_cert)
