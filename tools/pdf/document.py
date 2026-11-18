"""Prepare a phase document's Markdown for pandoc.

Pure functions, no I/O: the revision line's and the footer's data from the
heading and the status line, the Mermaid blocks and the risk-matrix marker
to swap for figures, column widths for tables that don't set their own,
and the red P marks of the requirement tables.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

STATUS_PREFIX: Final[str] = "**Status:**"
HEADING: Final[re.Pattern[str]] = re.compile(r"^# (.+)$")
REVISION: Final[re.Pattern[str]] = re.compile(
    r"revision (\d+)(?:, (\d{1,2} [A-Z][a-z]{2} \d{4}))?")
DATE: Final[re.Pattern[str]] = re.compile(
    r"\b(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})\b")
MONTHS: Final[dict[str, str]] = {
    "Jan": "January", "Feb": "February", "Mar": "March", "Apr": "April",
    "May": "May", "Jun": "June", "Jul": "July", "Aug": "August",
    "Sep": "September", "Oct": "October", "Nov": "November",
    "Dec": "December"}
CHANGE_LOG: Final[re.Pattern[str]] = re.compile(
    r"^#{2,3} (\d+(\.\d+)* )?Change log$")
LOG_ROW: Final[re.Pattern[str]] = re.compile(r"^\| (\d+) \|")
MERMAID: Final[re.Pattern[str]] = re.compile(
    r"^```mermaid\n(.*?)^```$", re.S | re.M)
RISK_MARKER: Final[re.Pattern[str]] = re.compile(
    r"^<!-- risk-matrix.*-->$", re.M)
SEPARATOR: Final[re.Pattern[str]] = re.compile(r"^\|[-|: ]+\|$")
CELL_SPLIT: Final[re.Pattern[str]] = re.compile(r"(?<!\\)\|")
P_MARK: Final[re.Pattern[str]] = re.compile(r"\bP[1-9]\b")
RED_BOLD: Final[str] = r"\textcolor{{wowred}}{{\textbf{{{}}}}}"
REQUIREMENT_ROW: Final[str] = "| APP-"
FENCE: Final[str] = "```"
SHORT_COLUMN: Final[int] = 14
HEADER_PADDING: Final[int] = 3
MIN_COLUMN: Final[int] = 16
PANDOC_COLUMNS: Final[int] = 72
CHARACTERS_PER_LINE: Final[int] = 140
TEXT_WIDTH_PX: Final[float] = 655.0
NATURAL_SCALE: Final[float] = 0.8
MAX_HEIGHT_MM: Final[float] = 215.0
MM_PER_PX: Final[float] = 0.2646
PT_PER_PX: Final[float] = 0.6
LATEX_SPECIALS: Final[str] = "&%$#_{}"


class State(StrEnum):
    """Approval state shown in the footer."""

    APPROVED = "approved"
    DRAFT = "draft"


@dataclass(frozen=True)
class Meta:
    """What the title block and the footer show."""

    title: str
    revision: int
    date: str
    state: State
    status: str

    @property
    def footer_title(self) -> str:
        """Return the title without its dash, as the footer shows it."""
        return self.title.replace(" — ", " ")


@dataclass(frozen=True)
class Figure:
    """A rendered figure: a file in the work directory and its size in px."""

    name: str
    width: float
    height: float


def read_meta(text: str) -> Meta:
    """Read the title, revision, date and state of a phase document.

    The revision is the first "revision N" of the status line; the date
    is the one written right after it, else the status line's first date.
    """
    lines = text.split("\n")
    heading = HEADING.match(lines[0])
    if heading is None or not lines[2].startswith(STATUS_PREFIX):
        raise ValueError("expected '# <title>', a blank line, '**Status:**'")
    status = lines[2].removeprefix(STATUS_PREFIX).strip()
    found = REVISION.search(status)
    if found is None:
        raise ValueError("the status line names no revision")
    date = found.group(2) or _first_date(status)
    return Meta(heading.group(1).strip(), int(found.group(1)),
                _long_date(date), _state(status), status)


def change_log_revision(text: str) -> int | None:
    """Return the highest revision in the change log, if there is one."""
    revisions: list[int] = []
    inside = False
    for line in text.split("\n"):
        if line.startswith("#"):
            inside = bool(CHANGE_LOG.match(line))
            continue
        row = LOG_ROW.match(line)
        if inside and row:
            revisions.append(int(row.group(1)))
    return max(revisions) if revisions else None


def mermaid_sources(body: str) -> list[str]:
    """Return the source of every Mermaid block, in order."""
    return MERMAID.findall(body)


def replace_mermaid(body: str, blocks: Sequence[str]) -> str:
    """Swap each Mermaid block, in order, for the given block."""
    queue = iter(blocks)
    return MERMAID.sub(lambda _: next(queue), body)


def replace_risk_marker(body: str, block: str) -> str:
    """Swap the risk-matrix marker for the given block."""
    return RISK_MARKER.sub(lambda _: block, body, count=1)


def has_risk_marker(body: str) -> bool:
    """Tell whether the document asks for a risk matrix."""
    return RISK_MARKER.search(body) is not None


def table_after_marker(body: str) -> list[list[str]]:
    """Return the cells of the first table after the risk-matrix marker."""
    marker = RISK_MARKER.search(body)
    if marker is None:
        return []
    rows: list[list[str]] = []
    for line in body[marker.end():].lstrip("\n").split("\n"):
        if not line.startswith("|"):
            break
        if not SEPARATOR.match(line.strip()):
            rows.append(split_cells(line))
    return rows


def figure_latex(figure: Figure) -> str:
    """Return a raw LaTeX block that places a figure under its heading.

    Diagrams show at 80 % of their natural size, shrink to the text width,
    and never grow taller than MAX_HEIGHT_MM.
    """
    scale = min(1.0, TEXT_WIDTH_PX / (figure.width * NATURAL_SCALE))
    height_mm = figure.height * scale * NATURAL_SCALE * MM_PER_PX
    if height_mm > MAX_HEIGHT_MM:
        size = f"height={MAX_HEIGHT_MM:.0f}mm"
    elif scale < 1.0:
        size = r"width=\linewidth"
    else:
        size = f"width={figure.width * PT_PER_PX:.0f}pt"
    return ("```{=latex}\n\\begin{figure}[H]\\centering\n"
            f"\\includegraphics[{size},keepaspectratio]{{{figure.name}}}\n"
            "\\end{figure}\n```")


def prepare(body: str, new_page_before: Sequence[str] = ()) -> str:
    """Return the document as pandoc gets it.

    Tables without widths of their own get them from their content, P
    marks in requirement rows turn red, and the named headings start on a
    new page.
    """
    lines = retable(body.split("\n"))
    out: list[str] = []
    in_code = False
    for line in lines:
        if line.startswith(FENCE):
            in_code = not in_code
        if not in_code:
            line = _mark(line)
            if line.startswith("## ") and line[3:] in new_page_before:
                out += ["\\newpage", ""]
        out.append(line)
    return "\n".join(out)


def retable(lines: Sequence[str]) -> list[str]:
    """Give column widths to the tables outside code blocks that lack them.

    A separator line longer than pandoc's 72 columns sets the widths
    (pandoc reads them from its dashes), as the Phase 0 record's tables
    do; a shorter one gets widths from the table's content.
    """
    out: list[str] = []
    block: list[str] = []
    in_code = False
    for line in [*lines, ""]:
        if line.startswith(FENCE):
            in_code = not in_code
        if line.startswith("|") and not in_code:
            block.append(line)
            continue
        if block:
            own = len(block) > 1 and len(block[1]) > PANDOC_COLUMNS
            if len(block) <= 2:
                out += block
            else:
                out += widen(block) if own else proportion(block)
            block = []
        out.append(line)
    return out[:-1]


def widen(table: Sequence[str]) -> list[str]:
    """Widen the narrow columns of an own-width table.

    pandoc never breaks a word, so a header word longer than its column
    runs into the next one; and a column of a few dashes with long cells
    turns into a tower of short lines. Each column gets at least its
    header's longest word, and at least MIN_COLUMN or its longest cell.
    """
    header = split_cells(table[0])
    dashes = split_cells(table[1])
    rows = [split_cells(line) for line in table[2:]]
    if not SEPARATOR.match(table[1].strip()) or any(
            len(row) != len(dashes) for row in (header, *rows)):
        return list(table)
    cells = []
    for column, (title, dash) in enumerate(zip(header, dashes)):
        word = max((len(word) for word in title.split()), default=0)
        cell = max((len(row[column]) for row in rows), default=0)
        width = max(len(dash), word + HEADER_PADDING,
                    min(cell, MIN_COLUMN))
        cells.append(dash[0] + "-" * (width - 2) + dash[-1])
    return [table[0], "|" + "|".join(cells) + "|", *table[2:]]


def proportion(table: Sequence[str]) -> list[str]:
    """Rewrite a table's separator so pandoc sizes its columns by content.

    A short column (its longest cell at most SHORT_COLUMN characters) gets
    the share that cell needs at scriptsize, about CHARACTERS_PER_LINE per
    text width plus 4 for padding; the long columns share the rest by
    their mean cell length.
    """
    rows = [split_cells(line) for line in table
            if not SEPARATOR.match(line.strip())]
    count = len(rows[0])
    if len(table) < 2 or not SEPARATOR.match(table[1].strip()) or any(
            len(row) != count for row in rows):
        return list(table)
    fixed: dict[int, float] = {}
    weights: dict[int, float] = {}
    for column in range(count):
        lengths = [len(row[column]) for row in rows[1:]] or [
            len(rows[0][column])]
        header = len(rows[0][column])
        longest = max([*lengths, header])
        if longest <= SHORT_COLUMN:
            fixed[column] = (longest + 4) / CHARACTERS_PER_LINE
        else:
            mean = sum(lengths) / len(lengths)
            weights[column] = max(header, min(mean + 4, 70))
    rest = max(1 - sum(fixed.values()), 0.2)
    total = sum(weights.values()) or 1.0
    shares = [fixed.get(column, rest * weights.get(column, 0.0) / total)
              for column in range(count)]
    separator = "|" + "|".join("-" * max(3, round(200 * share))
                               for share in shares) + "|"
    return [table[0], separator, *table[2:]]


def split_cells(line: str) -> list[str]:
    """Return the cells of a table row."""
    return [cell.strip() for cell in CELL_SPLIT.split(line.strip())[1:-1]]


def latex_escape(text: str) -> str:
    """Escape Markdown text for the title block, keeping bold and code."""
    text = text.replace("\\", r"\textbackslash{}")
    for char in LATEX_SPECIALS:
        text = text.replace(char, "\\" + char)
    text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"`(.+?)`", r"\\texttt{\1}", text)
    return text.replace("–", "--").replace("—", "---")


def _first_date(status: str) -> str:
    found = DATE.search(status)
    if found is None:
        raise ValueError("the status line has no date")
    return found.group(0)


def _long_date(date: str) -> str:
    day, month, year = date.split()
    return f"{day} {MONTHS[month]} {year}"


def _state(status: str) -> State:
    return State.DRAFT if State.DRAFT in status.lower() else State.APPROVED


def _mark(line: str) -> str:
    red: Callable[[re.Match[str]], str] = (
        lambda found: RED_BOLD.format(found.group(0)))
    if not line.startswith(REQUIREMENT_ROW):
        return line
    cells = line.split(" | ")
    cells[-1] = P_MARK.sub(red, cells[-1])
    return " | ".join(cells)
