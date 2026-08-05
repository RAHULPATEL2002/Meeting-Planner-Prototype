"""Helpers for the one timezone rule this codebase has.

**Rule:** everything is stored as *naive UTC*. Timezone-aware input is converted
to UTC and stripped; naive input is assumed to already be UTC. Output re-attaches
UTC so clients always receive an unambiguous ``...Z`` timestamp.

SQLite cannot store an offset, so pretending otherwise would silently corrupt
data the first time a user in a non-UTC zone created a meeting.
"""

from __future__ import annotations

from datetime import UTC, datetime


def to_utc_naive(value: datetime) -> datetime:
    """Normalise any datetime to the naive-UTC representation used in the DB."""
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    # Second precision is plenty for a calendar and keeps assertions readable.
    return value.replace(microsecond=0)


def as_utc(value: datetime) -> datetime:
    """Re-attach UTC to a naive datetime read back from the database."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utcnow() -> datetime:
    """Current time in the naive-UTC representation used in the DB."""
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def overlap_minutes(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> int:
    """Minutes shared by two half-open intervals ``[start, end)``.

    Half-open matters: a meeting ending at 10:00 and one starting at 10:00 are
    back-to-back, not a conflict.
    """
    latest_start = max(a_start, b_start)
    earliest_end = min(a_end, b_end)
    delta = (earliest_end - latest_start).total_seconds()
    return int(delta // 60) if delta > 0 else 0
