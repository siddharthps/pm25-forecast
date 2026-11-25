"""The feature rows (#21, T15; D-062): one per (monitor, target day D+1), as known at issue time.

The issue time is 06:00 Chicago on day D (`airwatch.timeutil`). What counts follows each row's
`source`, so training and serving run this same code on different inputs:

- **As published** (AirNow, the GFS archive, live GFS): only rows whose `available_at_utc` is
  before the issue time. Per weather hour, the newest run left wins.
- **Stand-ins** (AQS, ERA5): by measurement time only. AQS's `available_at_utc` is when AQS last
  changed the record and ERA5's is when it was fetched, both after any historical issue time.
  These are D-004's and D-007's declared skews, measured in T22.
- Always: PM2.5 hours of D-7 to D-1 (city-local days), weather stamps of D+1 only.

A feature without enough data is NaN and its row is kept. Instant weather values use the stamps
from local midnight up to the next one; precipitation and radiation are stamped at the end of
their hour, so they use the stamps after midnight through the next one (`airwatch.weather.leads`).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from airwatch.errors import ReportableError
from airwatch.observations.aqs import MIN_HOURS
from airwatch.timeutil import ensure_utc, issue_time_utc, local_day_window_utc

__all__ = [
    "CLOUD_RANGE",
    "FEATURE_COLUMNS",
    "KEY_COLUMNS",
    "PM_SOURCES_AS_PUBLISHED",
    "WEATHER_SOURCES_AS_PUBLISHED",
    "MixedSourcesError",
    "build_features",
    "known_at",
]

PM_SOURCES_AS_PUBLISHED = frozenset({"airnow"})
WEATHER_SOURCES_AS_PUBLISHED = frozenset({"gfs_archive", "gfs_live"})
CLOUD_RANGE = (0.0, 100.0)
FIREWORKS_DAYS = frozenset({(7, 4), (1, 1)})
WEEK_DAYS = 7
WEEK_MIN_VALID_DAYS = 4
DAYS_PER_YEAR = 365.25

KEY_COLUMNS = ("site_id", "target_day", "issue_at_utc")
PM_FEATURES = (
    "pm_mean_d1",
    "pm_mean_d2",
    "pm_mean_d3",
    "pm_mean_7d",
    "pm_max_d1",
    "pm_hours_d1",
)
WEATHER_FEATURES = (
    "temp_mean",
    "temp_max",
    "rh_mean",
    "wind_speed_mean",
    "wind_u_mean",
    "wind_v_mean",
    "precip_total",
    "pressure_mean",
    "cloud_mean",
    "shortwave_mean",
)
CALENDAR_FEATURES = ("doy_sin", "doy_cos", "day_of_week", "fireworks_day")
FEATURE_COLUMNS = (*PM_FEATURES, *WEATHER_FEATURES, *CALENDAR_FEATURES, "monitor")


class MixedSourcesError(ReportableError):
    """An input frame mixes sources, so one hour could be counted twice or from the wrong one."""


def _single_source(df: pd.DataFrame, what: str) -> None:
    sources = df["source"].dropna().unique()
    if len(sources) > 1:
        raise MixedSourcesError(f"{what}: {len(sources)} sources in one input; pass one")


def known_at(df: pd.DataFrame, cutoff_utc: datetime, as_published: frozenset[str]) -> pd.DataFrame:
    """Rows usable at `cutoff_utc`: as-published sources only if known strictly before it."""
    if getattr(df["available_at_utc"].dt, "tz", None) is None:
        raise ValueError("available_at_utc must be timezone-aware UTC")
    published = df["source"].isin(as_published)
    early = df["available_at_utc"] < pd.Timestamp(ensure_utc(cutoff_utc))
    return df.loc[~published | early]


def _pm_days(pm: pd.DataFrame, issue_day: date, tz: ZoneInfo) -> pd.DataFrame:
    """Per site and local day D-7..D-1: mean, max and count of instrument-averaged hours.

    The mean and max are NaN on a day with fewer than MIN_HOURS hours.
    """
    start, _ = local_day_window_utc(issue_day - timedelta(days=WEEK_DAYS), tz)
    end, _ = local_day_window_utc(issue_day, tz)
    window = pm[(pm["time_utc"] >= start) & (pm["time_utc"] < end)]
    per_hour = window.groupby(["site_id", "time_utc"], as_index=False, observed=True)[
        "value_ug_m3"
    ].mean()
    per_hour["date_local"] = per_hour["time_utc"].dt.tz_convert(tz).dt.date
    days: pd.DataFrame = per_hour.groupby(["site_id", "date_local"], observed=True)[
        "value_ug_m3"
    ].agg(["mean", "max", "size"])
    days.loc[days["size"] < MIN_HOURS, ["mean", "max"]] = np.nan
    return days


def _pm_features(days: pd.DataFrame, site: str, issue_day: date) -> dict[str, float]:
    def get(k: int, col: str) -> float:
        return float(days[col].get((site, issue_day - timedelta(days=k)), math.nan))

    week = [get(k, "mean") for k in range(1, WEEK_DAYS + 1)]
    valid_week = [v for v in week if not math.isnan(v)]
    d1_hours = get(1, "size")
    return {
        "pm_mean_d1": week[0],
        "pm_mean_d2": week[1],
        "pm_mean_d3": week[2],
        "pm_mean_7d": (
            sum(valid_week) / len(valid_week)
            if len(valid_week) >= WEEK_MIN_VALID_DAYS
            else math.nan
        ),
        "pm_max_d1": get(1, "max"),
        "pm_hours_d1": 0.0 if math.isnan(d1_hours) else d1_hours,
    }


def _newest_run(weather: pd.DataFrame) -> pd.DataFrame:
    ordered = weather.sort_values(["site_id", "valid_utc", "run_start_utc"], kind="stable")
    return ordered.drop_duplicates(["site_id", "valid_utc"], keep="last")


def _mean(values: pd.Series, need: int) -> float:
    present = values.dropna()
    return float(present.mean()) if len(present) >= need else math.nan


def _weather_features(w: pd.DataFrame, start: datetime, end: datetime) -> dict[str, float]:
    hours = (end - start) // timedelta(hours=1)
    instant = w[(w["valid_utc"] >= start) & (w["valid_utc"] < end)]
    ended = w[(w["valid_utc"] > start) & (w["valid_utc"] <= end)]
    temp = instant["temperature_2m"].dropna()
    rad = np.deg2rad(instant["wind_direction_10m"])
    speed = instant["wind_speed_10m"]
    rain = ended["precipitation"].dropna()
    return {
        "temp_mean": _mean(temp, MIN_HOURS),
        "temp_max": float(temp.max()) if len(temp) >= MIN_HOURS else math.nan,
        "rh_mean": _mean(instant["relative_humidity_2m"], MIN_HOURS),
        "wind_speed_mean": _mean(speed, MIN_HOURS),
        "wind_u_mean": _mean(-speed * np.sin(rad), MIN_HOURS),
        "wind_v_mean": _mean(-speed * np.cos(rad), MIN_HOURS),
        "precip_total": float(rain.sum()) if len(rain) == hours else math.nan,
        "pressure_mean": _mean(instant["surface_pressure"], MIN_HOURS),
        "cloud_mean": _mean(instant["cloud_cover"].clip(*CLOUD_RANGE), MIN_HOURS),
        "shortwave_mean": _mean(ended["shortwave_radiation"], MIN_HOURS),
    }


def _calendar_features(target: date) -> dict[str, float]:
    angle = 2 * math.pi * (target.timetuple().tm_yday - 1) / DAYS_PER_YEAR
    return {
        "doy_sin": math.sin(angle),
        "doy_cos": math.cos(angle),
        "day_of_week": float(target.weekday()),
        "fireworks_day": float((target.month, target.day) in FIREWORKS_DAYS),
    }


def build_features(
    pm_hourly: pd.DataFrame,
    weather: pd.DataFrame,
    target_days: Iterable[date],
    *,
    sites: Sequence[str],
    tz: ZoneInfo,
) -> pd.DataFrame:
    """One row per site in `sites` and day in `target_days`: KEY_COLUMNS then FEATURE_COLUMNS.

    `pm_hourly` has the hourly observation schema; `weather` the Open-Meteo columns. Each holds
    one source. Raises MixedSourcesError otherwise.
    """
    _single_source(pm_hourly, "PM2.5")
    _single_source(weather, "weather")
    wanted = sorted(set(sites))
    rows: list[dict[str, object]] = []
    for target in target_days:
        issue_at = issue_time_utc(target)
        issue_day = target - timedelta(days=1)
        days = _pm_days(known_at(pm_hourly, issue_at, PM_SOURCES_AS_PUBLISHED), issue_day, tz)
        start, end = local_day_window_utc(target, tz)
        w = known_at(weather, issue_at, WEATHER_SOURCES_AS_PUBLISHED)
        w = _newest_run(w[(w["valid_utc"] >= start) & (w["valid_utc"] <= end)])
        by_site = dict(tuple(w.groupby("site_id", observed=True)))
        calendar = _calendar_features(target)
        for site in wanted:
            rows.append(
                {
                    "site_id": site,
                    "target_day": target,
                    "issue_at_utc": pd.Timestamp(issue_at),
                    **_pm_features(days, site, issue_day),
                    **_weather_features(by_site.get(site, w.iloc[0:0]), start, end),
                    **calendar,
                    "monitor": site,
                }
            )
    out = pd.DataFrame(rows, columns=[*KEY_COLUMNS, *FEATURE_COLUMNS])
    out = out.astype({c: "float64" for c in FEATURE_COLUMNS if c != "monitor"})
    out = out.astype({"pm_hours_d1": "int64", "day_of_week": "int64", "fireworks_day": "int64"})
    out["site_id"] = out["site_id"].astype("string")
    out["monitor"] = pd.Categorical(out["monitor"], categories=wanted)
    return out
