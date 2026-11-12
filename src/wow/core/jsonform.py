"""Convert core values to and from JSON forms.

JSON forms of core events, actions and values, so test data stays
language-neutral (APP-821, D-17).

A dataclass becomes an object with a "type" field (the class name in
snake case) and one field per attribute; bytes become hex text; tuples
become lists.
"""

import dataclasses
import re
import types
from collections.abc import Mapping
from typing import Any, Union, get_args, get_origin, get_type_hints


def type_name(cls: type) -> str:
    """Return the snake case JSON name of a class."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()


def to_json(value: object) -> Any:
    """Return the JSON form of a core value."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        form: dict[str, Any] = {"type": type_name(type(value))}
        for item in dataclasses.fields(value):
            form[item.name] = to_json(getattr(value, item.name))
        return form
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (tuple, list)):
        return [to_json(item) for item in value]
    return value


class Registry:
    """The classes that may appear in JSON forms, by name."""

    def __init__(self, *classes: type) -> None:
        self._classes = {type_name(cls): cls for cls in classes}

    def load(self, form: Any) -> Any:
        """Build the core value a JSON form describes."""
        if not isinstance(form, dict) or "type" not in form:
            raise ValueError(f"not a typed object: {form!r}")
        cls = self._classes.get(form["type"])
        if cls is None:
            raise ValueError(f"unknown type {form['type']!r}")
        hints = get_type_hints(cls)
        values = {
            item.name: self._value(hints[item.name], form[item.name])
            for item in dataclasses.fields(cls)
        }
        return cls(**values)

    def _value(self, hint: Any, raw: Any) -> Any:
        if raw is None:
            return None
        origin = get_origin(hint)
        if origin in (Union, types.UnionType):
            options = [a for a in get_args(hint) if a is not type(None)]
            if bytes in options:
                return bytes.fromhex(raw)
            if len(options) == 1:
                return self._value(options[0], raw)
        if hint is bytes:
            return bytes.fromhex(raw)
        if origin in (dict, Mapping):
            return dict(raw)
        if origin is tuple:
            item_hint = get_args(hint)[0]
            return tuple(self._value(item_hint, item) for item in raw)
        if isinstance(raw, dict):
            return self.load(raw)
        if hint is float and isinstance(raw, int):
            return float(raw)
        return raw
