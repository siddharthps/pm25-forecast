"""Leakage and per-monitor rules for the feature rows, as properties (#21, T15; D-062).

- An as-published row (AirNow, GFS) known at or after the issue time, with any value, gives the
  same features as deleting it.
- A stand-in row (AQS, ERA5) outside its window (PM2.5 from day D on, weather outside D+1)
  never changes the features, whenever it was published.
- Changing, adding or deleting another monitor's rows, or shuffling the input, never changes a
  monitor's row.
"""

from datetime import date, timedelta

import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from airwatch.features.build import build_features
from airwatch.observations.schema import concat_hourly
from airwatch.weather.openmeteo import VARIABLES
from tests.unit.features.helpers import (
    ISSUE_AT,
    PHOENIX,
    SITE_A,
    SITE_B,
    SITES,
    TARGET,
    pm_day,
    pm_history,
    weather_day,
)

any_value = st.floats(min_value=-20, max_value=5000, allow_nan=False)
D = TARGET - timedelta(days=1)


def _level(site: str, d: date) -> float:
    return 4.0 + (d.toordinal() * 7 + int(site[-2:])) % 17


AIRNOW = pm_history(TARGET, _level, source="airnow")
AQS = pm_history(TARGET, _level)
GFS = pd.concat([weather_day(TARGET, site=s, source="gfs_archive") for s in SITES])
ERA5 = pd.concat([weather_day(TARGET, site=s) for s in SITES])


def features(pm: pd.DataFrame, weather: pd.DataFrame, site: str | None = None) -> pd.DataFrame:
    out = build_features(pm, weather, [TARGET], sites=SITES, tz=PHOENIX)
    if site is not None:
        out = out[out["site_id"] == site]
    return out.sort_values("site_id").reset_index(drop=True)


LIVE_BASE = features(AIRNOW, GFS)
STAND_IN_BASE = features(AQS, ERA5)
SITE_A_BASE = features(AQS, ERA5, SITE_A)


@settings(deadline=None, max_examples=40)
@given(
    picked=st.sets(st.integers(min_value=0, max_value=len(AIRNOW) - 1)),
    values=st.lists(any_value, min_size=len(AIRNOW), max_size=len(AIRNOW)),
    after_s=st.integers(min_value=0, max_value=8 * 3600),
)
def test_airnow_known_at_or_after_issue_counts_as_deleted(
    picked: set[int], values: list[float], after_s: int
) -> None:
    mask = AIRNOW.index.isin(picked)
    changed = AIRNOW.copy()
    changed.loc[mask, "value_ug_m3"] = pd.Series(values, index=AIRNOW.index)[mask]
    changed.loc[mask, "available_at_utc"] = pd.Timestamp(ISSUE_AT + timedelta(seconds=after_s))
    deleted = AIRNOW[~mask].reset_index(drop=True)
    pd.testing.assert_frame_equal(features(changed, GFS), features(deleted, GFS))


@settings(deadline=None, max_examples=40)
@given(
    picked=st.sets(st.integers(min_value=0, max_value=len(GFS) - 1)),
    values=st.lists(any_value, min_size=len(GFS), max_size=len(GFS)),
    variable=st.sampled_from(VARIABLES),
    after_s=st.integers(min_value=0, max_value=30 * 3600),
)
def test_gfs_known_at_or_after_issue_counts_as_deleted(
    picked: set[int], values: list[float], variable: str, after_s: int
) -> None:
    base = GFS.reset_index(drop=True)
    mask = base.index.isin(picked)
    newer = base[mask].copy()
    newer[variable] = pd.Series(values, index=base.index)[mask]
    newer["run_start_utc"] = pd.Timestamp(ISSUE_AT)
    newer["available_at_utc"] = pd.Timestamp(ISSUE_AT + timedelta(seconds=after_s))
    pd.testing.assert_frame_equal(features(AIRNOW, pd.concat([base, newer])), LIVE_BASE)


@settings(deadline=None, max_examples=40)
@given(
    hours=st.integers(min_value=1, max_value=48),
    values=st.lists(any_value, min_size=48, max_size=48),
    site=st.sampled_from(SITES),
    published_before=st.booleans(),
)
def test_aqs_from_the_issue_day_on_never_counts(
    hours: int, values: list[float], site: str, published_before: bool
) -> None:
    extra = concat_hourly(
        [
            pm_day(D, values[:24], site=site, hours=min(hours, 24)),
            pm_day(TARGET, values[24:], site=site, hours=max(hours - 24, 1)),
        ]
    )
    extra["available_at_utc"] = (
        extra["time_utc"] + pd.Timedelta(hours=1)
        if published_before
        else pd.Timestamp(ISSUE_AT + timedelta(days=90))
    )
    pd.testing.assert_frame_equal(features(concat_hourly([AQS, extra]), ERA5), STAND_IN_BASE)


@settings(deadline=None, max_examples=40)
@given(
    shift_h=st.one_of(
        st.integers(min_value=-72, max_value=-1), st.integers(min_value=25, max_value=96)
    ),
    values=st.lists(any_value, min_size=25, max_size=25),
    variable=st.sampled_from(VARIABLES),
    site=st.sampled_from(SITES),
)
def test_era5_outside_the_target_day_never_counts(
    shift_h: int, values: list[float], variable: str, site: str
) -> None:
    outside = weather_day(TARGET, site=site, values={variable: values})
    outside["valid_utc"] = outside["valid_utc"] + pd.Timedelta(hours=shift_h)
    outside = outside[~outside["valid_utc"].isin(ERA5["valid_utc"])]
    pd.testing.assert_frame_equal(features(AQS, pd.concat([ERA5, outside])), STAND_IN_BASE)


@settings(deadline=None, max_examples=40)
@given(
    pm_values=st.lists(any_value, min_size=1, max_size=len(AQS)),
    weather_value=any_value,
    variable=st.sampled_from(VARIABLES),
    drop_other=st.booleans(),
    seed=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_other_monitors_and_row_order_never_change_a_monitor(
    pm_values: list[float], weather_value: float, variable: str, drop_other: bool, seed: int
) -> None:
    other_pm = AQS["site_id"] == SITE_B
    pm = AQS.copy()
    idx = pm.index[other_pm][: len(pm_values)]
    pm.loc[idx, "value_ug_m3"] = pm_values[: len(idx)]
    weather = ERA5.copy()
    weather.loc[weather["site_id"] == SITE_B, variable] = weather_value
    if drop_other:
        pm = pm[~other_pm]
        weather = weather[weather["site_id"] != SITE_B]
    pm = pm.sample(frac=1.0, random_state=seed % 2**32).reset_index(drop=True)
    weather = weather.sample(frac=1.0, random_state=seed % 2**32)
    pd.testing.assert_frame_equal(features(pm, weather, SITE_A), SITE_A_BASE)
