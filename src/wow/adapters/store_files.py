"""Write files so that a crash leaves the old or the new version.

File helpers (3A, adapters/store_files; ICD IF-09, IF-10; APP-707):
the new content goes to a temporary file, is synced, then renamed over
the old one.
"""

import os
from pathlib import Path


def write_atomic(path: Path, data: bytes) -> None:
    """Replace a file's content atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
