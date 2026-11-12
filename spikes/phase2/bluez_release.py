"""Drop a BlueZ connection that no process owns any more (spike)."""

from __future__ import annotations

import sys

NOT_CONNECTED = "org.bluez.Error.NotConnected"
UNKNOWN_OBJECT = "org.freedesktop.DBus.Error.UnknownObject"


def device_path(address: str, adapter: str = "hci0") -> str:
    return f"/org/bluez/{adapter}/dev_{address.upper().replace(':', '_')}"


def outcome(error_name: str | None) -> str:
    if error_name is None:
        return "released"
    if error_name == NOT_CONNECTED:
        return "not connected"
    if error_name == UNKNOWN_OBJECT:
        return "unknown to BlueZ"
    return f"error {error_name}"


async def release(address: str) -> str:
    """BlueZ keeps a link after its owner dies, and the trainer stops
    advertising while linked, so a new process can't find it to connect."""
    if sys.platform != "linux":
        return "skipped"
    from dbus_fast import BusType, Message, MessageType
    from dbus_fast.aio import MessageBus

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        reply = await bus.call(Message(
            destination="org.bluez", path=device_path(address),
            interface="org.bluez.Device1", member="Disconnect"))
    finally:
        bus.disconnect()
    failed = reply.message_type == MessageType.ERROR
    return outcome(reply.error_name if failed else None)
