"""Run FTMS control as a state machine.

Trainer control over the FTMS control point: take control, one
procedure at a time with the latest command winning, regain control,
time-outs and the orderly release (ICD IF-01, 4.1.5 and 4.1.6).
"""

from dataclasses import dataclass, replace
from enum import StrEnum

from wow.core import ftms_codec as codec
from wow.core.devices import (
    Erg, Range, Resistance, TrainerCapabilities, TrainerCommand,
)
from wow.core.ftms_codec import Dropped, ResultCode
from wow.core.jsonform import Registry
from wow.core.vocab import Mode, Problem
from typing import Final

NOT_RESPONDING_WARN: Final[float] = 3.0
PROCEDURE_TIMEOUT: Final[float] = 30.0
REGAIN_INTERVAL: Final[float] = 2.0
EXPECTED_RESET_WINDOW: Final[float] = 1.0
STATUS_DEDUP: Final[float] = 0.5
FAILED_RETRY_DELAY: Final[float] = 2.0
RELEASE_TIMEOUT: Final[float] = 2.0


NO_CAPABILITIES: Final[TrainerCapabilities] = TrainerCapabilities(
    None, None, False, False)


@dataclass(frozen=True)
class LinkUp:
    """Event: the trainer link is up."""

    capabilities: TrainerCapabilities


@dataclass(frozen=True)
class LinkDown:
    """Event: the trainer link is down."""

    pass


@dataclass(frozen=True)
class Indication:
    """Event: a control point indication arrived."""

    data: bytes


@dataclass(frozen=True)
class StatusNotification:
    """Event: a machine status notification arrived."""

    data: bytes


@dataclass(frozen=True)
class SetCommand:
    """Event: the desired trainer command changed."""

    command: TrainerCommand


@dataclass(frozen=True)
class Release:
    """Event: give up control of the trainer."""

    pass


@dataclass(frozen=True)
class Tick:
    """Event: a deadline of the session has come."""

    pass


SessionEvent = (
    LinkUp | LinkDown | Indication | StatusNotification | SetCommand
    | Release | Tick
)


@dataclass(frozen=True)
class Write:
    """Action: write to the control point."""

    data: bytes


@dataclass(frozen=True)
class CloseLink:
    """Action: close the link to the trainer."""

    pass


@dataclass(frozen=True)
class WarningChanged:
    """Action: a warning was raised or cleared."""

    kind: Problem
    active: bool


@dataclass(frozen=True)
class StatusForwarded:
    """Action: pass a machine status on to the ride."""

    data: bytes


@dataclass(frozen=True)
class ModeUnavailable:
    """Action: the trainer rejected a control mode."""

    mode: Mode


@dataclass(frozen=True)
class Logged:
    """Action: record a protocol event."""

    event: str
    data: bytes


SessionAction = (
    Write | CloseLink | WarningChanged | StatusForwarded | ModeUnavailable
    | Logged
)

SESSION_FORMS: Final[Registry] = Registry(
    LinkUp, LinkDown, Indication, StatusNotification, SetCommand, Release,
    Tick, Write, CloseLink, WarningChanged, StatusForwarded,
    ModeUnavailable, Logged, TrainerCapabilities, Range, Erg, Resistance,
)


class Phase(StrEnum):
    """Phase of the control procedure."""

    DISCONNECTED = "disconnected"
    REQUESTING_CONTROL = "requesting_control"
    STARTING = "starting"
    READY = "ready"
    REGAINING_CONTROL = "regaining_control"
    RELEASING = "releasing"


@dataclass(frozen=True)
class _Procedure:
    data: bytes
    since: float
    command: TrainerCommand | None
    retried: bool

    @property
    def op(self) -> int:
        return self.data[0]


