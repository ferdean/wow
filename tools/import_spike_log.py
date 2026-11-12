"""Convert a Phase 2 spike log into the Bluetooth log format.

Converts a Phase 2 spike log into the Bluetooth log format IF-11, once,
for testdata/ble/ (ICD 4.11; test plan section 3).

Spike records: {"utc", "mono_ms", "kind", "device", "uuid", "hex"}, where
kind is "rx" (notification or indication), "tx" (write) or "read", and
uuid is the short form ("2ad2"); events are {"kind": "event", "name"}.

Usage:
    uv run python tools/import_spike_log.py \
        logs/contact-20261104T214602Z.jsonl \
        testdata/ble/phase2-s1-contact.jsonl
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from wow.adapters.ble_log import BleLogRecord, record_line
from wow.adapters.ble_sim import D100_ADDRESS, HRM_ADDRESS
from wow.core.uuids import FITNESS_MACHINE_CONTROL_POINT, sig_uuid
from typing import Final

OPS: Final[dict[str, str]] = {"tx": "write", "read": "read"}
LINK_EVENTS: Final[dict[str, str]] = {
    "connected": "connected", "disconnected": "disconnected"}


def full_uuid(text: str) -> str:
    """Return the full UUID of a short or full one."""
    return text.lower() if "-" in text else sig_uuid(int(text, 16))


def convert(
    lines: Iterable[str], addresses: Mapping[str, str]
) -> tuple[list[BleLogRecord], Counter[str]]:
    """Convert spike log lines; count the records skipped."""
    records: list[BleLogRecord] = []
    skipped: Counter[str] = Counter()
    generation = {dev: 1 for dev in addresses}
    seen_connect = {dev: False for dev in addresses}
    for line in lines:
        if not line.strip():
            continue
        spike = json.loads(line)
        kind, dev = spike.get("kind"), spike.get("device")
        if dev not in addresses:
            skipped[f"{kind}:{spike.get('name', '')}"] += 1
            continue
        if kind == "event":
            op = LINK_EVENTS.get(spike.get("name", ""))
            if op is None:
                skipped[f"event:{spike.get('name')}"] += 1
                continue
            if op == "connected":
                generation[dev] += seen_connect[dev]
                seen_connect[dev] = True
            uuid, data = None, None
        elif kind == "rx":
            uuid, data = full_uuid(spike["uuid"]), spike["hex"]
            op = ("indicate" if uuid == FITNESS_MACHINE_CONTROL_POINT
                  else "notify")
        elif kind in OPS:
            uuid, data, op = full_uuid(spike["uuid"]), spike["hex"], OPS[kind]
        else:
            skipped[str(kind)] += 1
            continue
        records.append(BleLogRecord(
            utc=spike["utc"], mono_ms=float(spike["mono_ms"]), dev=dev,
            addr=addresses[dev], gen=generation[dev], op=op, uuid=uuid,
            hex=data))
    return records, skipped


def main(argv: Sequence[str] | None = None) -> int:
    """Convert a log from the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spike_log", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--trainer", default=D100_ADDRESS)
    parser.add_argument("--hrm", default=HRM_ADDRESS)
    args = parser.parse_args(argv)
    lines = args.spike_log.read_text(encoding="utf-8").splitlines()
    records, skipped = convert(lines, {"trainer": args.trainer,
                                       "hrm": args.hrm})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(record_line(r) + "\n" for r in records), encoding="utf-8")
    print(f"{len(lines)} spike lines, {len(records)} IF-11 lines written "
          f"to {args.output}")
    for name, count in sorted(skipped.items()):
        print(f"  left out: {name} x {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
