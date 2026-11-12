"""Serve the display over HTTPS and set-up over HTTP.

The HTTPS site with the built display and the WebSocket, and the plain
HTTP site that redirects and serves the root certificate for set-up
(ICD IF-07; 3A, web/server; APP-410, APP-816).

Slice SL-02: `/`, `/assets/*`, `/ws`, and port 80. The FIT download
follows in SL-08.
"""

import logging
import ssl
from collections.abc import Awaitable, Callable
from pathlib import Path

from aiohttp import web
from typing import Final

logger = logging.getLogger(__name__)

ASSETS_CACHE: Final[str] = "public, max-age=31536000, immutable"
ROOT_CERT_PATH: Final[str] = "/setup/root.crt"

WsHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def tls_context(cert: Path, key: Path) -> ssl.SSLContext:
    """Return the TLS context for a certificate and key."""
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    return context


def redirect_target(host: str, https_port: int, path_qs: str) -> str:
    """Return the HTTPS URL an HTTP request is sent to."""
    authority = host if https_port == 443 else f"{host}:{https_port}"
    return f"https://{authority}{path_qs}"


def https_app(static: Path, ws: WsHandler) -> web.Application:
    """Return the HTTPS site: display, assets and WebSocket."""
    index = static / "index.html"

    async def page(_request: web.Request) -> web.StreamResponse:
        if not index.is_file():
            return web.Response(status=503, text="display not built\n")
        return web.FileResponse(index, headers={"Cache-Control": "no-cache"})

    async def cache_assets(request: web.Request,
                           response: web.StreamResponse) -> None:
        if request.path.startswith("/assets/") and response.status == 200:
            response.headers["Cache-Control"] = ASSETS_CACHE

    app = web.Application()
    app.router.add_get("/", page)
    app.router.add_get("/ws", ws)
    if (static / "assets").is_dir():
        app.router.add_static("/assets", static / "assets")
    app.on_response_prepare.append(cache_assets)
    return app


def http_app(host: str, https_port: int, root_cert: Path) -> web.Application:
    """Return the HTTP site: redirect and root certificate."""
    async def root_certificate(_request: web.Request) -> web.StreamResponse:
        return web.FileResponse(root_cert, headers={
            "Content-Type": "application/x-x509-ca-cert"})

    async def redirect(request: web.Request) -> web.StreamResponse:
        raise web.HTTPMovedPermanently(
            redirect_target(host, https_port, request.path_qs))

    app = web.Application()
    app.router.add_get(ROOT_CERT_PATH, root_certificate)
    app.router.add_route("*", "/{tail:.*}", redirect)
    return app


class WebServer:
    """Starts and stops the sites."""

    def __init__(self) -> None:
        self._runners: list[web.AppRunner] = []

    async def start(self, app: web.Application, host: str | None, port: int,
                    context: ssl.SSLContext | None = None) -> int:
        """Serve an app and return the port it listens on."""
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, host, port, ssl_context=context)
        await site.start()
        self._runners.append(runner)
        bound = runner.addresses[0][1] if runner.addresses else port
        logger.info("listening on %s port %d%s", host or "all addresses",
                    bound, " (TLS)" if context else "")
        return int(bound)

    async def stop(self) -> None:
        """Stop all sites."""
        for runner in reversed(self._runners):
            await runner.cleanup()
        self._runners.clear()
