"""Phase 2 trainer spikes S1-S5. Throwaway: not app code."""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import os
import signal
import sys
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.exc import BleakError

import bluez_release
import ftms_codec as codec

VERSION = "spike-0.1.4"

FEATURE = codec.sig_uuid(0x2ACC)
INDOOR_BIKE = codec.sig_uuid(0x2AD2)
POWER_RANGE = codec.sig_uuid(0x2AD8)
RESISTANCE_RANGE = codec.sig_uuid(0x2AD6)
INCLINE_RANGE = codec.sig_uuid(0x2AD5)
CONTROL_POINT = codec.sig_uuid(0x2AD9)
MACHINE_STATUS = codec.sig_uuid(0x2ADA)
CYCLING_POWER = codec.sig_uuid(0x2A63)
HEART_RATE = codec.sig_uuid(0x2A37)
BATTERY = codec.sig_uuid(0x2A19)
DEVICE_INFO = {
    "manufacturer": codec.sig_uuid(0x2A29),
    "model": codec.sig_uuid(0x2A24),
    "hardware": codec.sig_uuid(0x2A27),
    "firmware": codec.sig_uuid(0x2A26),
    "software": codec.sig_uuid(0x2A28),
}

LINK_ERRORS = (BleakError, TimeoutError, OSError, EOFError)
STALE_MS = 2000
REPEAT_MS = 1000

Pending = tuple[int, "asyncio.Future[tuple[int, bytes]]"]
Releaser = Callable[[str], Awaitable[str]]


def now_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def utc_now() -> str:
    stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return stamp.replace("+00:00", "Z")


class RunLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file: TextIO = path.open("a", encoding="utf-8")

    def write(self, kind: str, **fields: Any) -> None:
        record = {"utc": utc_now(), "mono_ms": now_ms(), "kind": kind}
        self._file.write(json.dumps({**record, **fields}) + "\n")
        self._file.flush()

    def gatt(self, device: str, uuid: str, direction: str,
             data: bytes) -> None:
        self.write(direction, device=device, uuid=codec.short_uuid(uuid),
                   hex=data.hex())

    def event(self, name: str, **fields: Any) -> None:
        self.write("event", name=name, **fields)

    def close(self) -> None:
        self._file.close()


class Live:
    def __init__(self) -> None:
        self._values: dict[str, tuple[int, float]] = {}

    def update(self, prefix: str, values: Mapping[str, float]) -> None:
        stamp = now_ms()
        for name, value in values.items():
            self._values[f"{prefix}.{name}"] = (stamp, value)

    def get(self, key: str) -> float | None:
        entry = self._values.get(key)
        if entry is None or now_ms() - entry[0] > STALE_MS:
            return None
        return entry[1]


class Banner:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def show(self, text: str, seconds: float | None = None) -> None:
        self.text = text
        suffix = f" ({seconds:.0f} s)" if seconds else ""
        print(f"\n>>> {text}{suffix}", flush=True)


