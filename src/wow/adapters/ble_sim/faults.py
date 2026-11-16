"""Script faults into the simulated devices.

Faults scripted on the simulator's clock (ICD 4.3.4; APP-819): each
starts and ends at a set time.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum


class FaultKind(StrEnum):
    """A fault the simulator can play."""

    LINK_LOSS = "link_loss"
    SILENCE = "silence"
    REFUSE_CONTROL = "refuse_control"
    NO_ANSWER = "no_answer"
    PERMISSION_LOST = "permission_lost"
    RESET = "reset"
    BATTERY_OUT_OF_RANGE = "battery_out_of_range"
    ABSENT_STRAP = "absent_strap"
    POWER_ZERO = "power_zero"
    ADAPTER_DOWN = "adapter_down"


@dataclass(frozen=True)
class Fault:
    """One fault from start to end, in seconds on the simulator's clock."""

    kind: FaultKind
    start: float
    end: float


class Faults:
    """The faults of one simulated device or adapter."""

    def __init__(self, faults: Sequence[Fault] = ()) -> None:
        self._faults = tuple(faults)

    def active(self, kind: FaultKind, now: float) -> bool:
        """Return whether a fault of a kind is on at now."""
        return any(f.kind == kind and f.start <= now < f.end
                   for f in self._faults)

    def starts(self, kinds: Sequence[FaultKind]) -> list[float]:
        """Return the start times of the faults of some kinds."""
        return sorted(f.start for f in self._faults if f.kind in kinds)


@dataclass(frozen=True)
class SimFaults:
    """The faults of the simulated trainer, strap and adapter."""

    trainer: tuple[Fault, ...] = ()
    strap: tuple[Fault, ...] = ()
    adapter: tuple[Fault, ...] = ()
