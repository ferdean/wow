"""Write the ride journal and Bluetooth logs.

Writes the ride journal and the Bluetooth logs as JSON Lines from a
worker thread, so disk writes never stall the event loop (AD-06; ICD
IF-09, IF-11).

Slice SL-02: the ride directory, `events.jsonl`, `ble.jsonl` and
`logs/ble-system.jsonl`, synced at most every 2 s and when a ride closes.
Samples, timing, `meta.json` and the FIT file follow in SL-03.
"""

import json
import logging
import os
import queue
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, IO

from wow.adapters.ble_log import BleLogRecord, record_line

logger = logging.getLogger(__name__)

SYNC_INTERVAL: Final[float] = 2.0
JOURNAL: Final[str] = "events.jsonl"
BLE_LOG: Final[str] = "ble.jsonl"


@dataclass(frozen=True)
class _Item:
    kind: str
    path: Path | None = None
    text: str = ""
    done: threading.Event | None = None


class Recorder:
    """Writes JSON Lines from a worker thread."""

    def __init__(self, data: Path, boot_id: str) -> None:
        self._data = data
        self.boot_id = boot_id
        self._ride: Path | None = None
        self._queue: queue.Queue[_Item] = queue.Queue()
        self._thread = threading.Thread(target=self._work, name="recorder",
                                        daemon=True)

    @property
    def ride_dir(self) -> Path | None:
        """Return the open ride directory, if any."""
        return self._ride

    def start(self) -> None:
        """Start the worker thread."""
        self._thread.start()

    def stop(self) -> None:
        """Write everything pending and stop the worker."""
        self._queue.put(_Item("stop"))
        self._thread.join(timeout=10.0)

    def open_ride(self, ride_id: str) -> Path:
        """Create the directory and files of a ride."""
        self._ride = self._data / "rides" / ride_id
        self._queue.put(_Item("mkdir", self._ride))
        return self._ride

    def close_ride(self, ride: Path) -> None:
        """Close the files of a ride."""
        if self._ride == ride:
            self._ride = None
        self._queue.put(_Item("close", ride / JOURNAL))
        self._queue.put(_Item("close", ride / BLE_LOG))

    def journal(self, record: Mapping[str, object]) -> None:
        """Queue a journal record."""
        if self._ride is None:
            logger.warning("journal record outside a ride: %s", record)
            return
        self._queue.put(_Item("line", self._ride / JOURNAL,
                              json.dumps(dict(record))))

    def ble(self, record: BleLogRecord) -> None:
        """Queue a Bluetooth log record."""
        target = (self._data / "logs" / "ble-system.jsonl"
                  if self._ride is None else self._ride / BLE_LOG)
        self._queue.put(_Item("line", target, record_line(record)))

    def flush(self) -> None:
        """Wait until everything queued is written."""
        done = threading.Event()
        self._queue.put(_Item("flush", done=done))
        done.wait(timeout=10.0)

    def _work(self) -> None:
        files: dict[Path, IO[str]] = {}
        synced = time.monotonic()
        while True:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                item = _Item("idle")
            if item.kind == "stop":
                _sync(files, close=True)
                return
            try:
                _carry_out(files, item)
            except OSError as error:
                logger.error("recorder: %s %s failed: %r", item.kind,
                             item.path, error)
            if files and time.monotonic() - synced >= SYNC_INTERVAL:
                _sync(files)
                synced = time.monotonic()


def _carry_out(files: dict[Path, IO[str]], item: _Item) -> None:
    path = item.path
    if item.kind == "mkdir" and path is not None:
        path.mkdir(parents=True, exist_ok=True)
    elif item.kind == "line" and path is not None:
        handle = files.get(path)
        if handle is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = files[path] = path.open("a", encoding="utf-8")
        handle.write(item.text + "\n")
    elif item.kind == "close" and path is not None and path in files:
        _sync({path: files.pop(path)}, close=True)
    elif item.kind == "flush":
        _sync(files)
    if item.done is not None:
        item.done.set()


def _sync(files: Mapping[Path, IO[str]], close: bool = False) -> None:
    for handle in files.values():
        handle.flush()
        os.fsync(handle.fileno())
        if close:
            handle.close()
