from fractions import Fraction

import pytest

from wow.core.devices import Range
from wow.core.numbers import round_half_up, zone_of
from wow.core.target_policy import erg_target

D100 = Range(50, 600, 1)


@pytest.mark.case("T-TGT-01")
@pytest.mark.req("APP-302", "APP-313")
@pytest.mark.parametrize(
    "watts, intensity, step, expected",
    [
        (Fraction(88) * 250 / 100, 100, 1, 220),
        (Fraction(88) * 250 / 100, 105, 1, 231),
        (Fraction(88) * 250 / 100, 50, 1, 110),
        (Fraction(88) * 250 / 100, 150, 1, 330),
        (200, 105, 1, 210),
        (Fraction(65) * 250 / 100, 100, 1, 163),
        (Fraction(88) * 250 / 100, 105, 5, 230),
        (232.5, 100, 5, 235),
        (232.4, 100, 5, 230),
    ],
)
def test_targets_follow_ftp_intensity_and_round_half_up(
    watts: Fraction | float,
    intensity: int,
    step: int,
    expected: int,
) -> None:
    target = erg_target(watts, intensity, Range(0, 2000, step))
    assert target.power == expected
    assert not target.limited


@pytest.mark.case("T-TGT-01")
@pytest.mark.req("APP-302", "APP-313")
def test_round_half_up_is_not_bankers_rounding() -> None:
    assert round(162.5) == 162
    assert round_half_up(162.5) == 163
    assert round_half_up(Fraction(325, 2)) == 163
    assert round_half_up(0.1 + 0.2, 1) == 0


@pytest.mark.case("T-TGT-02")
@pytest.mark.req("APP-303")
@pytest.mark.parametrize("requested, sent", [(40, 50), (650, 600)])
def test_targets_outside_the_range_send_the_nearest_limit(
    requested: int,
    sent: int,
) -> None:
    target = erg_target(requested, 100, D100)
    assert (target.power, target.requested_power) == (sent, requested)
    assert target.limited


@pytest.mark.case("S-WKO-01")
def test_zones_use_upper_bounds_inclusive() -> None:
    assert [zone_of(p, 250) for p in (137, 138, 187, 188, 300, 301)] == [
        1,
        2,
        2,
        3,
        5,
        6,
    ]
