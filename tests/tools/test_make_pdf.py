"""The pure parts of tools/make_pdf.py, and the phase documents it reads.

Typesetting needs pandoc, XeLaTeX and Chromium, which the gate doesn't
install; these tests cover what decides the output.
"""

from pathlib import Path

import pytest

from tools.pdf.document import (
    MIN_COLUMN, Figure, State, change_log_revision, figure_latex,
    mermaid_sources, prepare, read_meta, replace_mermaid,
    replace_risk_marker, split_cells, table_after_marker)
from tools.pdf.risk import Risk, colour, risks
from tools.pdf.typeset import date_line, footer

ROOT = Path(__file__).resolve().parents[2]
PHASE_DOCUMENTS = sorted((ROOT / "docs").glob("phase*.md"))
DOCUMENT = """# Phase 9 — Example

**Status:** approved; revision 3, 18 Nov 2026. Draws on revision 2.

## Change log

| Rev. | Date | Change |
|------|------|--------|
| 1 | 1 Nov 2026 | First. |
| 3 | 18 Nov 2026 | Third. |
"""


@pytest.mark.case("S-DOC-01")
@pytest.mark.parametrize("path", PHASE_DOCUMENTS, ids=lambda p: p.stem)
def test_each_phase_document_names_its_latest_revision(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    meta = read_meta(text)
    assert meta.title.startswith("Phase ")
    assert change_log_revision(text) in (None, meta.revision)


@pytest.mark.case("S-DOC-01")
def test_the_whole_set_of_phase_documents_is_in_docs() -> None:
    assert [path.stem for path in PHASE_DOCUMENTS] == [
        "phase0-discovery", "phase1-requirements", "phase2-spikes",
        "phase3-arch", "phase3-display", "phase3-icd", "phase4-test-plan",
        "phase5-implementation"]


@pytest.mark.case("S-DOC-01")
def test_meta_comes_from_the_status_line() -> None:
    meta = read_meta(DOCUMENT)
    assert (meta.title, meta.revision, meta.date, meta.state) == (
        "Phase 9 — Example", 3, "18 November 2026", State.APPROVED)
    assert footer(meta) == (
        "WitchesOnWheels · Phase 9 Example · revision 3 · approved")
    assert date_line(meta) == "Revision 3 · 18 November 2026"
    assert change_log_revision(DOCUMENT) == 3


@pytest.mark.case("S-DOC-01")
def test_a_draft_and_a_date_before_the_revision() -> None:
    meta = read_meta("# Phase 9 — X\n\n**Status:** draft of 4 Nov 2026 "
                     "(revision 1).\n")
    assert (meta.revision, meta.date, meta.state) == (
        1, "4 November 2026", State.DRAFT)


@pytest.mark.case("S-DOC-01")
def test_a_document_without_a_status_line_is_refused() -> None:
    with pytest.raises(ValueError):
        read_meta("# Phase 9\n\nSome text.\n")


@pytest.mark.case("S-DOC-01")
def test_mermaid_blocks_are_found_and_swapped_in_order() -> None:
    body = ("a\n```mermaid\nflowchart LR\n  A --> B\n```\nb\n"
            "```mermaid\nstateDiagram-v2\n```\nc")
    assert mermaid_sources(body) == ["flowchart LR\n  A --> B\n",
                                     "stateDiagram-v2\n"]
    assert replace_mermaid(body, ["ONE", "TWO"]) == "a\nONE\nb\nTWO\nc"


@pytest.mark.case("S-DOC-01")
def test_a_short_table_gets_widths_from_its_content() -> None:
    table = prepare("| ID | Text |\n|---|---|\n| A-1 | " + "word " * 30
                    + "|\n")
    separator = table.split("\n")[1]
    short, long = (len(cell) for cell in split_cells(separator))
    assert long > short > 3


@pytest.mark.case("S-DOC-01")
def test_an_own_width_table_keeps_its_widths_but_no_narrow_column() -> None:
    separator = "|" + "-" * 70 + "|---|" + "-" * 10 + "|"
    table = prepare("| Text | Likelihood | N |\n" + separator + "\n"
                    "| a | Low: power target declared | 1 |\n")
    text, likely, number = split_cells(table.split("\n")[1])
    assert len(text) == 70
    assert len(likely) == max(len("Likelihood") + 3, MIN_COLUMN)
    assert len(number) == 10


@pytest.mark.case("S-DOC-01")
def test_p_marks_turn_red_only_in_the_last_cell_of_requirement_rows() -> None:
    body = prepare("| APP-101 | P5 text | UC-01; P5 |\n| A-1 | P5 |\n"
                   "```\n| APP-102 | x | P5 |\n```\n## Open points\n",
                   new_page_before=("Open points",))
    lines = body.split("\n")
    assert lines[0] == ("| APP-101 | P5 text | UC-01; "
                        r"\textcolor{wowred}{\textbf{P5}} |")
    assert lines[1] == "| A-1 | P5 |"
    assert lines[3] == "| APP-102 | x | P5 |"
    assert lines[5:7] == ["\\newpage", ""]


@pytest.mark.case("S-DOC-01")
@pytest.mark.parametrize("width, height, size", [
    (300.0, 200.0, "width=180pt"),
    (2000.0, 600.0, r"width=\linewidth"),
    (800.0, 2000.0, "height=215mm"),
])
def test_figures_keep_their_size_within_the_page(
        width: float, height: float, size: str) -> None:
    assert f"[{size},keepaspectratio]{{d.pdf}}" in figure_latex(
        Figure("d.pdf", width, height))


@pytest.mark.case("S-DOC-01")
def test_the_risk_matrix_reads_phase_2s_table() -> None:
    text = (ROOT / "docs" / "phase2-spikes.md").read_text(encoding="utf-8")
    found = risks(table_after_marker(text))
    assert len(found) == 14
    assert found[0] == Risk("R-01", 4, 1, None)
    assert found[6] == Risk("R-07", 3, 3, 2)
    assert "<!--" not in replace_risk_marker(text, "MATRIX")


@pytest.mark.case("S-DOC-01")
@pytest.mark.parametrize("score, fill", [
    (1, "#B7DFB0"), (3, "#B7DFB0"), (4, "#FFE699"), (6, "#FFE699"),
    (8, "#F8B26A"), (9, "#F8B26A"), (12, "#E8817C"), (16, "#E8817C"),
])
def test_scores_take_their_band_colour(score: int, fill: str) -> None:
    assert colour(score) == fill
