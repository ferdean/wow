"""L3 rig: the app shell on the stepped clock with the simulated D100 and
HRM 200 behind the logging connector (test plan 2.1)."""

from dataclasses import dataclass, field

from wow.adapters.ble_log import BleLogRecord, LoggingConnector
from wow.adapters.ble_sim import (
    D100_ADDRESS, HRM_ADDRESS, SimConnector, SimD100Server, SimHrm200Server,
    SimScheduler,
)
from wow.adapters.ble_sim.d100 import (
    D100_FEATURES, D100_POWER_RANGE, D100_RESISTANCE_RANGE,
)
from wow.adapters.clock_stepped import SteppedClock
from wow.app.device_manager import DeviceChoice, DeviceManager
from wow.app.ftms_trainer import FtmsTrainer
from wow.app.hrm_link import HrmLink
from wow.core.devices import HrSample, TrainerSample


@dataclass
class Rig:
    clock: SteppedClock
    scheduler: SimScheduler
    sim: SimConnector
    d100: SimD100Server | None
    hrm: SimHrm200Server | None
    trainer: FtmsTrainer
    strap: HrmLink
    manager: DeviceManager
    log: list[BleLogRecord] = field(default_factory=list)
    trainer_samples: list[TrainerSample] = field(default_factory=list)
    hr_samples: list[HrSample] = field(default_factory=list)

    async def close(self) -> None:
        await self.clock.drive(self.manager.close(), limit=60.0)
        await self.scheduler.close()


def make_rig(
    *,
    with_d100: bool = True,
    with_hrm: bool = True,
    features: bytes = D100_FEATURES,
    power_range: bytes | None = D100_POWER_RANGE,
    resistance_range: bytes | None = D100_RESISTANCE_RANGE,
    battery_pct: int = 80,
    d100_type: type[SimD100Server] = SimD100Server,
    choice: DeviceChoice = DeviceChoice(D100_ADDRESS, HRM_ADDRESS),
) -> Rig:
    clock = SteppedClock()
    scheduler = SimScheduler(clock)
    d100 = d100_type(
        scheduler, features=features, power_range=power_range,
        resistance_range=resistance_range) if with_d100 else None
    hrm = (SimHrm200Server(scheduler, battery_pct=battery_pct)
           if with_hrm else None)
    servers = [s for s in (d100, hrm) if s is not None]
    log: list[BleLogRecord] = []
    roles = {D100_ADDRESS: "trainer", HRM_ADDRESS: "hrm"}
    sim = SimConnector(clock, servers)
    connector = LoggingConnector(
        sim, clock, log.append,
        lambda address: roles.get(address.upper(), "other"))
    trainer_samples: list[TrainerSample] = []
    hr_samples: list[HrSample] = []
    trainer = FtmsTrainer(clock, on_sample=trainer_samples.append)
    strap = HrmLink(clock, on_sample=hr_samples.append)
    manager = DeviceManager(connector, clock, trainer, strap, choice)
    return Rig(clock, scheduler, sim, d100, hrm, trainer, strap, manager,
               log, trainer_samples, hr_samples)