class Link:
    name = "device"
    subscriptions: tuple[str, ...] = ()

    def __init__(self, address: str, log: RunLog, live: Live,
                 factory: Callable[..., Any] = BleakClient,
                 releaser: Releaser = bluez_release.release) -> None:
        self.address = address
        self.log = log
        self.live = live
        self._factory = factory
        self._releaser = releaser
        self.client: Any = None
        self.lost = asyncio.Event()
        self.closing = False
        self.hold_off = 0.0
        self._generation = 0
        self._connecting = False

    @property
    def connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    async def connect(self, timeout: float = 10.0) -> None:
        self._generation += 1
        generation = self._generation
        await self._release_stale()
        self.lost.clear()
        self.client = self._factory(
            self.address,
            disconnected_callback=functools.partial(
                self._on_disconnect_of, generation),
            timeout=timeout)
        started = now_ms()
        self._connecting = True
        try:
            await self.client.connect()
        finally:
            self._connecting = False
        self.log.event("connected", device=self.name, address=self.address,
                       connect_ms=now_ms() - started)
        for uuid in self.subscriptions:
            try:
                await self.client.start_notify(uuid, self._on_data)
            except BleakError as error:
                self.log.event("subscribe_failed", device=self.name,
                               uuid=codec.short_uuid(uuid), error=str(error))
        await self.after_connect()

    async def after_connect(self) -> None:
        return None

    async def _release_stale(self) -> None:
        try:
            result = await self._releaser(self.address)
        except Exception as error:  # a failed release must not block a connect
            result = f"error {error!r}"
        self.log.event("stale_release", device=self.name, outcome=result)

    async def drop(self) -> None:
        self.log.event("forced_drop", device=self.name)
        print(f"\n--- dropping the {self.name} link on purpose", flush=True)
        await self.client.disconnect()

    def _on_disconnect_of(self, generation: int, client: Any) -> None:
        """bleak on BlueZ retries an aborted connect inside connect() and
        reports the abort as a disconnect, so those reports are ignored."""
        stale = generation != self._generation
        if stale or self._connecting:
            self.log.event("disconnect_ignored", device=self.name,
                           stale=stale, connecting=self._connecting)
            return
        self._on_disconnect(client)

    async def read(self, uuid: str) -> bytes | None:
        try:
            data = bytes(await self.client.read_gatt_char(uuid))
        except BleakError as error:
            self.log.event("read_failed", device=self.name,
                           uuid=codec.short_uuid(uuid), error=str(error))
            return None
        self.log.gatt(self.name, uuid, "read", data)
        return data

    def _on_disconnect(self, _client: Any) -> None:
        self.log.event("disconnected", device=self.name,
                       planned=self.closing)
        if not self.closing:
            print(f"\n!!! {self.name} link lost", flush=True)
        self.lost.set()

    def _on_data(self, sender: BleakGATTCharacteristic,
                 data: bytearray) -> None:
        payload = bytes(data)
        self.log.gatt(self.name, sender.uuid, "rx", payload)
        try:
            self.handle(sender.uuid, payload)
        except (ValueError, IndexError) as error:
            self.log.event("decode_failed", device=self.name,
                           uuid=codec.short_uuid(sender.uuid),
                           error=str(error))

    def handle(self, uuid: str, payload: bytes) -> None:
        raise NotImplementedError

    async def keep_alive(
        self, recovered: Callable[[], Awaitable[None]] | None = None
    ) -> None:
        while not self.closing:
            await self.lost.wait()
            if self.closing:
                return
            started = now_ms()
            if self.hold_off:
                print(f"    waiting {self.hold_off:.0f} s before reconnecting",
                      flush=True)
            await asyncio.sleep(self.hold_off)
            await self._reconnect()
            if recovered is not None:
                await recovered()
            seconds = (now_ms() - started) / 1000
            self.log.event("recovered", device=self.name, seconds=seconds)
            print(f"\n+++ {self.name} back after {seconds:.1f} s",
                  flush=True)

    async def _reconnect(self) -> None:
        while not self.closing:
            try:
                await self.connect()
                return
            except Exception as error:  # the spike must outlive any failure
                self.log.event("reconnect_failed", device=self.name,
                               error=repr(error))
                await asyncio.sleep(1)

    async def close(self) -> None:
        self.closing = True
        if self.connected:
            await self.client.disconnect()


