"""Time rules: the single home for issue time, local-day boundaries and UTC conversion.

Rules (SPEC § Key definitions; D-019, frozen):

- Every timestamp is timezone-aware and stored in UTC. A local zone is applied only for display
  and for day boundaries. Naive datetimes are rejected, never guessed at.
- The forecast for target day D+1 is issued at 06:00 America/Chicago on day D.
- A local calendar day is the half-open UTC interval [start, end) of the instants whose local
  date is that day: 23, 24 or 25 hours long.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

__all__ = [
    "ISSUE_HOUR_LOCAL",
    "ISSUE_TZ",
    "UTC",
    "ensure_utc",
    "issue_time_utc",
    "local_day_window_utc",
    "to_local",
]

# D-019 (frozen). Deliberately constants, not settings: changing them changes every result.
ISSUE_TZ = ZoneInfo("America/Chicago")
ISSUE_HOUR_LOCAL = 6


def _require_aware(dt: datetime) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"naive datetime rejected: {dt.isoformat()} has no time zone")


def _require_date(day: date) -> None:
    # datetime subclasses date, so a datetime would otherwise slip through silently.
    if isinstance(day, datetime) or not isinstance(day, date):
        raise TypeError(f"expected a date, got {type(day).__name__}")


def ensure_utc(dt: datetime) -> datetime:
    """Return the same instant in UTC. Raises ValueError for a naive datetime."""
    _require_aware(dt)
    return dt.astimezone(UTC)


def to_local(dt: datetime, tz: ZoneInfo) -> datetime:
    """Return the same instant on `tz`'s wall clock. Raises ValueError for a naive datetime."""
    _require_aware(dt)
    return dt.astimezone(tz)


def _local_midnight_utc(day: date, tz: ZoneInfo) -> datetime:
    """The first instant of `day` in `tz`, in UTC.

    Correct for US zones, where DST changes at 02:00 and midnight is always a single, existing
    wall-clock time. (Zones that change at midnight are out of scope; the property tests cover
    the D-006 candidate zones.)
    """
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


def local_day_window_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Return the half-open UTC window [start, end) of the local calendar day `day` in `tz`."""
    _require_date(day)
    return _local_midnight_utc(day, tz), _local_midnight_utc(day + timedelta(days=1), tz)


def issue_time_utc(target_day: date) -> datetime:
    """Return the UTC instant at which the forecast for `target_day` (D+1) is issued.

    That is 06:00 America/Chicago on the day before. 06:00 is never skipped or repeated by a US
    DST change (those happen at 02:00), so the instant is always unique.
    """
    _require_date(target_day)
    issue_day = target_day - timedelta(days=1)
    return datetime.combine(issue_day, time(ISSUE_HOUR_LOCAL), tzinfo=ISSUE_TZ).astimezone(UTC)
