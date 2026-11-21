"""The riders of wow.toml and their view (supporting S-RDR-01, S-RDR-02)."""

import pytest

from wow.core.devices import LinkState
from wow.core.riders import Rider, RidersError, riders_of
from wow.core.view import home_screen, riders_view, view_state

FERRAN = Rider("ferran", "Ferran")
ANNA = Rider("anna", "Anna")


@pytest.mark.case("S-RDR-01")
def test_the_table_gives_the_riders_in_its_order() -> None:
    assert riders_of({"ferran": "Ferran", "anna": " Anna "}) == (FERRAN,
                                                                 ANNA)
    assert riders_of({"a-1": "A"}) == (Rider("a-1", "A"),)


@pytest.mark.case("S-RDR-01")
@pytest.mark.parametrize("table, problem", [
    ("ferran", "not a table"),
    ({}, "no rider"),
    ({"Ferran": "Ferran"}, "rider ID 'Ferran'"),
    ({"-x": "X"}, "rider ID '-x'"),
    ({"a" * 33: "A"}, "rider ID"),
    ({"ferran": 7}, "rider ferran: a name"),
    ({"ferran": "  "}, "rider ferran: a name"),
    ({"ferran": "F" * 25}, "rider ferran: a name"),
    ({"ferran": "Ferran", "f2": "ferran"}, "name 'ferran' twice"),
])
def test_a_table_that_cant_be_used_says_why(table: object,
                                            problem: str) -> None:
    with pytest.raises(RidersError, match=problem):
        riders_of(table)


@pytest.mark.case("S-RDR-02")
def test_the_view_names_the_riders_only_when_there_are_some() -> None:
    screen = home_screen([])
    alone = view_state(screen, LinkState.CONNECTED, LinkState.CONNECTED,
                       80, [], None)
    assert "riders" not in alone
    shared = view_state(screen, LinkState.CONNECTED, LinkState.CONNECTED,
                        80, [], None, riders_view((FERRAN, ANNA), ANNA, 205))
    assert shared["riders"] == {
        "active": "anna", "ftp": 205,
        "list": [{"id": "ferran", "name": "Ferran"},
                 {"id": "anna", "name": "Anna"}]}
