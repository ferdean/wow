"""Typeset a prepared phase document with pandoc and XeLaTeX.

The template is the one of the approved Phase 0 PDF: Latin Modern Sans 10,
the title with a red rule under it and the revision line, bold text in
red, footnote-size zebra tables with bold headers, and the footer
"WitchesOnWheels · <document> · revision · state" with "Page x of y".
"""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tools.pdf.document import Meta, latex_escape

HERE: Final[Path] = Path(__file__).parent
HEADER: Final[Path] = HERE / "header.tex"
FILTER: Final[Path] = HERE / "filter.lua"
DOT: Final[str] = " · "
BODY: Final[str] = "body.md"
METADATA: Final[str] = "meta.json"
MISSING: Final[re.Pattern[str]] = re.compile(
    r"Missing character: There is no (.+?) in font")
PANDOC_OPTIONS: Final[tuple[str, ...]] = (
    "-f", "markdown+autolink_bare_uris-smart", "--shift-heading-level-by=-1",
    "--no-highlight", "-V", "documentclass=article",
    "-V", "classoption=table", "-V", "fontsize=10pt",
    "-V", "fontfamily=fontspec",
    "-V", "geometry:a4paper,margin=18mm,bottom=22mm",
    "-V", "colorlinks=true", "-V", "linkcolor=black", "-V", "urlcolor=black",
    "--pdf-engine=xelatex")


@dataclass(frozen=True)
class Result:
    """A typeset PDF and the characters its fonts lacked."""

    pdf: Path
    missing: tuple[str, ...]


def footer(meta: Meta) -> str:
    """Return the footer's left text."""
    return DOT.join(("WitchesOnWheels", latex_escape(meta.footer_title),
                     f"revision {meta.revision}", meta.state.value))


def date_line(meta: Meta) -> str:
    """Return the line under the title."""
    return f"Revision {meta.revision}{DOT}{meta.date}"


def typeset(meta: Meta, body: str, work: Path, pdf: Path) -> Result:
    """Write pandoc's inputs into the work directory and build the PDF."""
    (work / BODY).write_text(body, encoding="utf-8")
    (work / METADATA).write_text(json.dumps({"date": date_line(meta)}),
                                 encoding="utf-8")
    (work / "header.tex").write_text(
        HEADER.read_text(encoding="utf-8").replace("@FOOTER@", footer(meta)),
        encoding="utf-8")
    log = work / "pandoc.log"
    result = subprocess.run(
        ["pandoc", BODY, "-o", str(pdf.resolve()), *PANDOC_OPTIONS,
         "-H", "header.tex", f"--metadata-file={METADATA}",
         f"--lua-filter={FILTER}"], cwd=work, capture_output=True, text=True)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"pandoc failed for {pdf.name}; see {log}")
    missing = tuple(sorted(set(MISSING.findall(result.stderr))))
    return Result(pdf, missing)
