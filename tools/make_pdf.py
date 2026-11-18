"""Typeset the phase documents as PDFs in the approved format.

Each docs/phase*.md becomes build/pdf/<name>.pdf in the format of the
approved Phase 0 to 2 PDFs, Mermaid diagrams drawn as vector figures in
the same font. Laptop only: nothing here is installed on the Pi.

Set-up, once:
    sudo apt install pandoc texlive-xetex texlive-latex-extra fonts-lmodern
    uv sync --group docs
    uv run --group docs playwright install chromium
    npm ci --prefix tools/pdf

Usage:
    uv run --group docs python -m tools.make_pdf [document ...]
        [--out build/pdf] [--chrome /usr/bin/google-chrome]
    uv run --group docs python -m tools.make_pdf --screens
        (3C's screenshots, from the built display's gallery, into
        docs/img/phase3-display; build the display first)
"""

import argparse
import glob
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from tools.pdf import document, risk
from tools.pdf.browser import Chromium, load_screens, static_site
from tools.pdf.typeset import typeset

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
DOCS: Final[Path] = ROOT / "docs"
IMAGES: Final[Path] = DOCS / "img"
STATIC: Final[Path] = ROOT / "src" / "wow" / "web" / "static"
SCREENS: Final[Path] = ROOT / "tools" / "pdf" / "screens.json"
SCREEN_OUT: Final[Path] = IMAGES / "phase3-display"
PATTERN: Final[str] = "phase*.md"
PROGRAMS: Final[tuple[str, ...]] = ("pandoc", "xelatex")
NEW_PAGE_BEFORE: Final[dict[str, tuple[str, ...]]] = {
    "phase2-spikes.md": ("Open points",)}
RISK_PHASE: Final[str] = "Phase 2"


def build(path: Path, chromium: Chromium, out: Path) -> Path:
    """Typeset one phase document; return the PDF's path."""
    text = path.read_text(encoding="utf-8")
    meta = document.read_meta(text)
    work = out / "work" / path.stem
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    body = text
    figures = chromium.mermaid(document.mermaid_sources(body), work)
    body = document.replace_mermaid(
        body, [document.figure_latex(figure) for figure in figures])
    if document.has_risk_marker(body):
        rows = document.table_after_marker(body)
        grid = chromium.html_figure(
            risk.page(risk.risks(rows), RISK_PHASE), work / "risk-matrix.pdf")
        body = document.replace_risk_marker(body, document.figure_latex(grid))
    if IMAGES.exists():
        shutil.copytree(IMAGES, work / "img")
    body = document.prepare(body, NEW_PAGE_BEFORE.get(path.name, ()))
    result = typeset(meta, body, work, out / f"{path.stem}.pdf")
    for char in result.missing:
        print(f"warning: {path.name}: no glyph for {char}", file=sys.stderr)
    print(f"{result.pdf}: revision {meta.revision}, {len(figures)} diagrams")
    return result.pdf


def screens(chromium: Chromium) -> list[Path]:
    """Photograph 3C's figures from the built display's gallery."""
    css = sorted(glob.glob(str(STATIC / "assets" / "index-*.css")))
    if not (STATIC / "index.html").exists() or not css:
        raise FileNotFoundError(
            "build the display first: cd display && npm ci && npm run build")
    spec = json.loads(SCREENS.read_text(encoding="utf-8"))
    figures = load_screens(spec, "assets/" + Path(css[0]).name)
    SCREEN_OUT.mkdir(parents=True, exist_ok=True)
    with static_site(STATIC) as site:
        return chromium.screens(figures, site, spec["viewport"],
                                float(spec["scale"]), SCREEN_OUT)


def main(argv: Sequence[str] | None = None) -> int:
    """Typeset the documents, or photograph the screens; 0 on success."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("documents", nargs="*", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "build" / "pdf")
    parser.add_argument("--chrome", type=Path, default=None,
                        help="a Chrome or Chromium to use instead of "
                        "Playwright's own")
    parser.add_argument("--screens", action="store_true",
                        help="photograph 3C's figures instead")
    args = parser.parse_args(argv)
    missing = [name for name in PROGRAMS if shutil.which(name) is None]
    if missing and not args.screens:
        print(f"not on the PATH: {', '.join(missing)}", file=sys.stderr)
        return 1
    paths = args.documents or sorted(DOCS.glob(PATTERN))
    with Chromium(args.chrome) as chromium:
        if args.screens:
            for path in screens(chromium):
                print(path)
            return 0
        args.out.mkdir(parents=True, exist_ok=True)
        for path in paths:
            try:
                build(path.resolve(), chromium, args.out)
            except (RuntimeError, ValueError) as error:
                print(f"{path.name}: {error}", file=sys.stderr)
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
