"""HTTPS and HTTP sites over real TLS on localhost (L5; ICD IF-07)."""

import ssl
from collections.abc import AsyncIterator
from pathlib import Path

import aiohttp
import pytest
import pytest_asyncio
from yarl import URL

from tests.support.app_rig import INDEX, TLS, app_config
from wow.adapters.clock_system import SystemClock
from wow.app.main import App
from wow.web.server import ASSETS_CACHE, redirect_target

KEY_PATHS = (
    "/setup/root.key", "/setup/server.key", "/setup/../tls/server.key",
    "/setup/%2e%2e/tls/server.key", "/setup/root.crt/../server.key",
    "/var/lib/wow/tls/server.key", "/server.key",
)


DECOY = "-----BEGIN PRIVATE KEY-----\ndecoy\n"


def plant_decoys(tmp: Path) -> None:
    for place in (tmp, tmp / "tls", tmp / "static", tmp / "static" / "tls"):
        place.mkdir(parents=True, exist_ok=True)
        (place / "server.key").write_text(DECOY, encoding="utf-8")
        (place / "root.key").write_text(DECOY, encoding="utf-8")


@pytest_asyncio.fixture
async def app(tmp_path: Path) -> AsyncIterator[App]:
    config = app_config(tmp_path)
    plant_decoys(tmp_path)
    running = App(config, SystemClock(None))
    await running.start()
    try:
        yield running
    finally:
        await running.stop()


def trusting() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=TLS / "root.crt")


@pytest.mark.case("T-WEB-01")
@pytest.mark.req("APP-816")
@pytest.mark.asyncio
async def test_page_over_https_with_the_root_trusted(app: App) -> None:
    https, _ = app.ports
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://127.0.0.1:{https}/",
                               ssl=trusting()) as response:
            assert response.status == 200
            assert await response.text() == INDEX
            assert response.headers["Cache-Control"] == "no-cache"
        async with session.get(f"https://localhost:{https}/assets/"
                               "app-1234.js", ssl=trusting()) as response:
            assert response.status == 200
            assert response.headers["Cache-Control"] == ASSETS_CACHE


@pytest.mark.case("T-WEB-01")
@pytest.mark.req("APP-816")
@pytest.mark.asyncio
async def test_handshake_refused_without_the_root(app: App) -> None:
    https, _ = app.ports
    async with aiohttp.ClientSession() as session:
        with pytest.raises(aiohttp.ClientConnectorCertificateError):
            await session.get(f"https://127.0.0.1:{https}/",
                              ssl=ssl.create_default_context())


@pytest.mark.case("T-WEB-02")
@pytest.mark.req("APP-816")
def test_redirect_target_keeps_path_and_query() -> None:
    assert redirect_target("wow.local", 443, "/x?y=1") == (
        "https://wow.local/x?y=1")
    assert redirect_target("wow.local", 8443, "/x?y=1") == (
        "https://wow.local:8443/x?y=1")


@pytest.mark.case("T-WEB-02")
@pytest.mark.req("APP-816")
@pytest.mark.asyncio
async def test_http_redirects_and_serves_only_the_root(app: App) -> None:
    https, http = app.ports
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://127.0.0.1:{http}/x?y=1",
                               allow_redirects=False) as response:
            assert response.status == 301
            assert response.headers["Location"] == redirect_target(
                "wow.local", https, "/x?y=1")
        async with session.get(f"http://127.0.0.1:{http}/setup/root.crt"
                               ) as response:
            assert response.status == 200
            assert await response.read() == (TLS / "root.crt").read_bytes()


@pytest.mark.case("T-WEB-02")
@pytest.mark.req("APP-816")
@pytest.mark.asyncio
@pytest.mark.parametrize("path", KEY_PATHS)
async def test_no_path_reaches_a_key(app: App, path: str) -> None:
    https, http = app.ports
    targets = (URL(f"http://127.0.0.1:{http}{path}", encoded=True),
               URL(f"https://127.0.0.1:{https}/assets/../..{path}",
                   encoded=True),
               URL(f"https://127.0.0.1:{https}/assets/%2e%2e/%2e%2e{path}",
                   encoded=True))
    async with aiohttp.ClientSession() as session:
        for url in targets:
            async with session.get(url, ssl=trusting(),
                                   allow_redirects=False) as response:
                body = await response.read()
                assert b"PRIVATE KEY" not in body
                assert response.status in (301, 403, 404)