class Trainer(Link):
    name = "trainer"
    subscriptions = (INDOOR_BIKE, CYCLING_POWER, MACHINE_STATUS,
                     CONTROL_POINT)

    def __init__(self, address: str, log: RunLog, live: Live,
                 factory: Callable[..., Any] = BleakClient,
                 releaser: Releaser = bluez_release.release) -> None:
        super().__init__(address, log, live, factory, releaser)
        self._lock = asyncio.Lock()
        self._pending: Pending | None = None
        self.resistance_size: int | None = None
        self.resistance_range = (0, 100, 1)
        self.has_control = False
        self.status_listener: Callable[[bytes], None] | None = None
        self.ibd_resistance_size = 2
        self._seen: set[str] = set()
        self._last_status: tuple[bytes, int] = (b"", 0)

    def handle(self, uuid: str, payload: bytes) -> None:
        if uuid == INDOOR_BIKE:
            values = codec.decode_indoor_bike(payload,
                                              self.ibd_resistance_size)
            self.live.update("ibd", values)
            if values["more_data"]:
                self._note_once("more_data_flag_seen")
            if values["extra_bytes"]:
                self._note_once("extra_bytes_seen",
                                count=values["extra_bytes"])
        elif uuid == CYCLING_POWER:
            self.live.update("cps", codec.decode_cycling_power(payload))
        elif uuid == MACHINE_STATUS:
            self._on_status(payload)
        elif uuid == CONTROL_POINT:
            self._on_response(payload)

    def _note_once(self, name: str, **fields: Any) -> None:
        if name not in self._seen:
            self._seen.add(name)
            self.log.event(name, **fields)

    def _is_repeat(self, payload: bytes) -> bool:
        last, stamp = self._last_status
        self._last_status = (payload, now_ms())
        return payload == last and now_ms() - stamp < REPEAT_MS

    def _on_status(self, payload: bytes) -> None:
        if self._is_repeat(payload):
            return
        text = codec.describe_status(payload)
        self.log.event("status", text=text)
        print(f"\n    status: {text}", flush=True)
        if payload[0] == 0xFF:
            self.has_control = False
        if self.status_listener is not None:
            self.status_listener(payload)

    def _on_response(self, payload: bytes) -> None:
        request, result, params = codec.decode_response(payload)
        if self._pending is None or self._pending[0] != request:
            self.log.event("unexpected_response", hex=payload.hex())
            return
        if not self._pending[1].done():
            self._pending[1].set_result((result, params))

    def _on_disconnect(self, client: Any) -> None:
        self.has_control = False
        if self._pending is not None and not self._pending[1].done():
            self._pending[1].set_result((codec.NO_RESPONSE, b""))
        super()._on_disconnect(client)

    async def command(self, payload: bytes,
                      timeout: float = 3.0) -> tuple[int, bytes]:
        async with self._lock:
            future = asyncio.get_running_loop().create_future()
            self._pending = (payload[0], future)
            started = now_ms()
            self.log.gatt(self.name, CONTROL_POINT, "tx", payload)
            try:
                await self.client.write_gatt_char(
                    CONTROL_POINT, payload, response=True)
                written = now_ms()
                result, params = await asyncio.wait_for(future, timeout)
            except LINK_ERRORS as error:
                self.log.event("command_failed", op=payload[0],
                               error=repr(error))
                return codec.NO_RESPONSE, b""
            finally:
                self._pending = None
            self.log.event("command_done", op=payload[0], result=result,
                           write_ms=written - started,
                           answer_ms=now_ms() - started)
            return result, params

    async def request_control(self) -> int:
        result, _ = await self.command(bytes([codec.REQUEST_CONTROL]))
        self.has_control = result == codec.SUCCESS
        return result

    async def start(self) -> int:
        result, _ = await self.command(bytes([codec.START_RESUME]))
        return result

    async def set_power(self, watts: int) -> int:
        result, _ = await self.command(codec.power_command(watts))
        return result

    async def set_resistance(self, raw: int) -> int:
        sizes = (self.resistance_size,) if self.resistance_size else (1, 2)
        result = codec.NO_RESPONSE
        for size in sizes:
            result, _ = await self.command(codec.resistance_command(raw, size))
            if result == codec.SUCCESS and self.resistance_size is None:
                self.resistance_size = size
                self.log.event("resistance_parameter_bytes", size=size)
            if result != codec.INVALID_PARAMETER:
                break
        return result

    async def spin_down(self) -> tuple[int, tuple[float, float] | None]:
        result, params = await self.command(
            bytes([codec.SPIN_DOWN, codec.SPIN_DOWN_START]), timeout=5.0)
        if result == codec.SUCCESS and len(params) >= 4:
            return result, codec.decode_spin_down_band(params)
        return result, None

    async def describe(self) -> list[str]:
        lines = []
        for label, uuid in DEVICE_INFO.items():
            data = await self.read(uuid)
            if data is not None:
                lines.append(f"{label}: {data.decode(errors='replace')}")
        feature = await self.read(FEATURE)
        if feature is not None:
            lines.append(self._describe_features(feature))
        for label, uuid in (("power", POWER_RANGE),
                            ("resistance", RESISTANCE_RANGE),
                            ("incline", INCLINE_RANGE)):
            data = await self.read(uuid)
            if data is not None:
                lines.append(f"{label} range (raw): "
                             f"{self._describe_range(uuid, data)}")
        return lines

    @staticmethod
    def _describe_features(data: bytes) -> str:
        try:
            machine, target = codec.decode_features(data)
        except ValueError as error:
            return f"features: {error}"
        return f"features: machine {machine:#010x} target {target:#010x}"

    def _describe_range(self, uuid: str, data: bytes) -> str:
        try:
            low, high, step = codec.decode_range(data)
        except ValueError as error:
            return str(error)
        if uuid == RESISTANCE_RANGE:
            self.resistance_range = (low, high, step)
            self.ibd_resistance_size = codec.resistance_field_size(
                len(data))
        return f"{low}..{high} step {step} ({len(data)} bytes)"

    async def close(self) -> None:
        self.closing = True
        if self.connected and self.has_control:
            low = self.resistance_range[0]
            print(f"\nReleasing: resistance raw {low}, then disconnect.")
            await self.set_resistance(low)
        await super().close()


