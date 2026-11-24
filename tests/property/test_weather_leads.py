"""The weather lead rule (#19, T14; D-051): every archived forecast hour was published in time.

The leakage rule is "only what was published before the issue time". The Previous Runs archive
counts back from each valid hour instead, so these tests check the rule as published-before,
against a reference that picks the run by stepping through GFS's real start times (00, 06, 12
and 18 UTC), not by the module's own arithmetic.
"""

from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from airwatch.timeutil import issue_time_utc
from airwatch.weather.leads import (
    ARCHIVE_OFFSET_DAYS,
    ARCHIVE_SUFFIX,
    MAX_PUBLISH_DELAY,
    archived_run_start,
    target_hours_utc,
)

PHOENIX = ZoneInfo("America/Phoenix")
GFS_START_HOURS = (0, 6, 12, 18)
OBSERVED_GFS_DELAY = timedelta(hours=6, minutes=18)

days = st.dates(min_value=date(2009, 1, 1), max_value=date(2030, 12, 31))


def _reference_run_start(valid: datetime, offset_days: int) -> datetime:
    """The last GFS start at or before `offset_days` whole days ahead of `valid`, by stepping."""
    cutoff = valid - timedelta(days=offset_days)
    day = cutoff.date() - timedelta(days=1)
    starts = [
        datetime(d.year, d.month, d.day, h, tzinfo=UTC)
        for d in (day, day + timedelta(days=1))
        for h in GFS_START_HOURS
    ]
    return max(s for s in starts if s <= cutoff)


def _us_dst_start(year: int) -> date:
    first = date(year, 3, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7)


def _us_dst_end(year: int) -> date:
    first = date(year, 11, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7)


def test_the_rule_is_three_days_back() -> None:
    assert ARCHIVE_OFFSET_DAYS == 3
    assert ARCHIVE_SUFFIX == "_previous_day3"


@given(target=days)
@example(target=_us_dst_start(2025))
@example(target=_us_dst_start(2025) + timedelta(days=1))
@example(target=_us_dst_end(2025))
@example(target=_us_dst_end(2025) + timedelta(days=1))
@example(target=date(2025, 1, 15))
@example(target=date(2025, 7, 15))
def test_every_hour_uses_a_run_published_before_the_issue_time(target: date) -> None:
    issued = issue_time_utc(target)
    for valid in target_hours_utc(target, PHOENIX):
        run = archived_run_start(valid)
        assert run == _reference_run_start(valid, ARCHIVE_OFFSET_DAYS), valid
        assert run + MAX_PUBLISH_DELAY <= issued, (valid, run, issued)


@given(target=days)
def test_target_hours_cover_the_local_day_and_the_hour_that_ends_it(target: date) -> None:
    hours = target_hours_utc(target, PHOENIX)
    local_midnight = datetime(target.year, target.month, target.day, tzinfo=PHOENIX)
    assert hours[0] == local_midnight.astimezone(UTC)
    assert hours[-1] == (local_midnight + timedelta(days=1)).astimezone(UTC)
    assert len(hours) == 25
    assert all(b - a == timedelta(hours=1) for a, b in pairwise(hours))
    assert all(h.tzinfo is UTC for h in hours)


def test_the_assumed_delay_covers_the_one_observed() -> None:
    assert MAX_PUBLISH_DELAY >= 2 * OBSERVED_GFS_DELAY


@pytest.mark.parametrize(
    ("target", "season"), [(date(2025, 1, 15), "CST"), (date(2025, 7, 15), "CDT")]
)
def test_two_days_back_would_leak_at_the_end_of_the_day(target: date, season: str) -> None:
    """Why not 48 h: tomorrow's last stamps land on the 06 UTC run of the issue day, which
    appears about 12:17 UTC, after the issue time in both seasons."""
    issued = issue_time_utc(target)
    late = [
        valid
        for valid in target_hours_utc(target, PHOENIX)
        if archived_run_start(valid, offset_days=2) + OBSERVED_GFS_DELAY > issued
    ]
    assert [v.hour for v in late] == [6, 7], season


def test_one_day_back_would_leak_for_every_hour() -> None:
    target = date(2025, 1, 15)
    issued = issue_time_utc(target)
    hours = target_hours_utc(target, PHOENIX)
    assert all(archived_run_start(v, offset_days=1) + OBSERVED_GFS_DELAY > issued for v in hours)


def test_known_values() -> None:
    """Hand-checked: Phoenix's 2025-01-15 runs 07:00 UTC on the 15th to 07:00 UTC on the 16th."""
    assert archived_run_start(datetime(2025, 1, 15, 7, tzinfo=UTC)) == datetime(
        2025, 1, 12, 6, tzinfo=UTC
    )
    assert archived_run_start(datetime(2025, 1, 16, 6, tzinfo=UTC)) == datetime(
        2025, 1, 13, 6, tzinfo=UTC
    )
    assert archived_run_start(datetime(2025, 1, 16, 7, tzinfo=UTC)) == datetime(
        2025, 1, 13, 6, tzinfo=UTC
    )
    assert archived_run_start(datetime(2025, 1, 16, 5, 59, tzinfo=UTC)) == datetime(
        2025, 1, 13, 0, tzinfo=UTC
    ), "a minute before a start rounds down to the start before"


def test_rejects_a_naive_datetime() -> None:
    with pytest.raises(ValueError, match="naive datetime rejected"):
        archived_run_start(datetime(2025, 1, 15, 7))  # noqa: DTZ001


def test_rejects_an_offset_below_one_day() -> None:
    with pytest.raises(ValueError, match="offset_days must be 1 to 7"):
        archived_run_start(datetime(2025, 1, 15, 7, tzinfo=UTC), offset_days=0)


def test_rejects_a_datetime_as_the_target_day() -> None:
    with pytest.raises(TypeError, match="expected a date"):
        target_hours_utc(datetime(2025, 1, 15, tzinfo=UTC), PHOENIX)
