"""Render figures in Chromium through Playwright.

Mermaid diagrams and HTML figures become vector PDFs at their natural
size; the display's screens are photographed from the gallery of the
built display (`#gallery/<state>`), with numbered pins, and set side by
side into one PNG per figure.
"""

import base64
import functools
import html
import json
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import Any, Final

from playwright.sync_api import (
    Browser, Error, Page, PdfMargins, Playwright, ViewportSize,
    sync_playwright)

from tools.pdf.document import Figure

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
MERMAID_JS: Final[Path] = (Path(__file__).parent / "node_modules" / "mermaid"
                           / "dist" / "mermaid.min.js")
MERMAID_CONFIG: Final[Path] = Path(__file__).with_name("mermaid.json")
DIAGRAM_VIEWPORT: Final[ViewportSize] = {"width": 1600, "height": 1200}
COMPOSITE_VIEWPORT: Final[ViewportSize] = {"width": 1800, "height": 1200}
NO_MARGIN: Final[PdfMargins] = {
    "top": "0", "bottom": "0", "left": "0", "right": "0"}
SETTLE_MS: Final[int] = 700
WAKE_PROMPT: Final[str] = "Tap to keep the screen on"
WAKE_PERMISSION: Final[str] = "screen-wake-lock"
GALLERY: Final[str] = "#gallery/"
DIAGRAM_PAGE: Final[str] = (
    "<html><body style='margin:0'><div id='out'></div></body></html>")
RENDER: Final[str] = """async (src) => {
    const id = 'fig' + Math.random().toString(36).slice(2);
    return (await mermaid.render(id, src)).svg;
}"""
PLACE: Final[str] = """(svg) => {
    const out = document.getElementById('out');
    out.innerHTML = svg;
    const el = out.querySelector('svg');
    const box = el.viewBox.baseVal;
    el.removeAttribute('style');
    el.setAttribute('width', box.width);
    el.setAttribute('height', box.height);
}"""
MEASURE: Final[str] = """(selector) => {
    const r = document.querySelector(selector).getBoundingClientRect();
    return [Math.ceil(r.width), Math.ceil(r.height)];
}"""
SCROLL_END: Final = """
document.querySelectorAll(".scroll").forEach(
    (box) => { box.scrollTop = box.scrollHeight; });
"""
PINS: Final[str] = """(pins) => {
    for (const [number, selector, index] of pins) {
        const target = selector.startsWith('text=')
            ? [...document.querySelectorAll('button, a, div, span')].find(
                (e) => e.innerText.trim() === selector.slice(5))
            : document.querySelectorAll(selector)[index];
        if (!target) { throw new Error('no pin target ' + selector); }
        const r = target.getBoundingClientRect();
        const pin = document.createElement('div');
        pin.textContent = number;
        const left = Math.min(Math.max(r.left - 9, 2), innerWidth - 28);
        const top = Math.min(Math.max(r.top - 9, 2), innerHeight - 28);
        pin.style.cssText = 'position:fixed;z-index:9999;width:24px;'
            + 'height:24px;border-radius:12px;background:#C8102E;'
            + 'color:#fff;font:bold 14px/24px sans-serif;text-align:center;'
            + 'box-shadow:0 0 0 2px #fff;left:' + left + 'px;top:'
            + top + 'px';
        document.body.appendChild(pin);
    }
}"""
COMPOSITE_CSS: Final[str] = """
body { margin: 0; background: #fff; }
#fig { display: inline-flex; gap: 28px; padding: 8px; }
figure { margin: 0; text-align: center; }
img { display: block; border-radius: 18px; }
figcaption { font-family: 'Latin Modern Sans', sans-serif; font-size: 22px;
             color: #000; margin-top: 10px; }
"""


@dataclass(frozen=True)
class Panel:
    """One phone screen of a figure."""

    state: str
    caption: str
    lock: bool = False
    clicks: tuple[str, ...] = ()
    pins: tuple[tuple[int, str, int], ...] = ()
    html: str = ""
    scroll: bool = False


@dataclass(frozen=True)
class ScreenFigure:
    """A figure of phone screens side by side, written as one PNG."""

    name: str
    panels: tuple[Panel, ...] = field(default_factory=tuple)


def load_screens(spec: Mapping[str, Any], css: str) -> list[ScreenFigure]:
    """Read the figure list of `screens.json`.

    A panel with a `page` shows that HTML file of tools/pdf instead of a
    gallery state, with `@CSS@` set to the built display's style sheet.
    """
    def page_of(panel: Mapping[str, Any]) -> str:
        if "page" not in panel:
            return ""
        path = Path(__file__).with_name(str(panel["page"]))
        return path.read_text(encoding="utf-8").replace("@CSS@", css)

    return [ScreenFigure(name, tuple(
        Panel(panel["state"], panel["caption"], panel.get("lock", False),
              tuple(panel.get("clicks", ())),
              tuple((int(n), str(s), int(i)) for n, s, i
                    in panel.get("pins", ())),
              page_of(panel), panel.get("scroll", False))
        for panel in panels)) for name, panels in spec["figures"].items()]