class HeartRate(Link):
    name = "hrm"
    subscriptions = (HEART_RATE, BATTERY)

    def handle(self, uuid: str, payload: bytes) -> None:
        if uuid == HEART_RATE:
            self.live.update("hrm", codec.decode_heart_rate(payload))
        elif uuid == BATTERY:
            self._battery(payload)

    def _battery(self, payload: bytes) -> None:
        level = payload[0]
        self.live.update("hrm", {"battery_pct": level})
        self.log.event("battery", raw_hex=payload.hex(), value=level,
                       valid=level <= 100)

    async def after_connect(self) -> None:
        data = await self.read(BATTERY)
        if data:
            self._battery(data)
            print(f"HRM battery: raw {data.hex()} = {data[0]} "
                  f"({'valid' if data[0] <= 100 else 'OUT OF RANGE'})")


def fmt(value: float | None, spec: str = ".0f") -> str:
    return "--" if value is None else format(value, spec)


def link_state(link: Link | None) -> str:
    if link is None:
        return "--"
    return "ok" if link.connected else "LOST"


def live_line(elapsed: float, banner: Banner, live: Live,
              trainer: Trainer, hrm: Link | None) -> str:
    return (
        f"{elapsed:6.0f}s | {banner.text[:28]:<28} | "
        f"P {fmt(live.get('ibd.power_w')):>4} W "
        f"cps {fmt(live.get('cps.power_w')):>4} W | "
        f"v {fmt(live.get('ibd.speed_kmh'), '.1f'):>5} km/h | "
        f"HR {fmt(live.get('hrm.hr_bpm')):>3} | "
        f"trainer {link_state(trainer)} hrm {link_state(hrm)}"
    )


async def print_live(banner: Banner, live: Live, trainer: Trainer,
                     hrm: Link | None) -> None:
    started = time.monotonic()
    tick = started
    while True:
        print(live_line(time.monotonic() - started, banner, live, trainer,
                        hrm), flush=True)
        tick += 1.0
        await asyncio.sleep(max(0.0, tick - time.monotonic()))


async def sleep_until(deadline: float) -> None:
    await asyncio.sleep(max(0.0, deadline - time.monotonic()))


def report(label: str, result: int) -> None:
    print(f"    {label}: {codec.RESULTS.get(result, hex(result))}",
          flush=True)


class Session:
    def __init__(self, args: argparse.Namespace, log: RunLog) -> None:
        self.live = Live()
        self.banner = Banner("connecting")
        self.trainer = Trainer(args.trainer, log, self.live)
        self.trainer.hold_off = getattr(args, "hold_off", 0.0)
        self.hrm = HeartRate(args.hrm, log, self.live) if args.hrm else None
        self.log = log
        self._tasks: list[asyncio.Task[None]] = []

    async def __aenter__(self) -> Session:
        try:
            await self._open()
        except BaseException:
            await self.__aexit__()
            raise
        return self

    async def _open(self) -> None:
        await self.trainer.connect(timeout=30.0)
        for line in await self.trainer.describe():
            print(line)
            self.log.event("trainer_info", text=line)
        if self.hrm is not None:
            await self.hrm.connect(timeout=30.0)
        self.watch(print_live(self.banner, self.live, self.trainer,
                              self.hrm))

    def watch(self, coroutine: Awaitable[None]) -> None:
        self._tasks.append(asyncio.ensure_future(coroutine))

    async def take_control(self) -> None:
        report("Request Control", await self.trainer.request_control())
        report("Start or Resume", await self.trainer.start())

    async def __aexit__(self, *_exc: object) -> None:
        for task in self._tasks:
            task.cancel()
        for link in (self.trainer, self.hrm):
            if link is not None:
                try:
                    await asyncio.wait_for(link.close(), 8.0)
                except LINK_ERRORS as error:
                    self.log.event("close_failed", device=link.name,
                                   error=repr(error))


