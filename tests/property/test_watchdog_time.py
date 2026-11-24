"""The watchdog checks the same day the forecast writes (#16, T9; D-019 frozen, D-041).

Its own `target_day` (it can't import airwatch) must equal `latest_target_day` for any moment at or
after the 06:00 Chicago issue time, DST days included, and refuse any moment before it.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from airwatch.forecast.run import latest_target_day
from airwatch.watchdog import handler as wd
from tests.process_zone import CAN_MOVE_ZONE, SKIP_REASON, process_zone

CHICAGO = ZoneInfo("America/Chicago")
days = st.dates(min_value=date(2026, 1, 1), max_value=date(2040, 12, 31))
ZONES = ("UTC", "America/Chicago", "Asia/Tokyo", "Pacific/Kiritimati")
after_issue = st.integers(min_value=6 * 3600, max_value=24 * 3600 - 1)
before_issue = st.integers(min_value=0, max_value=6 * 3600 - 1)


def _utc(day: date, seconds: int) -> datetime:
    local = datetime.combine(day, time(), tzinfo=CHICAGO) + timedelta(seconds=seconds)
    return datetime.fromtimestamp(local.timestamp(), tz=UTC)


@given(days, after_issue)
@example(date(2026, 3, 8), 8 * 3600)
@example(date(2026, 11, 1), 9 * 3600)
@example(date(2026, 12, 31), 8 * 3600)
def test_the_target_day_matches_the_forecasts(day: date, seconds: int) -> None:
    at = _utc(day, seconds)
    assert wd.target_day(at) == latest_target_day(at) == day + timedelta(days=1)


@given(days, before_issue)
def test_a_moment_before_the_issue_time_is_refused(day: date, seconds: int) -> None:
    with pytest.raises(wd.WatchdogError, match="before"):
        wd.target_day(_utc(day, seconds))


@given(days, st.sampled_from([8, 9]))
def test_the_schedules_hours_exist_every_day(day: date, hour: int) -> None:
    """08:00 and 09:00 are never skipped or doubled by a DST change (those happen at 02:00)."""
    local = datetime.combine(day, time(hour), tzinfo=CHICAGO)
    back = datetime.fromtimestamp(local.timestamp(), tz=UTC).astimezone(CHICAGO)
    assert (back.date(), back.hour, back.minute) == (day, hour, 0)
    assert wd.target_day(back) == day + timedelta(days=1)


@pytest.mark.skipif(not CAN_MOVE_ZONE, reason=SKIP_REASON)
@given(days, st.integers(min_value=0, max_value=24 * 3600 - 1), st.sampled_from(ZONES))
@example(date(2026, 3, 9), 8 * 3600, "UTC")
@example(date(2026, 11, 2), 8 * 3600, "Asia/Tokyo")
def test_the_lock_day_is_a_chicago_monday_whatever_the_process_zone(
    day: date, seconds: int, zone: str
) -> None:
    """#113: DST and the process zone can't move "Monday" off the Chicago calendar."""
    at = _utc(day, seconds)
    with process_zone(zone):
        got = wd.lock_day(at)
    assert got == (day if day.weekday() == 0 else None)
