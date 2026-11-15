"""Write files so that a crash leaves the old or the new version.

File helpers (3A, adapters/store_files; ICD IF-09, IF-10; APP-707):
the new content goes to a temporary file, is synced, then renamed over
the old one.
"""

import os
from pathlib import Path


def write_atomic(path: Path, data: bytes, mode: int | None = None) -> None:
    """Replace a file's content atomically; with mode, set its mode first.

    The mode is set on the temporary file before any byte is written, so
    the content is never readable with wider permissions.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(temporary, flags, 0o666 if mode is None else mode)
    with os.fdopen(descriptor, "wb") as handle:
        if mode is not None:
            os.fchmod(handle.fileno(), mode)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
