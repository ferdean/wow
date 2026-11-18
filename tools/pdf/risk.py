"""Draw the Phase 2 risk matrix: before and after grids from its table.

Rows are severity (Critical on top), columns likelihood; each cell is
coloured by its score, likelihood level times severity level, as the
approved Phase 2 PDF shows it.
"""

import html
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

SEVERITIES: Final[tuple[str, ...]] = ("Minor", "Moderate", "Major", "Critical")
LIKELIHOODS: Final[tuple[str, ...]] = ("Low", "Low–medium", "Medium", "High")
SHORT_LIKELIHOODS: Final[tuple[str, ...]] = (
    "Low", "Low–med.", "Medium", "High")
RETIRED: Final[str] = "Retired"
BANDS: Final[tuple[tuple[int, int, str, str], ...]] = (
    (1, 3, "#B7DFB0", "1–3"), (4, 6, "#FFE699", "4–6"),
    (8, 9, "#F8B26A", "8–9"), (12, 16, "#E8817C", "12–16"))
COLUMNS: Final[dict[str, str]] = {
    "id": "Risk", "severity": "Severity", "before": "Likelihood before",
    "after": "Likelihood after"}
CSS: Final[str] = """
body { margin: 0; font-family: 'Latin Modern Sans', sans-serif; color: #000; }
#fig { display: inline-flex; flex-direction: column; gap: 14px; padding: 4px; }
.grids { display: flex; gap: 40px; }
.grid { display: grid; grid-template-columns: 26px 70px repeat(4, 88px);
        grid-auto-rows: 52px; column-gap: 3px; row-gap: 3px; }
.title { grid-column: 3 / span 4; font-weight: bold; font-size: 16px;
         text-align: center; align-self: end; height: 28px; }
.axis-y { grid-row: 2 / span 4; writing-mode: vertical-rl;
          transform: rotate(180deg); text-align: center; font-size: 13px; }
.row { font-size: 13px; text-align: right; align-self: center;
       padding-right: 6px; }
.cell { display: flex; align-items: center; justify-content: center;
        text-align: center; font-size: 12.5px; padding: 3px; }
.col { font-size: 13px; text-align: center; align-self: start; }
.axis-x { grid-column: 3 / span 4; text-align: center; font-size: 13px; }
.retired { grid-column: 3 / span 4; text-align: center; font-size: 12.5px; }
.legend { display: flex; gap: 14px; align-items: center; font-size: 13px;
          padding-left: 70px; }
.swatch { display: inline-block; width: 22px; height: 12px;
          margin-right: 6px; vertical-align: middle; }
"""


@dataclass(frozen=True)
class Risk:
    """One rated risk."""

    id: str
    severity: int
    before: int
    after: int | None


def risks(rows: Sequence[Sequence[str]]) -> list[Risk]:
    """Read the risks from the table's rows (header first)."""
    header = list(rows[0])
    index = {key: next(i for i, name in enumerate(header)
                       if name.startswith(title))
             for key, title in COLUMNS.items()}
    found: list[Risk] = []
    for row in rows[1:]:
        after = row[index["after"]]
        found.append(Risk(row[index["id"]],
                          SEVERITIES.index(row[index["severity"]]) + 1,
                          LIKELIHOODS.index(row[index["before"]]) + 1,
                          None if after == RETIRED
                          else LIKELIHOODS.index(after) + 1))
    return found


def colour(score: int) -> str:
    """Return the cell colour of a score."""
    return next(fill for low, high, fill, _ in BANDS if low <= score <= high)


def page(found: Sequence[Risk], phase: str) -> str:
    """Return the HTML page of both grids, with the legend."""
    before = _cells((r.severity, r.before, r.id) for r in found)
    after = _cells((r.severity, r.after, r.id) for r in found
                   if r.after is not None)
    retired = [r.id for r in found if r.after is None]
    legend = "".join(
        f'<span><span class="swatch" style="background:{fill}"></span>'
        f"{label}</span>" for _, _, fill, label in BANDS)
    return (f"<html><head><style>{CSS}</style></head><body><div id='fig'>"
            f"<div class='grids'>{_grid(before, f'Before {phase}')}"
            f"{_grid(after, f'After {phase}', retired)}</div>"
            "<div class='legend'>Score = likelihood × severity:"
            f"{legend}</div></div></body></html>")


def _cells(placed: Iterable[tuple[int, int, str]]) -> dict[
        tuple[int, int], list[str]]:
    cells: dict[tuple[int, int], list[str]] = {}
    for severity, likelihood, risk in placed:
        cells.setdefault((severity, likelihood), []).append(risk)
    return cells


def _grid(cells: dict[tuple[int, int], list[str]], title: str,
          retired: Sequence[str] = ()) -> str:
    parts = [f"<div class='title'>{html.escape(title)}</div>",
             "<div class='axis-y'>Severity →</div>"]
    for severity in range(len(SEVERITIES), 0, -1):
        parts.append(f"<div class='row'>{SEVERITIES[severity - 1]}</div>")
        for likelihood in range(1, len(LIKELIHOODS) + 1):
            ids = " ".join(cells.get((severity, likelihood), []))
            parts.append(f"<div class='cell' style='background:"
                         f"{colour(severity * likelihood)}'>{ids}</div>")
    parts.append("<div></div><div></div>")
    parts += [f"<div class='col'>{name}</div>" for name in SHORT_LIKELIHOODS]
    parts.append("<div></div><div></div><div class='axis-x'>"
                 "Likelihood →</div>")
    if retired:
        parts.append("<div></div><div></div><div class='retired'>Retired: "
                     f"{', '.join(retired)}</div>")
    return f"<div class='grid'>{''.join(parts)}</div>"
