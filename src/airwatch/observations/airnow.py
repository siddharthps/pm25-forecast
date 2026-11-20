"""AirNow hourly observations (#10, T5): the live input (D-004), preliminary and unvalidated.

Source: AirNow's public hourly file product, `HourlyAQObs_YYYYMMDDHH.dat` on
files.airnowtech.org (no key needed). Checked on a real file: `PM25` is the raw hourly value,
`ValidDate`/`ValidTime` are UTC, and `AQSID` is the AQS site ID. So AirNow monitors map to the
AQS training sites directly.

`available_at_utc` is the file's Last-Modified time: when AirNow published that hour. That is
later than the hour itself (about three hours for the file checked).
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from airwatch.observations.metadata import FetchError, fetch_response
from airwatch.observations.schema import HOURLY_COLUMNS, concat_hourly, validate_hourly
from airwatch.timeutil import local_day_window_utc

__all__ = [
    "FILES_BASE",
    "fetch_hour",
    "fetch_local_day",
    "hourly_file_url",
    "hours_for_local_day",
    "keep_sites",
    "parse_hourly_aqobs",
]

FILES_BASE = "https://files.airnowtech.org/airnow/"
UNIT = "UG/M3"
HTTP_NOT_FOUND = 404
AQS_SITE_ID = re.compile(r"\d{9}")


def _require_aware(dt: datetime, name: str) -> None:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"naive datetime rejected: {name} has no time zone")


def hourly_file_url(hour_utc: datetime) -> str:
    """URL of the HourlyAQObs file for the hour starting at `hour_utc`."""
    _require_aware(hour_utc, "hour_utc")
    h = hour_utc.astimezone(UTC)
    return f"{FILES_BASE}{h:%Y}/{h:%Y%m%d}/HourlyAQObs_{h:%Y%m%d%H}.dat"


def hours_for_local_day(day: date, tz: ZoneInfo) -> list[datetime]:
    """The UTC hour starts that make up local calendar day `day` (23, 24 or 25 of them)."""
    start, end = local_day_window_utc(day, tz)
    n = int((end - start) / timedelta(hours=1))
    return [start + timedelta(hours=i) for i in range(n)]


def parse_hourly_aqobs(text: str, published_utc: datetime) -> tuple[pd.DataFrame, dict[str, int]]:
    """An HourlyAQObs file -> the hourly schema, plus a count of dropped rows by reason.

    A row is kept only if PM2.5 was measured, has a value, and is in UG/M3. Every other row is
    counted, never silently ignored.
    """
    _require_aware(published_utc, "published_utc")
    dropped: Counter[str] = Counter()
    kept: list[dict[str, str]] = []
    for r in csv.DictReader(io.StringIO(text)):
        if not r.get("PM25"):
            dropped["no_pm25_value"] += 1
        elif r.get("PM25_Measured") != "1":
            dropped["not_measured"] += 1
        elif r.get("PM25_Unit") != UNIT:
            dropped["unit_not_ug_m3"] += 1
        elif not AQS_SITE_ID.fullmatch(r.get("AQSID", "")):
            dropped["not_an_aqs_site_id"] += 1
        else:
            kept.append(r)

    published = pd.Timestamp(published_utc.astimezone(UTC))
    df = pd.DataFrame(
        {
            "source": "airnow",
            "site_id": [r["AQSID"] for r in kept],
            "poc": 0,
            "method_code": pd.NA,
            "time_utc": pd.to_datetime(
                [f"{r['ValidDate']} {r['ValidTime']}" for r in kept],
                utc=True,
                format="%m/%d/%Y %H:%M",
            ),
            "value_ug_m3": [float(r["PM25"]) for r in kept],
            "qualifier": pd.NA,
            "available_at_utc": published,
        },
        columns=list(HOURLY_COLUMNS),
    ).astype(HOURLY_COLUMNS)

    if len(df) and (df["available_at_utc"] <= df["time_utc"]).any():
        raise ValueError("file published before the hour it reports")
    validate_hourly(df)
    return df.reset_index(drop=True), dict(dropped)


def keep_sites(df: pd.DataFrame, sites: Iterable[str]) -> tuple[pd.DataFrame, int]:
    """Rows for `sites` only, plus how many AirNow rows were excluded as unmatched."""
    wanted = set(sites)
    mask = df["site_id"].isin(wanted)
    return df[mask].reset_index(drop=True), int((~mask).sum())


def fetch_hour(client: httpx.Client, hour_utc: datetime) -> tuple[str, datetime]:
    """Download one hourly file; return its text and its publication time (Last-Modified)."""
    response = fetch_response(client, hourly_file_url(hour_utc))
    modified = response.headers.get("Last-Modified")
    if not modified:
        raise RuntimeError("AirNow file has no Last-Modified header")
    return response.text, parsedate_to_datetime(modified).astimezone(UTC)


def fetch_local_day(
    client: httpx.Client, day: date, tz: ZoneInfo, sites: Iterable[str]
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Every hourly file of local day `day`, kept to `sites`, plus every drop counted by reason.

    A file AirNow hasn't published (404) is counted as `file_missing`, not fatal: the coverage
    check in validation judges whether the day still has enough hours. Other failures raise.
    """
    wanted = tuple(sites)
    frames: list[pd.DataFrame] = []
    drops: Counter[str] = Counter()
    for hour in hours_for_local_day(day, tz):
        try:
            text, published = fetch_hour(client, hour)
        except FetchError as exc:
            if exc.status != HTTP_NOT_FOUND:
                raise
            drops["file_missing"] += 1
            continue
        df, dropped = parse_hourly_aqobs(text, published)
        kept, unmatched = keep_sites(df, wanted)
        drops.update(dropped)
        drops["unmatched_site"] += unmatched
        frames.append(kept)
    day_df = concat_hourly(frames)
    validate_hourly(day_df)
    return day_df, dict(drops)
