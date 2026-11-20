"""EPA AQS client and parsing (#10, T5): validated hourly PM2.5 for training labels.

- Only hourly PM2.5 (parameter 88101, sample duration code 1) in µg/m³ is kept: the same kind
  of continuous instrument AirNow reports (OQ-8).
- Timestamps come from AQS's GMT fields. Its `time_local` is local *standard* time all year
  (checked on a recorded response), so it is never used.
- `available_at_utc` is the end of the day AQS last changed the record: data can't be known
  before it was last changed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from airwatch.observations.metadata import fetch_json
from airwatch.observations.schema import HOURLY_COLUMNS, validate_hourly

__all__ = ["AQS_BASE", "daily_means", "fetch_site_year", "parse_sample_rows"]

AQS_BASE = "https://aqs.epa.gov/data/api/"
PARAMETER = "88101"
HOURLY_CODE = "1"
UNITS = "Micrograms/cubic meter (LC)"
MIN_HOURS = 18


def parse_sample_rows(rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """AQS `sampleData` rows -> the hourly schema. Raises ValueError on surprises."""
    kept = [
        r
        for r in rows
        if str(r["parameter_code"]) == PARAMETER
        and str(r["sample_duration_code"]) == HOURLY_CODE
        and r["sample_measurement"] is not None
    ]
    units = {r["units_of_measure"] for r in kept}
    if units - {UNITS}:
        raise ValueError(f"unexpected units {sorted(units - {UNITS})}")

    df = pd.DataFrame(
        {
            "source": "aqs",
            "site_id": [f"{r['state_code']}{r['county_code']}{r['site_number']}" for r in kept],
            "poc": [int(r["poc"]) for r in kept],
            "method_code": [str(r["method_code"]) for r in kept],
            "time_utc": pd.to_datetime(
                [f"{r['date_gmt']} {r['time_gmt']}" for r in kept],
                utc=True,
                format="%Y-%m-%d %H:%M",
            ),
            "value_ug_m3": [float(r["sample_measurement"]) for r in kept],
            "qualifier": [r.get("qualifier") for r in kept],
            "available_at_utc": pd.to_datetime(
                [r["date_of_last_change"] for r in kept], utc=True, format="%Y-%m-%d"
            )
            + pd.Timedelta(days=1),
        },
        columns=list(HOURLY_COLUMNS),
    ).astype(HOURLY_COLUMNS)

    if (df["available_at_utc"] <= df["time_utc"]).any():
        raise ValueError("a record's last-change date is before its measurement")
    validate_hourly(df)
    return df.reset_index(drop=True)


def daily_means(hourly: pd.DataFrame, tz: ZoneInfo) -> pd.DataFrame:
    """Per-site daily means over the city's local calendar day (SPEC § Key definitions).

    Co-located instruments are averaged per hour first; a day needs >= 18 such hours.
    """
    validate_hourly(hourly)
    per_hour = (
        hourly.assign(date_local=hourly["time_utc"].dt.tz_convert(tz).dt.date)
        .groupby(["site_id", "date_local", "time_utc"], as_index=False)
        .agg(value=("value_ug_m3", "mean"), available_at_utc=("available_at_utc", "max"))
    )
    daily = per_hour.groupby(["site_id", "date_local"], as_index=False).agg(
        mean_ug_m3=("value", "mean"),
        n_hours=("value", "size"),
        available_at_utc=("available_at_utc", "max"),
    )
    valid = daily[daily["n_hours"] >= MIN_HOURS]
    return valid.reset_index(drop=True)


def fetch_site_year(
    client: httpx.Client, auth: Mapping[str, str], site_id: str, year: int
) -> list[dict[str, Any]]:
    """Raw AQS hourly rows for one site and one calendar year (AQS: one year per request).

    Credentials travel in `auth`; nothing here logs a URL or a parameter.
    """
    params = {
        **auth,
        "param": PARAMETER,
        "bdate": f"{year}0101",
        "edate": f"{year}1231",
        "state": site_id[:2],
        "county": site_id[2:5],
        "site": site_id[5:],
    }
    data = fetch_json(client, AQS_BASE + "sampleData/bySite", params)
    status = str(data.get("Header", [{}])[0].get("status", ""))
    if status.startswith("No data"):
        return []
    if status != "Success":
        raise RuntimeError(f"AQS sampleData: status {status!r} for site {site_id}, {year}")
    rows: list[dict[str, Any]] = data.get("Data", [])
    return rows
