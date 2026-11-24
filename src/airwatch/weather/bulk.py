"""Weather bulk history (#19, T14; D-051): one Parquet file per source, site and year, in S3.

ERA5 for 2009-2024 (the training weather) and the GFS archive from its first day (2024-01-20)
to yesterday (the test year and the forecasts-only variant), each at every monitor. The same
rules as the AQS download (`airwatch.observations.aqs_bulk`):

- **Durable record:** a manifest in S3 (`MANIFEST_KEY`) lists every finished part, with its rows,
  missing values, sha256 and fetch time. "Done" comes from the manifest, never local files.
- **Order of writes:** the data file first, then its manifest entry. A crash in between leaves an
  unrecorded file, which the next run fetches again and overwrites (same key, no duplicates).
- **Resumable and idempotent:** a rerun fetches only parts missing from the manifest, plus the
  current year's archive, which isn't final until the year has ended.
- **Quiet:** logs name the part and count rows, never a value.
- **Paced:** Open-Meteo counts a request over 10 variables or 2 weeks as several calls
  (open-meteo.com/en/pricing, read 2026-11-23: "2 weeks of data with 15 weather variables will be
  calculated as 1.5 API calls, while 4 weeks of data equals 3.0"). `call_weight` follows those
  examples, and each fetch first waits for room in an hourly budget set at half the free limit.
- **Single writer:** one run at a time (the manifest is read, updated and written back).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from airwatch.forecast.record import Store
from airwatch.weather.openmeteo import VARIABLES, Source

__all__ = [
    "ARCHIVE_START",
    "ERA5_YEARS",
    "HOURLY_BUDGET",
    "MANIFEST_KEY",
    "PREFIX",
    "HourlyBudget",
    "Part",
    "Summary",
    "call_weight",
    "load_manifest",
    "plan_parts",
    "run_download",
]

log = logging.getLogger(__name__)

PREFIX = "raw/weather/"
MANIFEST_KEY = PREFIX + "manifest.json"
ERA5_YEARS = range(2009, 2025)
ARCHIVE_START = date(2024, 1, 20)
FREE_CALLS_PER_HOUR = 5000
HOURLY_BUDGET = FREE_CALLS_PER_HOUR / 2
_WINDOW_S = 3600.0


@dataclass(frozen=True, order=True)
class Part:
    """One source, site and calendar year (UTC days) of hourly weather."""

    source: Source
    site_id: str
    year: int

    @property
    def key(self) -> str:
        return f"{PREFIX}source={self.source.value}/site={self.site_id}/year={self.year}.parquet"

    def days(self, today: date) -> tuple[date, date]:
        """The UTC days this part asks for: its year, cut to the archive's start and yesterday."""
        start, end = date(self.year, 1, 1), date(self.year, 12, 31)
        if self.source is Source.GFS_ARCHIVE:
            start = max(start, ARCHIVE_START)
            end = min(end, today - timedelta(days=1))
        return start, end

    def is_final(self, today: date) -> bool:
        return self.year < today.year


@dataclass(frozen=True)
class Summary:
    fetched: int
    rows: int


def call_weight(days: int, variables: int = len(VARIABLES)) -> float:
    """How many API calls Open-Meteo counts for one request (at least 1)."""
    return max(1.0, variables / 10) * max(1.0, days / 14)


class HourlyBudget:
    """Wait before a request until the last hour's weighted calls leave room for it."""

    def __init__(
        self,
        limit: float = HOURLY_BUDGET,
        *,
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.limit = limit
        self._monotonic = monotonic
        self._sleep = sleep
        self._spent: deque[tuple[float, float]] = deque()

    def _expire(self, now: float) -> None:
        while self._spent and self._spent[0][0] + _WINDOW_S <= now:
            self._spent.popleft()

    def __call__(self, weight: float) -> None:
        if weight > self.limit:
            raise ValueError(f"one request of {weight:.1f} calls is over the hourly budget")
        now = self._monotonic()
        self._expire(now)
        while self._spent and sum(w for _, w in self._spent) + weight > self.limit:
            self._sleep(self._spent[0][0] + _WINDOW_S - now)
            now = self._monotonic()
            self._expire(now)
        self._spent.append((now, weight))


def plan_parts(
    sites: Iterable[str],
    *,
    today: date,
    manifest_parts: Mapping[str, Mapping[str, Any]],
    era5_years: range = ERA5_YEARS,
) -> list[Part]:
    """Parts to fetch: those missing from the manifest, or recorded but not yet final."""
    wanted = tuple(sites)
    todo = [Part(Source.ERA5, s, y) for s in wanted for y in era5_years]
    todo += [
        Part(Source.GFS_ARCHIVE, s, y)
        for s in wanted
        for y in range(ARCHIVE_START.year, today.year + 1)
    ]
    return sorted(p for p in todo if not manifest_parts.get(p.key, {}).get("final", False))


def load_manifest(store: Store) -> dict[str, Any]:
    raw = store.get(MANIFEST_KEY)
    if raw is None:
        return {"version": 1, "parts": {}}
    manifest: dict[str, Any] = json.loads(raw)
    return manifest


def _parquet_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow")
    return buf.getvalue()


def run_download(  # noqa: PLR0913  (each argument is an injected edge: store, fetch, clock, pace)
    store: Store,
    fetch: Callable[[Part], pd.DataFrame],
    sites: Iterable[str],
    *,
    today: date,
    now: Callable[[], datetime],
    pace: Callable[[float], None],
    era5_years: range = ERA5_YEARS,
) -> Summary:
    """Fetch every missing or unfinished part, writing data before its manifest entry."""
    manifest = load_manifest(store)
    parts = plan_parts(sites, today=today, manifest_parts=manifest["parts"], era5_years=era5_years)
    log.info("%d part(s) to fetch", len(parts))
    total_rows = 0
    for i, part in enumerate(parts, start=1):
        start, end = part.days(today)
        pace(call_weight((end - start).days + 1))
        df = fetch(part)
        missing = int(df[list(VARIABLES)].isna().sum().sum())
        data = _parquet_bytes(df)
        store.put(part.key, data)
        manifest["parts"][part.key] = {
            "key": part.key,
            "source": part.source.value,
            "site_id": part.site_id,
            "year": part.year,
            "first_day": start.isoformat(),
            "last_day": end.isoformat(),
            "rows": len(df),
            "missing_values": missing,
            "sha256": hashlib.sha256(data).hexdigest(),
            "fetched_at_utc": now().isoformat(),
            "final": part.is_final(today),
        }
        store.put(MANIFEST_KEY, json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"))
        total_rows += len(df)
        log.info(
            "[%d/%d] %s, site %s, %d: %d rows, %d missing values",
            i,
            len(parts),
            part.source.value,
            part.site_id,
            part.year,
            len(df),
            missing,
        )
    return Summary(fetched=len(parts), rows=total_rows)
