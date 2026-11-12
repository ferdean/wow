"""Define simulated GATT servers and their shared plumbing.

Simulated GATT servers: the protocol and the shared plumbing (ICD 4.3.1).

Next to the ICD's four methods, a simulated server says whether it is
advertising and hears about connects and disconnects, so the D100 can
stop advertising while linked (F-33).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from wow.adapters.ble_sim.scheduler import SimScheduler
from wow.ports.gatt import Advertisement, Uuid


class GattServer(Protocol):
    """A simulated GATT server."""

    def advertisement(self) -> Advertisement:
        """Return the advertisement of the device."""
        ...

    def advertising(self) -> bool:
        """Return whether the device advertises."""
        ...

    def on_connect(self) -> None:
        """Handle a connection."""
        ...

    def on_disconnect(self) -> None:
        """Handle a disconnection."""
        ...

    def on_read(self, char: Uuid) -> bytes:
        """Return the value of a characteristic."""
        ...

    def on_write(self, char: Uuid, data: bytes) -> None:
        """Handle a write to a characteristic."""
        ...

    def on_subscribe(
        self, char: Uuid, notify: Callable[[bytes], None]
    ) -> None:
        """Start notifying a characteristic through notify."""
        ...


@dataclass
class Traffic:
    """What a server has seen, for tests."""

    reads: list[tuple[Uuid, bytes]] = field(default_factory=list)
    writes: list[tuple[Uuid, bytes]] = field(default_factory=list)
    sent: list[tuple[Uuid, bytes]] = field(default_factory=list)
    subscribed: list[Uuid] = field(default_factory=list)


class SimServerBase:
    """Shared behaviour of the simulated servers."""

    def __init__(
        self,
        scheduler: SimScheduler,
        advertisement: Advertisement,
        notifiable: frozenset[Uuid],
    ) -> None:
        self.scheduler = scheduler
        self.notifiable = notifiable
        self.traffic = Traffic()
        self._advertisement = advertisement
        self._subscribers: dict[Uuid, Callable[[bytes], None]] = {}
        self._linked = False

    def advertisement(self) -> Advertisement:
        """Return the advertisement of the device."""
        return self._advertisement

    def advertising(self) -> bool:
        """Return whether the device advertises."""
        return True

    def linked(self) -> bool:
        """Return whether a client is connected."""
        return self._linked

    def on_connect(self) -> None:
        """Handle a connection."""
        self._linked = True
        self._subscribers.clear()

    def on_disconnect(self) -> None:
        """Handle a disconnection."""
        self._linked = False
        self._subscribers.clear()
        self.stopped()

    def on_read(self, char: Uuid) -> bytes:
        """Return the value of a characteristic."""
        value = self.read_value(char)
        self.traffic.reads.append((char, value))
        return value

    def on_write(self, char: Uuid, data: bytes) -> None:
        """Handle a write to a characteristic."""
        self.traffic.writes.append((char, data))
        self.written(char, data)

    def on_subscribe(
        self, char: Uuid, notify: Callable[[bytes], None]
    ) -> None:
        """Start notifying a characteristic through notify."""
        if char not in self.notifiable:
            raise KeyError(char)
        self._subscribers[char] = notify
        self.traffic.subscribed.append(char)
        self.subscribed(char)

    def send(self, char: Uuid, data: bytes) -> None:
        """Notify a characteristic."""
        notify = self._subscribers.get(char)
        if notify is None:
            return
        self.traffic.sent.append((char, data))
        notify(data)

    def read_value(self, char: Uuid) -> bytes:
        """Return the value of a characteristic."""
        raise KeyError(char)

    def written(self, char: Uuid, data: bytes) -> None:
        """Handle a write to a characteristic."""
        raise KeyError(char)

    def subscribed(self, char: Uuid) -> None:
        """Start the notifications of a characteristic."""
        return None

    def stopped(self) -> None:
        """Stop all timed behaviour."""
        return None
