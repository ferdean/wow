"""Release a BlueZ link that no process owns.

Releases a BlueZ link that no process owns any more (F-33, A-44).

BlueZ keeps a link after its owner dies and the D100 stops advertising
while linked, so a restarted app could not find the trainer to connect.
"""

import sys
from typing import Final

NOT_CONNECTED: Final[str] = "org.bluez.Error.NotConnected"
UNKNOWN_OBJECT: Final[str] = "org.freedesktop.DBus.Error.UnknownObject"


def device_path(address: str, adapter: str) -> str:
    """Return the D-Bus path of a device."""
    return f"/org/bluez/{adapter}/dev_{address.upper().replace(':', '_')}"


def outcome(error_name: str | None) -> str:
    """Return the outcome word of a D-Bus error."""
    if error_name is None:
        return "released"
    if error_name == NOT_CONNECTED:
        return "not connected"
    if error_name == UNKNOWN_OBJECT:
        return "unknown to BlueZ"
    return f"error {error_name}"


async def release_stale_link(address: str, adapter: str) -> str:
    """Disconnect a stale link; return the outcome."""
    if sys.platform != "linux":
        return "skipped"
    from dbus_fast import BusType, Message, MessageType
    from dbus_fast.aio import MessageBus

    try:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    except (OSError, EOFError) as error:
        return f"no system bus: {error}"
    try:
        reply = await bus.call(Message(
            destination="org.bluez", path=device_path(address, adapter),
            interface="org.bluez.Device1", member="Disconnect"))
    finally:
        bus.disconnect()
    failed = reply.message_type == MessageType.ERROR
    return outcome(reply.error_name if failed else None)
