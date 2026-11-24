"""The CAMS archive gap (#19, T14; D-052): as issued against stitched, each against observed.

Fakes stand in for the Single Runs API (a run's rows), the stitched history (rows from the bulk
download) and AirNow (a day of hours, through the real validation and daily-mean path). The
numbers are chosen so each figure can be worked out by hand.
"""

import math
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from airwatch.weather import cams
from airwatch.weather.cams import CamsSource, issued_run_start
from airwatch.weather.cams_gap import (
    FIRST_TARGET,
    SKIP_REASONS,
    measure,
    observed_means,
    summarise,
    target_days,
)
from tests.unit.forecast.fakes import PHOENIX, SITES, observed_day

A, B = SITES
DAY = date(2026, 6, 10)
OBS_OFFSET = 32.2 / 24
OBSERVED_BASE = {A: 8.0, B: 2.0}


def cams_rows(
    site: str, first: datetime, hours: int, value: float, source: CamsSource
) -> pd.DataFrame:
    stamps = [first + timedelta(hours=h) for h in range(hours)]
    return pd.DataFrame(
        {
            "site_id": site,
            "valid_utc": pd.to_datetime(stamps, utc=True),
            cams.VARIABLE: value,
            "source": source.value,
            "run_start_utc": pd.Timestamp(first),
            "available_at_utc": pd.Timestamp(first + cams.PUBLISH_DELAY),
        },
        columns=list(cams.COLUMNS),
    )


class FakeRuns:
    """Runs of constant values; `empty` runs have no values, `short` ones stop at 40 hours."""

    def __init__(
        self,
        values: dict[str, float],
        empty: set[tuple[str, datetime]] | None = None,
        short: set[tuple[str, datetime]] | None = None,
    ) -> None:
        self.values, self.empty, self.short = values, empty or set(), short or set()
        self.calls: list[tuple[str, datetime]] = []

    def __call__(self, site: str, run: datetime) -> pd.DataFrame:
        self.calls.append((site, run))
        hours = 40 if (site, run) in self.short else 168
        df = cams_rows(site, run, hours, self.values[site], CamsSource.RUN)
        if (site, run) in self.empty:
            df[cams.VARIABLE] = math.nan
        return df