async def cmd_scan(args: argparse.Namespace, log: RunLog) -> None:
    found = await BleakScanner.discover(timeout=args.seconds,
                                        return_adv=True)
    rows = sorted(found.values(), key=lambda pair: -pair[1].rssi)
    for device, adv in rows:
        services = [codec.short_uuid(u) for u in adv.service_uuids]
        service_data = {codec.short_uuid(k): v.hex()
                        for k, v in adv.service_data.items()}
        name = adv.local_name or device.name or ""
        log.event("advertisement", address=device.address, name=name,
                  rssi=adv.rssi, service_uuids=services,
                  service_data=service_data,
                  manufacturer_data={str(k): v.hex() for k, v
                                     in adv.manufacturer_data.items()})
        tag = ("  <- FTMS trainer" if "1826" in services else
               "  <- heart rate" if "180d" in services else "")
        print(f"{device.address}  {adv.rssi:4d} dBm  {name:<22} "
              f"services {','.join(services) or '-'}  "
              f"data {service_data or '-'}{tag}")


async def cmd_contact(args: argparse.Namespace, log: RunLog) -> None:
    async with Session(args, log) as session:
        trainer, banner = session.trainer, session.banner
        banner.show("Pedal steadily ~85 rpm, no control", 30)
        await asyncio.sleep(30)
        banner.show("Request Control, ERG 200 W, no Start")
        report("Request Control", await trainer.request_control())
        report("Set Target Power 200 W", await trainer.set_power(200))
        banner.show("ERG 200: 20 s at ~80 rpm, then ~95", 40)
        await asyncio.sleep(40)
        report("Start or Resume", await trainer.start())
        report("Set Target Power 200 W", await trainer.set_power(200))
        banner.show("After Start: 20 s at ~80 rpm, then ~95", 40)
        await asyncio.sleep(40)
        low, high, _step = trainer.resistance_range
        for raw in codec.sweep_levels(low, high):
            report(f"Set Target Resistance raw {raw}",
                   await trainer.set_resistance(raw))
            banner.show(f"Resistance raw {raw}: ~85 rpm, same gear", 30)
            await asyncio.sleep(30)
        banner.show("Done")


async def cmd_steps(args: argparse.Namespace, log: RunLog) -> None:
    steps = codec.step_profile(args.warmup, args.reps)
    plan = codec.target_plan(steps, args.lead)
    total = codec.total_seconds(steps)
    log.event("profile", tag=args.tag, lead_s=args.lead,
              steps=[[s.seconds, s.watts] for s in steps])
    async with Session(args, log) as session:
        await session.take_control()
        started = time.monotonic()
        log.event("profile_start", start_ms=int(started * 1000))
        session.watch(track_steps(session.banner, steps, args.tag, started))
        for due, watts in plan:
            await sleep_until(started + due)
            log.event("target_due", watts=watts,
                      due_ms=int((started + due) * 1000))
            await session.trainer.set_power(watts)
        await sleep_until(started + total)
        session.banner.show("Profile done")


async def track_steps(banner: Banner, steps: list[codec.Step], tag: str,
                      started: float) -> None:
    shown: int | None = -1
    while True:
        index = codec.current_step(steps, time.monotonic() - started)
        if index != shown and index is not None:
            step = steps[index]
            banner.show(f"[{tag}] step {index + 1}/{len(steps)} "
                        f"{step.watts} W", step.seconds)
        shown = index
        await asyncio.sleep(0.1)


async def cmd_spindown(args: argparse.Namespace, log: RunLog) -> None:
    statuses: asyncio.Queue[bytes] = asyncio.Queue()
    async with Session(args, log) as session:
        trainer = session.trainer
        trainer.status_listener = statuses.put_nowait
        report("Request Control", await trainer.request_control())
        result, band = await trainer.spin_down()
        report("Spin Down Start", result)
        if band is None:
            return
        log.event("spin_down_band", low_kmh=band[0], high_kmh=band[1])
        session.banner.show(f"Ease up past {band[1]:.1f} km/h, no sprint; "
                            "stop pedaling the moment it says so")
        await wait_spin_down(statuses, session.banner, log)