@contextmanager
def static_site(directory: Path) -> Iterator[str]:
    """Serve a directory on a free local port; yield its base URL."""
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

    handler = functools.partial(Quiet, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


class Chromium:
    """A headless Chromium for the figures, open for one run."""

    def __init__(self, executable: Path | None) -> None:
        self._executable = executable
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def __enter__(self) -> "Chromium":
        self._playwright = sync_playwright().start()
        path = None if self._executable is None else str(self._executable)
        self._browser = self._playwright.chromium.launch(executable_path=path)
        return self

    def __exit__(self, kind: type[BaseException] | None,
                 error: BaseException | None,
                 trace: TracebackType | None) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()

    def mermaid(self, sources: Sequence[str], work: Path) -> list[Figure]:
        """Render Mermaid sources as PDF figures in the work directory."""
        if not sources:
            return []
        if not MERMAID_JS.exists():
            raise FileNotFoundError(
                f"{MERMAID_JS} is missing: run `npm ci --prefix tools/pdf`")
        config = json.loads(MERMAID_CONFIG.read_text(encoding="utf-8"))
        page = self._page(DIAGRAM_VIEWPORT)
        page.set_content(DIAGRAM_PAGE)
        page.add_script_tag(path=str(MERMAID_JS))
        page.evaluate("(config) => mermaid.initialize(config)", config)
        figures: list[Figure] = []
        for number, source in enumerate(sources):
            try:
                svg: str = page.evaluate(RENDER, source)
            except Error as error:
                first = error.message.splitlines()[0]
                raise RuntimeError(
                    f"Mermaid diagram {number + 1}: {first}") from error
            page.evaluate(PLACE, svg)
            figures.append(self._pdf(page, "#out svg",
                                     work / f"diagram-{number:02d}.pdf"))
        page.close()
        return figures

    def html_figure(self, content: str, path: Path) -> Figure:
        """Render an HTML page's `#fig` element as a PDF figure."""
        page = self._page(DIAGRAM_VIEWPORT)
        page.set_content(content)
        figure = self._pdf(page, "#fig", path)
        page.close()
        return figure

    def screens(self, figures: Sequence[ScreenFigure], site: str,
                viewport: ViewportSize, scale: float,
                out: Path) -> list[Path]:
        """Photograph each figure's panels and write one PNG per figure."""
        written: list[Path] = []
        for figure in figures:
            shots = [(panel.caption, self._shot(panel, site, viewport))
                     for panel in figure.panels]
            path = out / f"{figure.name}.png"
            path.write_bytes(self._composite(shots, viewport, scale))
            written.append(path)
        return written

    def _page(self, viewport: ViewportSize, scale: float = 1.0,
              lock: bool = False, origin: str = "") -> Page:
        assert self._browser is not None, "use Chromium in a with block"
        context = self._browser.new_context(
            viewport=viewport, device_scale_factor=scale)
        if lock:
            context.grant_permissions([WAKE_PERMISSION], origin=origin)
        page: Page = context.new_page()
        return page

    def _pdf(self, page: Page, selector: str, path: Path) -> Figure:
        page.evaluate("document.fonts.ready")
        width, height = page.evaluate(MEASURE, selector)
        page.pdf(path=str(path), width=f"{width + 2}px",
                 height=f"{height + 2}px", print_background=True,
                 page_ranges="1", margin=NO_MARGIN)
        return Figure(path.name, float(width), float(height))

    def _shot(self, panel: Panel, site: str,
              viewport: ViewportSize) -> bytes:
        page = self._page(viewport, 2.0, panel.lock, site.rstrip("/"))
        if panel.html:
            page.goto(site)
            page.set_content(panel.html.replace("@BASE@", site))
        else:
            page.goto(site + (GALLERY + panel.state if panel.state else ""))
        page.wait_for_timeout(SETTLE_MS)
        prompt = page.get_by_text(WAKE_PROMPT)
        if panel.lock and prompt.count():
            prompt.click()
            page.wait_for_timeout(SETTLE_MS)
        for text in panel.clicks:
            page.get_by_text(text, exact=True).first.click()
            page.wait_for_timeout(SETTLE_MS)
        if panel.scroll:
            page.evaluate(SCROLL_END)
        if panel.pins:
            page.evaluate(PINS, [list(pin) for pin in panel.pins])
        shot: bytes = page.screenshot()
        page.context.close()
        return shot

    def _composite(self, shots: Sequence[tuple[str, bytes]],
                   viewport: ViewportSize, scale: float) -> bytes:
        width, height = viewport["width"], viewport["height"]
        figures = "".join(
            f"<figure><img width='{width}' height='{height}' "
            f"src='data:image/png;base64,"
            f"{base64.b64encode(shot).decode()}'>"
            f"<figcaption>{html.escape(caption)}</figcaption></figure>"
            for caption, shot in shots)
        page = self._page(COMPOSITE_VIEWPORT, scale)
        page.set_content(f"<html><head><style>{COMPOSITE_CSS}</style>"
                         f"</head><body><div id='fig'>{figures}</div>"
                         "</body></html>")
        page.evaluate("document.fonts.ready")
        png: bytes = page.locator("#fig").screenshot()
        page.context.close()
        return png