def stitched(values: dict[str, float], days: list[date]) -> pd.DataFrame:
    first = datetime.combine(min(days) - timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    span = (max(days) - min(days)).days + 3
    return pd.concat(
        [cams_rows(s, first, span * 24, v, CamsSource.HISTORY) for s, v in values.items()]
    )


def airnow(days: list[date], hours: dict[str, int] | None = None) -> Any:
    def fetch_day(day: date) -> tuple[pd.DataFrame, dict[str, int]]:
        assert day in days
        return observed_day(hours, base=OBSERVED_BASE, day=day), {}

    return fetch_day


def test_the_first_target_is_the_day_after_the_first_kept_run() -> None:
    assert datetime(2026, 4, 2, tzinfo=UTC) == cams.FIRST_RUN
    assert issued_run_start(FIRST_TARGET) == cams.FIRST_RUN
    assert date(2026, 4, 3) == FIRST_TARGET


def test_target_days_run_to_two_days_ago() -> None:
    days = target_days(date(2026, 4, 7))
    assert days == [date(2026, 4, 3), date(2026, 4, 4), date(2026, 4, 5)]


def test_the_summary_by_hand() -> None:
    pairs = pd.DataFrame(
        {
            "site_id": [A, B],
            "day": [DAY, DAY],
            "as_issued": [10.0, 4.0],
            "stitched": [8.0, 6.0],
            "observed": [9.0, 2.0],
        }
    )
    summary = summarise(pairs, Counter({"no_observed": 3}))
    assert summary["monitor_days"] == 2
    assert summary["mae_as_issued"] == pytest.approx(1.5)
    assert summary["mae_stitched"] == pytest.approx(2.5)
    assert summary["mae_difference"] == pytest.approx(-1.0)
    assert summary["mean_abs_cams_difference"] == pytest.approx(2.0)
    assert summary["skipped"] == {
        reason: 3 if reason == "no_observed" else 0 for reason in SKIP_REASONS
    }
    assert (summary["first_day"], summary["last_day"]) == ("2026-06-10", "2026-06-10")


def test_an_empty_summary_has_no_figures() -> None:
    summary = summarise(
        pd.DataFrame(columns=["site_id", "day", "as_issued", "stitched", "observed"]), Counter()
    )
    assert summary["monitor_days"] == 0
    assert summary["mae_as_issued"] is None


def test_observed_means_follow_the_scoring_path() -> None:
    means = observed_means(airnow([DAY]), DAY, PHOENIX, SITES)
    assert means == pytest.approx({A: 8.0 + OBS_OFFSET, B: 2.0 + OBS_OFFSET})


def test_a_day_that_fails_validation_has_no_observed_means() -> None:
    def broken(day: date) -> tuple[pd.DataFrame, dict[str, int]]:
        df = observed_day(base=OBSERVED_BASE, day=day)
        return pd.concat([df, df.iloc[[0]]]).reset_index(drop=True), {}

    assert observed_means(broken, DAY, PHOENIX, SITES) is None


def test_measure_pairs_each_monitor_day_with_the_issued_run() -> None:
    days = [DAY, DAY + timedelta(days=1)]
    runs = FakeRuns({A: 11.0, B: 2.0})
    summary = measure(
        days,
        SITES,
        PHOENIX,
        fetch_run=runs,
        stitched_rows=stitched({A: 9.0, B: 3.0}, days),
        fetch_day=airnow(days),
    )
    assert sorted(runs.calls) == sorted((s, issued_run_start(d)) for d in days for s in SITES)
    obs = {A: 8.0 + OBS_OFFSET, B: 2.0 + OBS_OFFSET}
    assert summary["monitor_days"] == 4
    assert summary["mae_as_issued"] == pytest.approx((abs(11 - obs[A]) + abs(2 - obs[B])) / 2)
    assert summary["mae_stitched"] == pytest.approx((abs(9 - obs[A]) + abs(3 - obs[B])) / 2)
    assert summary["mean_abs_cams_difference"] == pytest.approx(1.5)


def test_each_skip_is_counted_by_its_first_reason() -> None:
    days = [DAY, DAY + timedelta(days=1), DAY + timedelta(days=2)]
    runs = FakeRuns(
        {A: 11.0, B: 2.0},
        empty={(A, issued_run_start(days[0]))},
        short={(A, issued_run_start(days[1]))},
    )
    history = stitched({A: 9.0, B: 3.0}, days)
    hole = (history["site_id"] == B) & (
        history["valid_utc"] == pd.Timestamp(datetime(2026, 6, 11, 15, tzinfo=UTC))
    )
    history.loc[hole, cams.VARIABLE] = math.nan

    def fetch_day(day: date) -> tuple[pd.DataFrame, dict[str, int]]:
        return observed_day({B: 10} if day == days[2] else None, base=OBSERVED_BASE, day=day), {}

    summary = measure(
        days, SITES, PHOENIX, fetch_run=runs, stitched_rows=history, fetch_day=fetch_day
    )
    assert summary["skipped"] == {
        "no_as_issued_run": 1,
        "as_issued_incomplete": 1,
        "stitched_incomplete": 1,
        "observed_failed_validation": 0,
        "no_observed": 1,
    }
    assert summary["monitor_days"] == 2


def test_a_day_failing_validation_skips_every_monitor_on_it() -> None:
    def broken(day: date) -> tuple[pd.DataFrame, dict[str, int]]:
        df = observed_day(base=OBSERVED_BASE, day=day)
        return pd.concat([df, df.iloc[[0]]]).reset_index(drop=True), {}

    summary = measure(
        [DAY],
        SITES,
        PHOENIX,
        fetch_run=FakeRuns({A: 1.0, B: 1.0}),
        stitched_rows=stitched({A: 1.0, B: 1.0}, [DAY]),
        fetch_day=broken,
    )
    assert summary["skipped"]["observed_failed_validation"] == 2
    assert summary["monitor_days"] == 0
