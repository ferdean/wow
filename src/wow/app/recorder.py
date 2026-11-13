"""Write the ride files and Bluetooth logs.

Writes the ride journal, the samples and the Bluetooth logs as JSON Lines
from a worker thread, so disk writes never stall the event loop (AD-06;
ICD IF-09, IF-11; APP-808). Lines are synced at most every 2 s and at
every pause, dropout and finish; whole files such as `meta.json` and
`ride.fit` are replaced atomically by the same thread.
"""

import json
import logging
import os
import queue
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import IO, Final

from wow.adapters.ble_log import BleLogRecord, record_line
from wow.adapters.store_files import write_atomic

logger = logging.getLogger(__name__)

SYNC_INTERVAL: Final[float] = 2.0
JOURNAL: Final[str] = "events.jsonl"
SAMPLES: Final[str] = "samples.jsonl"
BLE_LOG: Final[str] = "ble.jsonl"
RIDE_LINES: Final[tuple[str, ...]] = (JOURNAL, SAMPLES, BLE_LOG)
SYNC_EVENTS: Final[frozenset[str]] = frozenset(
    {"paused", "dropout_start", "dropout_end", "finished", "discarded"})


class _Kind(Enum):
    MKDIR = auto()
    LINE = auto()
    CLOSE = auto()
    FLUSH = auto()
    SYNC = auto()
    JOB = auto()
    STOP = auto()
    IDLE = auto()


@dataclass(frozen=True)
class _Item:
    kind: _Kind
    path: Path | None = None
    text: str = ""
    done: threading.Event | None = None
    job: Callable[[], None] | None = None


class Recorder:
    """Writes JSON Lines and ride files from a worker thread."""

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
        self._queue.put(_Item(_Kind.STOP))
        self._thread.join(timeout=30.0)

    def open_ride(self, ride_id: str) -> Path:
        """Create the directory and files of a ride."""
        self._ride = self._data / "rides" / ride_id
        self._queue.put(_Item(_Kind.MKDIR, self._ride))
        return self._ride

    def close_ride(self, ride: Path) -> None:
        """Close the files of a ride."""
        if self._ride == ride:
            self._ride = None
        for name in RIDE_LINES:
            self._queue.put(_Item(_Kind.CLOSE, ride / name))

    def journal(self, record: Mapping[str, object]) -> None:
        """Queue a journal record."""
        if self._ride is None:
            logger.warning("journal record outside a ride: %s", record)
            return
        self._queue.put(_Item(_Kind.LINE, self._ride / JOURNAL,
                              json.dumps(dict(record))))
        if record.get("type") in SYNC_EVENTS:
            self._queue.put(_Item(_Kind.SYNC))

    def sample(self, record: Mapping[str, object]) -> None:
        """Queue a sample line."""
        if self._ride is not None:
            self._queue.put(_Item(_Kind.LINE, self._ride / SAMPLES,
                                  json.dumps(dict(record))))

    def ble(self, record: BleLogRecord) -> None:
        """Queue a Bluetooth log record."""
        target = (self._data / "logs" / "ble-system.jsonl"
                  if self._ride is None else self._ride / BLE_LOG)
        self._queue.put(_Item(_Kind.LINE, target, record_line(record)))

    def write_file(self, path: Path, data: bytes) -> None:
        """Queue an atomic replacement of a whole file."""
        self.run(lambda: write_atomic(path, data))

    def run(self, job: Callable[[], None]) -> None:
        """Queue work for the worker thread, after everything queued."""
        self._queue.put(_Item(_Kind.JOB, job=job))

    def flush(self) -> None:
        """Wait until everything queued is written."""
        done = threading.Event()
        self._queue.put(_Item(_Kind.FLUSH, done=done))
        done.wait(timeout=30.0)

    def _work(self) -> None:
        files: dict[Path, IO[str]] = {}
        synced = time.monotonic()
        while True:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                item = _Item(_Kind.IDLE)
            if item.kind == _Kind.STOP:
                _sync(files, close=True)
                return
            try:
                _carry_out(files, item)
            except Exception as error:
                logger.error("recorder: %s %s failed: %r",
                             item.kind.name.lower(), item.path, error)
            if files and time.monotonic() - synced >= SYNC_INTERVAL:
                _sync(files)
                synced = time.monotonic()


def _carry_out(files: dict[Path, IO[str]], item: _Item) -> None:
    path = item.path
    if item.kind == _Kind.MKDIR and path is not None:
        path.mkdir(parents=True, exist_ok=True)
    elif item.kind == _Kind.LINE and path is not None:
        handle = files.get(path)
        if handle is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = files[path] = path.open("a", encoding="utf-8")
        handle.write(item.text + "\n")
    elif item.kind == _Kind.CLOSE and path is not None and path in files:
        _sync({path: files.pop(path)}, close=True)
    elif item.kind in (_Kind.FLUSH, _Kind.SYNC):
        _sync(files)
    elif item.kind == _Kind.JOB and item.job is not None:
        _sync(files)
        item.job()
    if item.done is not None:
        item.done.set()


def _sync(files: Mapping[Path, IO[str]], close: bool = False) -> None:
    for handle in files.values():
        handle.flush()
        os.fsync(handle.fileno())
        if close:
            handle.close()
