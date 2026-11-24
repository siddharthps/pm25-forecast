"""Fakes for the daily job: an observed day of AirNow hours, CAMS as issued, S3 buckets."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from airwatch.observations.schema import POC_NOT_GIVEN, concat_hourly
from airwatch.timeutil import local_day_window_utc
from airwatch.weather import cams
from airwatch.weather.cams import CamsSource, issued_run_start
from tests.unit.validation.helpers import frame, varying

PHOENIX = ZoneInfo("America/Phoenix")
SITES = ("040130019", "040131003")
TARGET = date(2026, 11, 21)
ISSUE_AT = datetime(2026, 11, 20, 6, tzinfo=ZoneInfo("America/Chicago")).astimezone(UTC)
OBSERVED = date(2026, 11, 19)
PUBLISHED = ISSUE_AT - timedelta(hours=3)
PRIVATE, PUBLIC = "test-private-bucket", "test-public-bucket"


def observed_day(
    hours: dict[str, int] | None = None,
    *,
    base: dict[str, float] | None = None,
    available_at: datetime = PUBLISHED,
    day: date = OBSERVED,
) -> pd.DataFrame:
    """AirNow rows for `day`: `hours[site]` hours from local midnight (default 24 each)."""
    start = local_day_window_utc(day, PHOENIX)[0]
    frames = [
        frame(
            varying((hours or {}).get(site, 24), base=(base or {}).get(site, 8.0 + i)),
            site=site,
            poc=POC_NOT_GIVEN,
            method=None,
            source="airnow",
            start=start,
            available_at=available_at,
        )
        for i, site in enumerate(SITES)
    ]
    return concat_hourly(frames)


def fetcher(
    df: pd.DataFrame, drops: dict[str, int] | None = None, *, day: date = OBSERVED
) -> Callable[[date], tuple[pd.DataFrame, dict[str, int]]]:
    """A fetch_day that returns `df` for `day` (and refuses any other) and counts its calls."""

    def fetch_day(asked: date) -> tuple[pd.DataFrame, dict[str, int]]:
        assert asked == day, f"asked for {asked}, not {day}"
        fetch_day.calls += 1  # type: ignore[attr-defined]
        return df.copy(), dict(drops or {})

    fetch_day.calls = 0  # type: ignore[attr-defined]
    return fetch_day


class CamsFetcher:
    """A live CAMS fetch: the target's as-issued run, published 9 h 48 min after it started.

    Every hour holds `value`. `fail` raises like an unreachable Open-Meteo. Calls are counted.
    """

    def __init__(self, *, value: float = 6.0, fail: bool = False) -> None:
        self.value, self.fail = value, fail
        self.calls: list[tuple[str, date]] = []

    def __call__(self, site: str, target: date) -> pd.DataFrame:
        self.calls.append((site, target))
        if self.fail:
            raise ConnectionError("Open-Meteo unreachable")
        start, end = local_day_window_utc(target, PHOENIX)
        first = datetime.combine(start.date(), datetime.min.time(), tzinfo=UTC)
        hours = (end.date() - start.date()).days * 24 + 24
        run = issued_run_start(target)
        return pd.DataFrame(
            {
                "site_id": site,
                "valid_utc": pd.to_datetime(
                    [first + timedelta(hours=h) for h in range(hours)], utc=True
                ),
                cams.VARIABLE: self.value,
                "source": CamsSource.LIVE.value,
                "run_start_utc": pd.Timestamp(run),
                "available_at_utc": pd.Timestamp(run + timedelta(hours=9, minutes=48)),
            },
            columns=list(cams.COLUMNS),
        )


def object_versions(s3: Any, bucket: str, key: str) -> int:
    """How many versions of exactly `key` exist (the bucket is versioned)."""
    found = s3.list_object_versions(Bucket=bucket, Prefix=key).get("Versions", [])
    return sum(1 for v in found if v["Key"] == key)


class MemoryStore:
    """An in-memory bucket for runs that never touch S3 (dry runs, properties)."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.objects.get(key)

    def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    def list_keys(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))

    def create_if_absent(self, key: str, data: bytes) -> bool:
        if key in self.objects:
            return False
        self.objects[key] = data
        return True