class FtmsSession:
    """Control of one trainer over its FTMS control point."""

    def __init__(self) -> None:
        self._phase = Phase.DISCONNECTED
        self._capabilities = NO_CAPABILITIES
        self._desired: TrainerCommand | None = None
        self._applied: TrainerCommand | None = None
        self._pending: _Procedure | None = None
        self._granted_at: float | None = None
        self._regain_at: float | None = None
        self._blocked_until: float | None = None
        self._retry_next = False
        self._release_sent = False
        self._release_deadline: float | None = None
        self._responding = True
        self._warnings: set[Problem] = set()
        self._status_seen: dict[bytes, float] = {}

    @property
    def phase(self) -> Phase:
        """Return the current phase."""
        return self._phase

    def capabilities(self) -> TrainerCapabilities | None:
        """Return the capabilities from the link, if known."""
        if self._phase == Phase.DISCONNECTED:
            return None
        return self._capabilities

    def responding(self) -> bool:
        """Return whether the trainer answers in time."""
        return self._responding

    def in_control(self) -> bool:
        """Return whether the app holds control."""
        return self._phase in (Phase.STARTING, Phase.READY, Phase.RELEASING)

    def handle(self, event: SessionEvent, now: float) -> list[SessionAction]:
        """Handle an event and return the actions to carry out."""
        match event:
            case LinkUp(capabilities=capabilities):
                actions = self._on_link_up(capabilities)
            case LinkDown():
                actions = self._on_link_down()
            case Indication(data=data):
                actions = self._on_indication(data, now)
            case StatusNotification(data=data):
                actions = self._on_status(data, now)
            case SetCommand(command=command):
                self._desired = command
                actions = []
            case Release():
                actions = self._on_release()
            case Tick():
                actions = self._on_tick(now)
        return actions + self._send_if_ready(now)

    def next_deadline(self) -> float | None:
        """Return the time of the next Tick, if any."""
        times: list[float] = []
        if self._pending is not None:
            if self._responding:
                times.append(self._pending.since + NOT_RESPONDING_WARN)
            times.append(self._pending.since + PROCEDURE_TIMEOUT)
        if self._release_deadline is not None:
            times.append(self._release_deadline)
        send_at = self._next_send_time()
        if send_at is not None:
            times.append(send_at)
        return min(times, default=None)

    def _on_link_up(
        self, capabilities: TrainerCapabilities
    ) -> list[SessionAction]:
        actions = self._clear_warnings()
        self._phase = Phase.REQUESTING_CONTROL
        self._capabilities = capabilities
        self._reset_link_state()
        return actions

    def _on_link_down(self) -> list[SessionAction]:
        actions = self._clear_warnings()
        self._phase = Phase.DISCONNECTED
        self._reset_link_state()
        return actions

    def _reset_link_state(self) -> None:
        self._applied = None
        self._pending = None
        self._granted_at = None
        self._regain_at = None
        self._blocked_until = None
        self._retry_next = False
        self._release_sent = False
        self._release_deadline = None
        self._responding = True
        self._status_seen.clear()

    def _on_release(self) -> list[SessionAction]:
        self._desired = None
        lowest = self._lowest_level()
        holds_control = self._phase in (Phase.READY, Phase.RELEASING)
        if holds_control and lowest is not None:
            self._phase = Phase.RELEASING
            return []
        if self._phase == Phase.DISCONNECTED:
            return []
        return self._close()

    def _close(self) -> list[SessionAction]:
        actions = self._clear_warnings()
        self._phase = Phase.DISCONNECTED
        self._reset_link_state()
        return actions + [CloseLink()]

    def _on_indication(self, data: bytes, now: float) -> list[SessionAction]:
        response = codec.decode_control_point_response(data)
        if isinstance(response, Dropped):
            return [Logged("bad_indication", data)]
        procedure = self._pending
        if procedure is None or response.request_op != procedure.op:
            return [Logged("unexpected_response", data)]
        self._pending = None
        actions: list[SessionAction] = []
        if not self._responding:
            self._responding = True
            actions += self._set_warning(Problem.TRAINER_NOT_RESPONDING, False)
        if self._phase == Phase.RELEASING:
            return actions + (self._close() if self._release_sent else [])
        if procedure.op == codec.REQUEST_CONTROL:
            return actions + self._on_control_answer(
                procedure, response.result, now)
        if procedure.op == codec.START_OR_RESUME:
            return actions + self._on_start_answer(response.result, data)
        return actions + self._on_command_answer(
            procedure, response.result, data, now)

    def _on_control_answer(
        self, procedure: _Procedure, result: int, now: float
    ) -> list[SessionAction]:
        if result == ResultCode.SUCCESS:
            self._phase = Phase.STARTING
            self._granted_at = now
            self._applied = None
            return self._set_warning(Problem.CONTROL_REFUSED, False)
        self._phase = Phase.REGAINING_CONTROL
        self._regain_at = procedure.since + REGAIN_INTERVAL
        return self._set_warning(Problem.CONTROL_REFUSED, True)

    def _on_start_answer(
        self, result: int, data: bytes
    ) -> list[SessionAction]:
        if result == ResultCode.CONTROL_NOT_PERMITTED:
            return self._lose_control()
        self._phase = Phase.READY
        if result != ResultCode.SUCCESS:
            return [Logged("start_not_accepted", data)]
        return []

    def _on_command_answer(
        self, procedure: _Procedure, result: int, data: bytes, now: float
    ) -> list[SessionAction]:
        match result:
            case ResultCode.SUCCESS:
                self._applied = procedure.command
                return []
            case ResultCode.CONTROL_NOT_PERMITTED:
                return self._lose_control()
            case ResultCode.NOT_SUPPORTED:
                return self._mode_unavailable(procedure.command, data)
            case ResultCode.INVALID_PARAMETER:
                self._desired = self._applied
                return [Logged("invalid_parameter", data + procedure.data)]
            case _:
                return self._operation_failed(procedure, data, now)

    def _mode_unavailable(
        self, command: TrainerCommand | None, data: bytes
    ) -> list[SessionAction]:
        capabilities = self._capabilities
        actions: list[SessionAction] = [Logged("not_supported", data)]
        if isinstance(command, Erg):
            self._capabilities = replace(capabilities, power=None)
            mode = Mode.ERG
        else:
            self._capabilities = replace(capabilities, resistance=None)
            mode = Mode.RESISTANCE
        if type(self._desired) is type(command):
            self._desired = None
        return actions + [ModeUnavailable(mode)]

    def _operation_failed(
        self, procedure: _Procedure, data: bytes, now: float
    ) -> list[SessionAction]:
        actions: list[SessionAction] = [Logged("operation_failed", data)]
        self._retry_next = True
        if not procedure.retried:
            self._blocked_until = now + FAILED_RETRY_DELAY
            return actions
        self._blocked_until = now + PROCEDURE_TIMEOUT
        if self._responding:
            self._responding = False
            actions += self._set_warning(Problem.TRAINER_NOT_RESPONDING, True)
        return actions

    def _on_status(self, data: bytes, now: float) -> list[SessionAction]:
        status = codec.decode_status(data)
        if isinstance(status, Dropped):
            return [Logged("bad_status", data)]
        seen = self._status_seen.get(data)
        if seen is not None and now - seen < STATUS_DEDUP:
            return []
        self._status_seen = {
            key: at for key, at in self._status_seen.items()
            if now - at < STATUS_DEDUP
        }
        self._status_seen[data] = now
        match status.code:
            case codec.STATUS_RESET:
                return self._on_reset(now)
            case codec.STATUS_CONTROL_PERMISSION_LOST:
                if self._phase in (Phase.STARTING, Phase.READY):
                    return self._lose_control()
                return []
            case codec.STATUS_SPIN_DOWN:
                return [StatusForwarded(data)]
            case _:
                return []

    def _on_reset(self, now: float) -> list[SessionAction]:
        granted = self._granted_at
        if granted is not None and now - granted <= EXPECTED_RESET_WINDOW:
            return []
        if self._phase in (Phase.STARTING, Phase.READY):
            return self._lose_control()
        return []

    def _lose_control(self) -> list[SessionAction]:
        self._phase = Phase.REGAINING_CONTROL
        self._granted_at = None
        self._applied = None
        self._regain_at = None
        return self._set_warning(Problem.CONTROL_REFUSED, True)

    def _on_tick(self, now: float) -> list[SessionAction]:
        actions: list[SessionAction] = []
        deadline = self._release_deadline
        if deadline is not None and now >= deadline:
            return self._close()
        procedure = self._pending
        if procedure is None:
            return actions
        if self._responding and now >= procedure.since + NOT_RESPONDING_WARN:
            self._responding = False
            actions += self._set_warning(Problem.TRAINER_NOT_RESPONDING, True)
            actions.append(Logged("no_answer", procedure.data))
        if now >= procedure.since + PROCEDURE_TIMEOUT:
            self._pending = None
            actions.append(Logged("procedure_timeout", procedure.data))
        return actions

    def _next_procedure(self) -> tuple[bytes, TrainerCommand | None] | None:
        match self._phase:
            case Phase.REQUESTING_CONTROL | Phase.REGAINING_CONTROL:
                return codec.encode_request_control(), None
            case Phase.STARTING:
                return codec.encode_start_or_resume(), None
            case Phase.READY:
                return self._command_procedure()
            case Phase.RELEASING:
                lowest = self._lowest_level()
                if self._release_sent or lowest is None:
                    return None
                command = Resistance(lowest)
                return codec.encode_command(command), command
            case _:
                return None

    def _command_procedure(self) -> tuple[bytes, TrainerCommand] | None:
        desired = self._desired
        if desired is None or desired == self._applied:
            return None
        if not self._mode_available(desired):
            return None
        return codec.encode_command(desired), desired

    def _mode_available(self, command: TrainerCommand) -> bool:
        if isinstance(command, Erg):
            return self._capabilities.power is not None
        return self._capabilities.resistance is not None

    def _lowest_level(self) -> int | None:
        resistance = self._capabilities.resistance
        return None if resistance is None else resistance.minimum

    def _gate(self) -> float | None:
        gates: list[float] = []
        blocked = self._blocked_until
        if blocked is not None and self._phase != Phase.RELEASING:
            gates.append(blocked)
        if (self._phase == Phase.REGAINING_CONTROL
                and self._regain_at is not None):
            gates.append(self._regain_at)
        return max(gates, default=None)

    def _next_send_time(self) -> float | None:
        if self._pending is not None or self._next_procedure() is None:
            return None
        return self._gate()

    def _send_if_ready(self, now: float) -> list[SessionAction]:
        if self._pending is not None:
            return []
        procedure = self._next_procedure()
        if procedure is None:
            return []
        gate = self._gate()
        if gate is not None and now < gate:
            return []
        data, command = procedure
        self._blocked_until = None
        self._pending = _Procedure(data, now, command, self._retry_next)
        self._retry_next = False
        if self._phase == Phase.RELEASING:
            self._release_sent = True
            self._release_deadline = now + RELEASE_TIMEOUT
        return [Write(data)]

    def _set_warning(self, kind: Problem, active: bool) -> list[SessionAction]:
        if (kind in self._warnings) == active:
            return []
        if active:
            self._warnings.add(kind)
        else:
            self._warnings.discard(kind)
        return [WarningChanged(kind, active)]

    def _clear_warnings(self) -> list[SessionAction]:
        return [
            action
            for kind in sorted(self._warnings)
            for action in self._set_warning(kind, False)
        ]
