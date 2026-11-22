"""Leakage, as properties (#13, T6; D-019, D-034): nothing published after the issue time, and
nothing outside the observed day, can change the forecast.

- Any row published after the issue time, with any value, gives the same forecast as deleting it.
- Rows from the issue day itself (D, not yet complete) never change the forecast.
"""

from datetime import timedelta
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from airwatch.forecast.run import NoForecastError, run_daily
from airwatch.observations.schema import POC_NOT_GIVEN, concat_hourly
from tests.unit.forecast.fakes import (
    ISSUE_AT,
    PHOENIX,
    SITES,
    TARGET,
    MemoryStore,
    fetcher,
    observed_day,
)
from tests.unit.validation.helpers import frame

BASE = observed_day()
any_value = st.floats(min_value=-20, max_value=5000, allow_nan=False)


LATE_RUN_SEES_EVERY_HOUR = ISSUE_AT + timedelta(hours=9)


def forecast_of(df: pd.DataFrame) -> tuple[Any, Any]:
    outcome = run_daily(
        TARGET,
        fetch_day=fetcher(df),
        private=MemoryStore(),
        public=MemoryStore(),
        now=lambda: LATE_RUN_SEES_EVERY_HOUR,
        tz=PHOENIX,
        sites=SITES,
        publish=False,
    )
    return outcome.record["forecasts"], outcome.record["no_forecast"]


BASE_FORECAST = forecast_of(BASE)


@settings(deadline=None)
@given(
    late=st.lists(st.booleans(), min_size=len(BASE), max_size=len(BASE)),
    values=st.lists(any_value, min_size=len(BASE), max_size=len(BASE)),
    after_s=st.integers(min_value=1, max_value=8 * 3600),
)
def test_a_row_published_after_issue_counts_as_if_deleted(
    late: list[bool], values: list[float], after_s: int
) -> None:
    mask = pd.Series(late)
    changed = BASE.copy()
    changed.loc[mask, "value_ug_m3"] = pd.Series(values)[mask]
    changed.loc[mask, "available_at_utc"] = pd.Timestamp(ISSUE_AT + timedelta(seconds=after_s))
    deleted = BASE[~mask].reset_index(drop=True)
    if len(deleted) == 0:
        return
    try:
        expected = forecast_of(deleted)
    except NoForecastError:
        with pytest.raises(NoForecastError):
            forecast_of(changed)
        return
    assert forecast_of(changed) == expected


@settings(deadline=None)
@given(
    values=st.lists(any_value, min_size=1, max_size=4),
    site=st.sampled_from(SITES),
)
def test_rows_from_the_unfinished_issue_day_never_change_the_forecast(
    values: list[float], site: str
) -> None:
    """Hours from 00:00 Phoenix on the issue day (07:00 UTC), published by 11:30 UTC.

    That's before the 12:00 UTC issue time, so only the observed-day rule keeps them out.
    """
    d_start = ISSUE_AT - timedelta(hours=5)
    published = d_start + timedelta(hours=4, minutes=30)
    assert published <= ISSUE_AT
    today = frame(
        values,
        site=site,
        poc=POC_NOT_GIVEN,
        method=None,
        source="airnow",
        start=d_start,
        available_at=published,
    )
    assert forecast_of(concat_hourly([BASE, today])) == BASE_FORECAST
