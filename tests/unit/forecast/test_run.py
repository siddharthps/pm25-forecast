"""The persistence forecast's pure parts (#13, T6): dates, the issue-time cut, the forecast.

Rules under test (D-009 clarification, D-019, D-034):

- the forecast for D+1 is issued at 06:00 Chicago on D and uses the last complete local day, D-1;
- persistence: each monitor's forecast is its D-1 daily mean (>= 18 of 24 hours, POCs per hour);
- only rows published before the issue time are used; later rows are dropped and counted;
- a monitor without a valid D-1 is listed with its hour count, never silently left out.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from airwatch.forecast.run import (
    drop_after_issue,
    latest_target_day,
    persistence,
    plan_for,
)
from airwatch.observations.schema import concat_hourly
from tests.unit.forecast.fakes import (
    ISSUE_AT,
    OBSERVED,
    PHOENIX,
    PUBLISHED,
    SITES,
    TARGET,
    observed_day,
)
from tests.unit.validation.helpers import frame, varying

A, B = SITES


def test_the_plan_for_a_target_day() -> None:
    plan = plan_for(TARGET)
    assert plan.target_day == TARGET
    assert plan.issue_date == date(2026, 11, 20)
    assert plan.issue_at_utc == ISSUE_AT
    assert plan.observed_day == OBSERVED


def test_the_plan_follows_chicago_daylight_saving() -> None:
    assert plan_for(date(2026, 7, 2)).issue_at_utc == datetime(2026, 7, 1, 11, tzinfo=UTC)
    assert plan_for(date(2026, 1, 2)).issue_at_utc == datetime(2026, 1, 1, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "target"),
    [
        pytest.param(
            ISSUE_AT - timedelta(seconds=1), TARGET - timedelta(days=1), id="05:59:59 Chicago"
        ),
        pytest.param(ISSUE_AT, TARGET, id="06:00 exactly: today's issue is due"),
        pytest.param(ISSUE_AT + timedelta(hours=17), TARGET, id="23:00 Chicago, same day"),
        pytest.param(
            ISSUE_AT + timedelta(hours=18), TARGET, id="00:00 Chicago next day: not yet due"
        ),
    ],
)
def test_the_latest_target_is_the_last_one_already_due(now: datetime, target: date) -> None:
    assert latest_target_day(now) == target


def test_a_naive_now_is_refused() -> None:
    with pytest.raises(ValueError, match="time zone"):
        latest_target_day(datetime(2026, 11, 20, 12))  # noqa: DTZ001


def test_rows_published_after_the_issue_time_are_dropped_and_counted() -> None:
    on_time = observed_day()
    late = observed_day(available_at=ISSUE_AT + timedelta(seconds=1)).iloc[:3]
    kept, dropped = drop_after_issue(concat_hourly([on_time, late]), ISSUE_AT)
    assert dropped == 3
    assert len(kept) == len(on_time)


def test_a_row_published_exactly_at_the_issue_time_is_kept() -> None:
    kept, dropped = drop_after_issue(observed_day(available_at=ISSUE_AT), ISSUE_AT)
    assert dropped == 0
    assert len(kept) == 48


def test_persistence_is_the_observed_daily_mean() -> None:
    df = observed_day()
    forecasts, missing = persistence(df, OBSERVED, PHOENIX, SITES)
    expected = df.groupby("site_id")["value_ug_m3"].mean()
    assert [f["site_id"] for f in forecasts] == [A, B]
    for f in forecasts:
        assert f["forecast_ug_m3"] == pytest.approx(expected[f["site_id"]])
        assert f["n_hours"] == 24
    assert missing == []


@pytest.mark.parametrize(("hours", "valid"), [(18, True), (17, False)])
def test_a_monitor_needs_18_hours(hours: int, valid: bool) -> None:
    forecasts, missing = persistence(observed_day({B: hours}), OBSERVED, PHOENIX, SITES)
    assert (B in [f["site_id"] for f in forecasts]) is valid
    assert missing == ([] if valid else [{"site_id": B, "n_hours": 17}])


def test_a_monitor_with_no_rows_is_listed_with_zero_hours() -> None:
    df = observed_day()
    forecasts, missing = persistence(df[df["site_id"] == A], OBSERVED, PHOENIX, SITES)
    assert [f["site_id"] for f in forecasts] == [A]
    assert missing == [{"site_id": B, "n_hours": 0}]


def test_co_located_instruments_are_averaged_per_hour_first() -> None:
    start = ISSUE_AT - timedelta(hours=29)
    one = frame([10.0] * 24, site=A, poc=1, start=start, available_at=PUBLISHED)
    two = frame([20.0] * 12, site=A, poc=2, start=start, available_at=PUBLISHED)
    forecasts, _ = persistence(concat_hourly([one, two]), OBSERVED, PHOENIX, (A,))
    assert forecasts[0]["forecast_ug_m3"] == pytest.approx(12.5), (
        "12 hours average to 15, 12 are 10: (12*15 + 12*10) / 24, not pooled rows"
    )


def test_rows_from_other_days_never_enter_the_forecast() -> None:
    start = ISSUE_AT - timedelta(hours=29)
    today = frame(
        [500.0] * 6,
        site=A,
        start=start + timedelta(days=1),
        available_at=ISSUE_AT + timedelta(hours=1),
    )
    df = concat_hourly([observed_day(), today])
    with_today, _ = persistence(df, OBSERVED, PHOENIX, SITES)
    without, _ = persistence(observed_day(), OBSERVED, PHOENIX, SITES)
    assert with_today == without


def test_values_are_never_rounded_in_the_record() -> None:
    df = frame(varying(24, base=8.123456), site=A, start=ISSUE_AT - timedelta(hours=29))
    forecasts, _ = persistence(df, OBSERVED, PHOENIX, (A,))
    assert forecasts[0]["forecast_ug_m3"] == pytest.approx(df["value_ug_m3"].mean(), abs=1e-12)


def test_another_full_day_in_the_input_never_replaces_the_observed_day() -> None:
    older = observed_day(day=OBSERVED - timedelta(days=1), base={A: 300.0, B: 300.0})
    newer = observed_day(
        day=OBSERVED + timedelta(days=1),
        base={A: 300.0, B: 300.0},
        available_at=ISSUE_AT + timedelta(days=2),
    )
    df = concat_hourly([older, observed_day(), newer])
    forecasts, _ = persistence(df, OBSERVED, PHOENIX, SITES)
    without, _ = persistence(observed_day(), OBSERVED, PHOENIX, SITES)
    assert forecasts == without
