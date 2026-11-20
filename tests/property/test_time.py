"""Time rules (#7, T3; D-019 frozen): issue time, local-day windows, and no naive datetimes.

Every check compares against a reference built a different way (stepping through UTC hours, or
the US DST law), not against a copy of the implementation.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from airwatch.timeutil import (
    ISSUE_HOUR_LOCAL,
    ISSUE_TZ,
    ensure_utc,
    issue_time_utc,
    local_day_window_utc,
    to_local,
)

CHICAGO = ZoneInfo("America/Chicago")
CANDIDATE_TZS = [CHICAGO, ZoneInfo("America/Denver"), ZoneInfo("America/Los_Angeles")]
PHOENIX = ZoneInfo("America/Phoenix")
ALL_TZS = [*CANDIDATE_TZS, PHOENIX]

FIRST, LAST = date(2009, 1, 1), date(2030, 12, 31)
days = st.dates(min_value=FIRST, max_value=LAST)
zones = st.sampled_from(ALL_TZS)


def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    first_sunday = first + timedelta(days=(6 - first.weekday()) % 7)
    return first_sunday + timedelta(weeks=n - 1)


def _us_dst_start(year: int) -> date:
    return _nth_sunday(year, 3, 2)


def _us_dst_end(year: int) -> date:
    return _nth_sunday(year, 11, 1)


def _utc_hours_in_local_day(day: date, tz: ZoneInfo) -> list[datetime]:
    """Reference: step through whole UTC hours and keep those whose local date is `day`."""
    start = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(days=1)
    hours = (start + timedelta(hours=h) for h in range(72))
    return [t for t in hours if t.astimezone(tz).date() == day]


DST_EXAMPLES = [
    _us_dst_start(2009),
    _us_dst_end(2009),
    _us_dst_start(2025),
    _us_dst_end(2025),
    _us_dst_start(2030),
    _us_dst_end(2030),
]


@given(target=days)
@example(target=_us_dst_start(2025))
@example(target=_us_dst_start(2025) + timedelta(days=1))
@example(target=_us_dst_end(2025))
@example(target=_us_dst_end(2025) + timedelta(days=1))
def test_issue_time_is_six_local_on_the_day_before(target: date) -> None:
    """The reference: the one whole UTC hour whose Chicago reading is 06:00 the day before."""
    issued = issue_time_utc(target)
    day_before = target - timedelta(days=1)
    matches = [
        t
        for t in _utc_hours_in_local_day(day_before, CHICAGO)
        if t.astimezone(CHICAGO).hour == ISSUE_HOUR_LOCAL
    ]
    assert matches == [issued]
    assert issued.tzinfo is UTC


def test_issue_rule_is_the_frozen_one() -> None:
    assert ISSUE_TZ == CHICAGO
    assert ISSUE_HOUR_LOCAL == 6


def test_issue_time_known_values() -> None:
    """Hand-checked anchors: CST is UTC-6, CDT is UTC-5."""
    assert issue_time_utc(date(2025, 1, 16)) == datetime(2025, 1, 15, 12, tzinfo=UTC), "CST"
    assert issue_time_utc(date(2025, 7, 5)) == datetime(2025, 7, 4, 11, tzinfo=UTC), "CDT"
    assert issue_time_utc(date(2025, 3, 10)) == datetime(2025, 3, 9, 11, tzinfo=UTC), (
        "DST starts 2025-03-09 at 02:00, so 06:00 that morning is already CDT"
    )
    assert issue_time_utc(date(2025, 11, 3)) == datetime(2025, 11, 2, 12, tzinfo=UTC), (
        "DST ends 2025-11-02 at 02:00, so 06:00 that morning is already CST"
    )


def test_issue_time_rejects_a_datetime() -> None:
    with pytest.raises(TypeError):
        issue_time_utc(datetime(2025, 1, 16, tzinfo=UTC))


@given(day=days, tz=zones)
def test_local_day_window_matches_the_reference(day: date, tz: ZoneInfo) -> None:
    start, end = local_day_window_utc(day, tz)
    hours = _utc_hours_in_local_day(day, tz)
    assert start == hours[0]
    assert end == hours[-1] + timedelta(hours=1)
    assert start.tzinfo is UTC
    assert end.tzinfo is UTC


@given(day=days, tz=zones)
def test_consecutive_local_days_tile_time(day: date, tz: ZoneInfo) -> None:
    assert local_day_window_utc(day, tz)[1] == local_day_window_utc(day + timedelta(days=1), tz)[0]


@pytest.mark.parametrize("tz", ALL_TZS, ids=str)
def test_day_length_is_23_24_or_25_hours_exactly_on_dst_dates(tz: ZoneInfo) -> None:
    """Exhaustive over 2009-2030 (about 8,000 days per zone), against the US DST law."""
    starts = {_us_dst_start(y) for y in range(FIRST.year, LAST.year + 1)}
    ends = {_us_dst_end(y) for y in range(FIRST.year, LAST.year + 1)}
    observes_dst = tz != PHOENIX
    day = FIRST
    while day <= LAST:
        start, end = local_day_window_utc(day, tz)
        hours = (end - start) / timedelta(hours=1)
        if observes_dst and day in starts:
            assert hours == 23, day
        elif observes_dst and day in ends:
            assert hours == 25, day
        else:
            assert hours == 24, day
        day += timedelta(days=1)


def test_local_day_window_rejects_a_datetime() -> None:
    with pytest.raises(TypeError):
        local_day_window_utc(datetime(2025, 1, 16, tzinfo=UTC), CHICAGO)


LO = datetime(2009, 1, 1)  # noqa: DTZ001
HI = datetime(2030, 12, 31)  # noqa: DTZ001
naive = st.datetimes(min_value=LO, max_value=HI)
aware = st.datetimes(
    min_value=LO,
    max_value=HI,
    timezones=st.sampled_from([UTC, *ALL_TZS]),
)


@given(dt=naive)
def test_ensure_utc_rejects_naive(dt: datetime) -> None:
    with pytest.raises(ValueError, match="naive"):
        ensure_utc(dt)


@given(dt=naive, tz=zones)
def test_to_local_rejects_naive(dt: datetime, tz: ZoneInfo) -> None:
    with pytest.raises(ValueError, match="naive"):
        to_local(dt, tz)


@given(dt=aware)
@example(dt=datetime(2025, 11, 2, 1, 30, fold=1, tzinfo=CHICAGO))
def test_ensure_utc_keeps_the_instant(dt: datetime) -> None:
    """The pinned example is the repeated hour's second pass, when DST ends."""
    out = ensure_utc(dt)
    assert out.tzinfo is UTC
    assert out.timestamp() == dt.timestamp()


@given(dt=aware, tz=zones)
def test_to_local_round_trips(dt: datetime, tz: ZoneInfo) -> None:
    local = to_local(dt, tz)
    assert local.tzinfo is tz
    assert ensure_utc(local) == ensure_utc(dt)


@pytest.mark.parametrize("day", DST_EXAMPLES, ids=str)
def test_dst_days_are_in_range(day: date) -> None:
    assert FIRST <= day <= LAST, "guards the guards: a DST example outside the range"
    assert day.weekday() == 6
