from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC timestamp, stored consistently across SQLite and Postgres."""
    return datetime.now(UTC).replace(tzinfo=None)


def as_naive_utc(value: datetime) -> datetime:
    """Normalize API timestamps before comparing them with stored values."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
