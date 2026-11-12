from dataclasses import dataclass

import pytest

from wow.core.devices import Erg, HrSample, Range, Resistance
from wow.core.devices import TrainerCapabilities
from wow.core.ftms_session import Indication, LinkUp, SetCommand
from wow.core.jsonform import Registry, to_json, type_name


@dataclass(frozen=True)
class Sample:
    value: float
    data: bytes | None
    tags: tuple[str, ...]


FORMS = Registry(LinkUp, TrainerCapabilities, Range, SetCommand, Erg,
                 Resistance, Indication, HrSample, Sample)


@pytest.mark.case("S-INF-01")
@pytest.mark.parametrize("value", [
    LinkUp(TrainerCapabilities(Range(50, 600, 1), None, True, False)),
    SetCommand(Erg(330)),
    SetCommand(Resistance(40)),
    Indication(bytes.fromhex("800501")),
    HrSample(12.5, None, (0.9, 1.0)),
    Sample(3.0, b"\x01\xff", ("a", "b")),
    Sample(3.0, None, ()),
])
def test_round_trip(value: object) -> None:
    assert FORMS.load(to_json(value)) == value


@pytest.mark.case("S-INF-01")
def test_forms_are_plain_json() -> None:
    assert to_json(SetCommand(Erg(330))) == {
        "type": "set_command", "command": {"type": "erg", "power": 330}}
    assert to_json(Indication(b"\x80\x05\x01")) == {
        "type": "indication", "data": "800501"}
    assert FORMS.load({"type": "sample", "value": 3, "data": None,
                       "tags": []}) == Sample(3.0, None, ())
    assert type_name(TrainerCapabilities) == "trainer_capabilities"


@pytest.mark.case("S-INF-01")
@pytest.mark.parametrize("form", [[1], {"no": "type"}, {"type": "unknown"}])
def test_bad_forms_are_refused(form: object) -> None:
    with pytest.raises(ValueError):
        FORMS.load(form)
