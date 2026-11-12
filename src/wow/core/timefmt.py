"""Format UTC stamps for outputs.

UTC stamps for outputs (AD-08: UTC appears only in outputs).
"""

from datetime import UTC, datetime


def utc_text(moment: datetime) -> str:
    """Return a moment as UTC text."""
    stamp = moment.astimezone(UTC).isoformat(timespec="milliseconds")
    return stamp.replace("+00:00", "Z")
