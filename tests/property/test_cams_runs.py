"""CAMS run rules (#19, T14; D-052): the as-issued run was out by the issue time, every day.

"As issued" is the run started at 00 UTC on the issue day. These tests check it as "the newest run
published before the issue time, given the observed delay", against a reference that steps
through CAMS's real start times (00 and 12 UTC), not the module's own arithmetic. They also check
that the run reaches the end of the target day, and how the stitched history maps each hour to a
run.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from airwatch.timeutil import issue_time_utc, local_day_window_utc
from airwatch.weather.cams import (
    CYCLE,
    PUBLISH_DELAY,
    RUN_LENGTH,
    STITCHED_LEADS,
    issued_run_start,
    stitched_run_start,
)

PHOENIX = ZoneInfo("America/Phoenix")
CAMS_START_HOURS = (0, 12)
OBSERVED_CAMS_DELAYS = (timedelta(hours=9, minutes=48), timedelta(hours=9, minutes=55))
WINTER, SUMMER = date(2026, 12, 2), date(2026, 7, 2)

days = st.dates(min_value=date(2022, 8, 5), max_value=date(2030, 12, 31))
LO = datetime(2022, 8, 4)  # noqa: DTZ001
HI = datetime(2030, 12, 31)  # noqa: DTZ001
instants = st.datetimes(min_value=LO, max_value=HI, timezones=st.just(UTC))


def _reference_issued_run(target: date, delay: timedelta) -> datetime:
    """The newest CAMS start published by the issue time, by stepping through two days of starts."""
    issue = issue_time_utc(target)
    starts = [
        datetime(d.year, d.month, d.day, h, tzinfo=UTC)
        for d in (issue.date() - timedelta(days=1), issue.date())
        for h in CAMS_START_HOURS
    ]
    return max(s for s in starts if s + delay <= issue)


@given(days)
@example(WINTER)
@example(SUMMER)
def test_the_issued_run_is_the_newest_one_out_by_the_issue_time(target: date) -> None:
    for delay in (PUBLISH_DELAY, *OBSERVED_CAMS_DELAYS):
        assert issued_run_start(target) == _reference_issued_run(target, delay)


@given(days)
def test_the_issued_run_was_out_at_least_an_hour_before_the_issue_time(target: date) -> None:
    assert issue_time_utc(target) - (issued_run_start(target) + PUBLISH_DELAY) >= timedelta(hours=1)


@given(days)
def test_the_issued_run_covers_every_hour_of_the_target_day(target: date) -> None:
    start, end = local_day_window_utc(target, PHOENIX)
    run = issued_run_start(target)
    assert run <= start
    assert end - timedelta(hours=1) <= run + RUN_LENGTH


@given(instants)
@example(datetime(2026, 11, 20, 11, 59, tzinfo=UTC))
@example(datetime(2026, 11, 20, 12, tzinfo=UTC))
def test_a_stitched_hour_comes_from_the_last_run_started_at_or_before_it(valid: datetime) -> None:
    run = stitched_run_start(valid)
    assert run.hour in CAMS_START_HOURS
    assert (run.minute, run.second, run.microsecond) == (0, 0, 0)
    assert run <= valid < run + STITCHED_LEADS
    assert STITCHED_LEADS == CYCLE


@pytest.mark.parametrize(
    ("target", "issue_utc", "run"),
    [
        (WINTER, datetime(2026, 12, 1, 12, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC)),
        (SUMMER, datetime(2026, 7, 1, 11, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)),
    ],
    ids=["winter", "summer"],
)
def test_the_worked_examples_in_d052(target: date, issue_utc: datetime, run: datetime) -> None:
    assert issue_time_utc(target) == issue_utc
    assert issued_run_start(target) == run


def test_the_day_before_noon_run_would_be_staler_and_the_next_one_late() -> None:
    issue = issue_time_utc(SUMMER)
    run = issued_run_start(SUMMER)
    assert run + CYCLE + min(OBSERVED_CAMS_DELAYS) > issue
    assert run - CYCLE + PUBLISH_DELAY < run + PUBLISH_DELAY <= issue


def test_naive_times_are_refused() -> None:
    with pytest.raises(ValueError, match="naive datetime rejected"):
        stitched_run_start(datetime(2026, 11, 20, 5))  # noqa: DTZ001
