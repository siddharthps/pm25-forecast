"""Small hourly PM2.5 and weather frames for the feature tests (D-062)."""

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from airwatch.observations.schema import POC_NOT_GIVEN, concat_hourly
from airwatch.timeutil import issue_time_utc, local_day_window_utc
from airwatch.weather.leads import target_hours_utc
from airwatch.weather.openmeteo import COLUMNS, VARIABLES
from tests.unit.validation.helpers import SITE_A, SITE_B, frame

__all__ = [
    "ISSUE_AT",
    "PHOENIX",
    "SITES",
    "SITE_A",
    "SITE_B",
    "TARGET",
    "pm_day",
    "pm_history",
    "weather_day",
]

PHOENIX = ZoneInfo("America/Phoenix")
SITES = (SITE_A, SITE_B)
TARGET = date(2026, 1, 15)
ISSUE_AT = issue_time_utc(TARGET)

CALM: Mapping[str, float] = {
    "temperature_2m": 12.0,
    "relative_humidity_2m": 40.0,
    "wind_speed_10m": 5.0,
    "wind_direction_10m": 180.0,
    "precipitation": 0.0,
    "surface_pressure": 970.0,
    "cloud_cover": 20.0,
    "shortwave_radiation": 150.0,
}


def pm_day(  # noqa: PLR0913  (each argument is one column of the schema or the day)
    day: date,
    values: Sequence[float] | float,
    *,
    site: str = SITE_A,
    source: str = "aqs",
    poc: int | None = None,
    hours: int | None = None,
    available_at: datetime | None = None,
) -> pd.DataFrame:
    """One local day of hourly rows from local midnight; `hours` keeps only the first ones."""
    start, end = local_day_window_utc(day, PHOENIX)
    n = (end - start) // timedelta(hours=1)
    vals = [float(values)] * n if isinstance(values, float | int) else [float(v) for v in values]
    vals = vals[: hours if hours is not None else n]
    airnow = source == "airnow"
    df = frame(
        vals,
        site=site,
        source=source,
        poc=POC_NOT_GIVEN if airnow else (poc if poc is not None else 3),
        method=None if airnow else "170",
        start=start,
        available_at=available_at or start + timedelta(days=200),
    )
    if airnow and available_at is None:
        df["available_at_utc"] = df["time_utc"] + pd.Timedelta(hours=1)
    return df


def pm_history(
    target: date,
    value_of: Callable[[str, date], float],
    *,
    sites: Sequence[str] = SITES,
    source: str = "aqs",
    days_back: int = 8,
) -> pd.DataFrame:
    """Every site, every local day from D-`days_back` through D-1 (D = the issue day)."""
    issue_day = target - timedelta(days=1)
    frames = [
        pm_day(
            issue_day - timedelta(days=k),
            value_of(site, issue_day - timedelta(days=k)),
            site=site,
            source=source,
        )
        for site in sites
        for k in range(1, days_back + 1)
    ]
    return concat_hourly(frames)


def weather_day(  # noqa: PLR0913  (each argument is one column or the day)
    target: date,
    *,
    site: str = SITE_A,
    source: str = "era5",
    values: Mapping[str, Sequence[float] | float] | None = None,
    run_start: datetime | None = None,
    available_at: datetime | None = None,
) -> pd.DataFrame:
    """Every stamp D+1's weather uses (midnight to midnight, both ends), all 8 variables."""
    stamps = target_hours_utc(target, PHOENIX)
    n = len(stamps)
    chosen = {**CALM, **(values or {})}
    cols: dict[str, object] = {"site_id": site, "valid_utc": pd.to_datetime(stamps, utc=True)}
    for var in VARIABLES:
        v = chosen[var]
        cols[var] = [float(v)] * n if isinstance(v, float | int) else [float(x) for x in v]
    run = run_start or datetime(2026, 1, 1, tzinfo=UTC)
    cols["source"] = source
    cols["run_start_utc"] = pd.Timestamp(run)
    cols["available_at_utc"] = pd.Timestamp(available_at or ISSUE_AT - timedelta(hours=20))
    df = pd.DataFrame(cols, columns=list(COLUMNS))
    return df.astype({"site_id": "string", "source": "string"})
