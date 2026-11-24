"""The weather lead rule (D-051): which archived GFS run each hour of a target day comes from.

Open-Meteo's Previous Runs API returns, for each valid hour, the value from the last run started
at or before a whole number of days earlier (`_previous_dayN`). The leakage rule is "only what
was published before the issue time", so the offset must be large enough that every hour of the
target day lands on a run already published at 06:00 Chicago on the day before.

Every hour of D+1 uses `_previous_day3`. Its newest run is the 06 UTC run of D-1, about a day
before the issue time. `_previous_day2` would leak for the target day's last hour or two, and
`_previous_day1` for every hour (tests/property/test_weather_leads.py shows both).

The target day's hourly stamps run from local midnight to the next local midnight inclusive:
instant values are stamped at their hour, and sums such as precipitation at the end of the hour
they cover, so the stamp at the closing midnight belongs to the day.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from airwatch.timeutil import ensure_utc, local_day_window_utc

__all__ = [
    "ARCHIVE_OFFSET_DAYS",
    "ARCHIVE_SUFFIX",
    "GFS_CYCLE",
    "MAX_PUBLISH_DELAY",
    "archived_run_start",
    "target_hours_utc",
]

ARCHIVE_OFFSET_DAYS = 3
ARCHIVE_SUFFIX = f"_previous_day{ARCHIVE_OFFSET_DAYS}"
GFS_CYCLE = timedelta(hours=6)
MAX_PUBLISH_DELAY = timedelta(hours=18)

_MIN_OFFSET_DAYS, _MAX_OFFSET_DAYS = 1, 7


def archived_run_start(valid: datetime, offset_days: int = ARCHIVE_OFFSET_DAYS) -> datetime:
    """The start (UTC) of the GFS run the archive returns for `valid` at `_previous_day{N}`.

    That is the last 6-hourly start at or before `offset_days` days ahead of `valid`. Raises
    ValueError for a naive datetime or an offset the API doesn't offer (1 to 7 days).
    """
    if not _MIN_OFFSET_DAYS <= offset_days <= _MAX_OFFSET_DAYS:
        raise ValueError(f"offset_days must be 1 to 7, got {offset_days}")
    cutoff = ensure_utc(valid) - timedelta(days=offset_days)
    midnight = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
    cycles = (cutoff - midnight) // GFS_CYCLE
    return midnight + cycles * GFS_CYCLE


def target_hours_utc(target: date, tz: ZoneInfo) -> list[datetime]:
    """Every hourly stamp (UTC) the target day's weather uses: midnight to midnight, both ends."""
    start, end = local_day_window_utc(target, tz)
    count = (end - start) // timedelta(hours=1)
    return [start + timedelta(hours=h) for h in range(count + 1)]