async def wait_spin_down(statuses: asyncio.Queue[bytes], banner: Banner,
                         log: RunLog) -> None:
    started = time.monotonic()
    while time.monotonic() - started < 120:
        try:
            status = await asyncio.wait_for(statuses.get(), 1.0)
        except TimeoutError:
            continue
        if status[0] != codec.STATUS_SPIN_DOWN or len(status) < 2:
            continue
        outcome = codec.SPIN_DOWN_STATUS.get(status[1], hex(status[1]))
        if status[1] == 0x04:
            banner.show("STOP PEDALING NOW")
        elif status[1] in (0x02, 0x03):
            seconds = time.monotonic() - started
            log.event("spin_down_result", outcome=outcome, seconds=seconds)
            banner.show(f"Spin-down {outcome} after {seconds:.0f} s")
            return
    log.event("spin_down_result", outcome="timeout", seconds=120)
    banner.show("No spin-down result within 120 s")


async def cmd_ride(args: argparse.Namespace, log: RunLog) -> None:
    async with Session(args, log) as session:
        trainer = session.trainer
        await session.take_control()
        report(f"Set Target Power {args.watts} W",
               await trainer.set_power(args.watts))

        async def recovered() -> None:
            report("Request Control", await trainer.request_control())
            report(f"Set Target Power {args.watts} W",
                   await trainer.set_power(args.watts))

        session.watch(trainer.keep_alive(recovered))
        if session.hrm is not None:
            session.watch(session.hrm.keep_alive())
        for seconds in args.drop_at:
            session.watch(after(seconds, trainer.drop))
        if args.crash_at is not None:
            session.watch(after(args.crash_at, functools.partial(crash, log)))
        session.banner.show(f"ERG {args.watts} W for {args.minutes} min")
        await asyncio.sleep(args.minutes * 60)


async def after(seconds: float, action: Callable[[], Awaitable[None]]) -> None:
    await asyncio.sleep(seconds)
    await action()


async def crash(log: RunLog) -> None:
    log.event("forced_crash")
    print("\n--- crashing on purpose", flush=True)
    os.kill(os.getpid(), getattr(signal, "SIGKILL", signal.SIGTERM))


COMMANDS: dict[str, Callable[[argparse.Namespace, RunLog],
                             Awaitable[None]]] = {
    "scan": cmd_scan,
    "contact": cmd_contact,
    "steps": cmd_steps,
    "spindown": cmd_spindown,
    "ride": cmd_ride,
}


def lead_time(text: str) -> float:
    value = float(text)
    if not 0 <= value <= 5:
        raise argparse.ArgumentTypeError("lead time must be 0-5 s")
    return value


def repetitions(text: str) -> int:
    value = int(text)
    if not 1 <= value <= 6:
        raise argparse.ArgumentTypeError("reps must be 1-6")
    return value


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logdir", default="logs")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="list nearby devices (A-32)")
    scan.add_argument("--seconds", type=float, default=10.0)
    for name, text in (("contact", "S1 first contact"),
                       ("steps", "S2 ERG step response"),
                       ("spindown", "S3 spin-down"),
                       ("ride", "S4/S5 steady ERG ride with dropouts")):
        command = sub.add_parser(name, help=text)
        command.add_argument("--trainer", default=os.environ.get(
            "WOW_TRAINER"), required="WOW_TRAINER" not in os.environ)
        command.add_argument("--hrm", default=os.environ.get("WOW_HRM"))
        if name == "steps":
            command.add_argument("--lead", type=lead_time, default=0.0)
            command.add_argument("--tag", default="run")
            command.add_argument("--warmup", type=float, default=5.0)
            command.add_argument("--reps", type=repetitions, default=6)
        if name == "ride":
            command.add_argument("--watts", type=int, default=170)
            command.add_argument("--minutes", type=float, default=45.0)
            command.add_argument("--hold-off", type=float, default=0.0)
            command.add_argument("--drop-at", type=float, action="append",
                                 default=[])
            command.add_argument("--crash-at", type=float)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args(sys.argv[1:])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = RunLog(Path(args.logdir) / f"{args.command}-{stamp}.jsonl")
    log.event("start", version=VERSION, argv=sys.argv[1:],
              python=sys.version.split()[0], platform=sys.platform)
    print(f"Logging to {log.path}")
    try:
        asyncio.run(COMMANDS[args.command](args, log))
    except KeyboardInterrupt:
        print("\nStopped.")
    except BleakError as error:
        log.event("fatal", error=repr(error))
        print(f"\nBluetooth error: {error}")
    finally:
        log.event("end")
        log.close()


if __name__ == "__main__":
    main()
