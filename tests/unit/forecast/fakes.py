"""Fakes for the daily forecast: an observed day of AirNow hours, and S3 buckets in moto."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from airwatch.observations.schema import concat_hourly
from airwatch.timeutil import local_day_window_utc
from tests.unit.validation.helpers import frame, varying

PHOENIX = ZoneInfo("America/Phoenix")
SITES = ("040130019", "040131003")
TARGET = date(2026, 11, 21)  # issued Friday 2026-11-20 06:00 Chicago = 12:00 UTC
ISSUE_AT = datetime(2026, 11, 20, 12, tzinfo=UTC)
OBSERVED = date(2026, 11, 19)  # D-1: the last complete Phoenix day at issue time
PUBLISHED = ISSUE_AT - timedelta(hours=3)  # every input file existed before the issue time
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
            poc=0,
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
