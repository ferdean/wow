"""Simulate the other devices a scan finds.

Devices that only advertise, for the device scan (APP-114; T-DEV-05): a
cadence sensor with the Cycling Speed and Cadence service, and two
devices without a fitness service that the scan has to hide.
"""

from typing import Final

from wow.adapters.ble_sim.scheduler import SimScheduler
from wow.adapters.ble_sim.server import SimServerBase
from wow.core import uuids
from wow.core.uuids import sig_uuid
from wow.ports.gatt import Advertisement

CADENCE_ADDRESS: Final[str] = "C8:4A:2D:11:22:33"
CADENCE_NAME: Final[str] = "CADENCE-1816"
TV_ADDRESS: Final[str] = "5C:49:7D:01:02:03"
PHONE_ADDRESS: Final[str] = "7A:12:9F:44:55:66"
DEVICE_INFORMATION_SERVICE: Final[str] = sig_uuid(0x180A)
BATTERY_SERVICE: Final[str] = sig_uuid(0x180F)


class SimAdvertiser(SimServerBase):
    """A device that advertises and offers nothing else."""

    def __init__(self, scheduler: SimScheduler, address: str,
                 name: str | None, services: tuple[str, ...],
                 rssi_dbm: int) -> None:
        super().__init__(
            scheduler,
            Advertisement(address=address, name=name, rssi_dbm=rssi_dbm,
                          service_uuids=services, service_data={}),
            frozenset())


def bystanders(scheduler: SimScheduler) -> list[SimServerBase]:
    """Return a cadence sensor, a television and a phone."""
    return [
        SimAdvertiser(scheduler, CADENCE_ADDRESS, CADENCE_NAME,
                      (uuids.CYCLING_SPEED_AND_CADENCE_SERVICE,), -70),
        SimAdvertiser(scheduler, TV_ADDRESS, "Living room TV",
                      (DEVICE_INFORMATION_SERVICE,), -50),
        SimAdvertiser(scheduler, PHONE_ADDRESS, None, (BATTERY_SERVICE,),
                      -65),
    ]
