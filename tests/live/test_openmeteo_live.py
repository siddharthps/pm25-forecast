"""Live check (opt-in: `uv run pytest -m live`): each Open-Meteo source answers as expected.

One request per source for one monitor, checked by the client's own rules. Reports counts and
run times only, never values. Never runs in CI or the core suite (pyproject markers).
"""

import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from airwatch.weather import cams
from airwatch.weather.leads import MAX_PUBLISH_DELAY
from airwatch.weather.openmeteo import Query, Source, fetch_hourly, fetch_live

log = logging.getLogger(__name__)
SITE = "040134003"
PHOENIX = ZoneInfo("America/Phoenix")


def _now() -> datetime:
    return datetime.now(UTC)


@pytest.mark.live
@pytest.mark.parametrize(
    ("source", "day"),
    [(Source.ERA5, date(2024, 6, 15)), (Source.GFS_ARCHIVE, date(2025, 1, 15))],
    ids=["era5", "gfs_archive"],
)
def test_a_history_source_answers_in_full(source: Source, day: date) -> None:
    with httpx.Client(timeout=60) as client:
        df = fetch_hourly(client, Query.for_site(source, SITE, day, day), now=_now)
    missing = int(df.drop(columns=["run_start_utc"]).isna().sum().sum())
    log.info("%s %s: %d rows, %d missing values", source.value, day, len(df), missing)
    assert len(df) == 24
    assert missing == 0


@pytest.mark.live
def test_the_live_forecast_names_a_run_published_within_the_assumed_delay() -> None:
    tomorrow = (_now() + timedelta(days=1)).date()
    with httpx.Client(timeout=60) as client:
        df = fetch_live(client, Query.for_site(Source.GFS_LIVE, SITE, tomorrow, tomorrow), now=_now)
    started = df["run_start_utc"].iloc[0].to_pydatetime()
    available = df["available_at_utc"].iloc[0].to_pydatetime()
    log.info(
        "live: %d rows, run %s published %s after it started", len(df), started, available - started
    )
    assert len(df) == 24
    assert available - started <= MAX_PUBLISH_DELAY


@pytest.mark.live
def test_the_live_cams_forecast_names_a_run_no_newer_than_the_as_issued_one() -> None:
    target = (_now() + timedelta(days=1)).date()
    with httpx.Client(timeout=60) as client:
        df = cams.fetch_live(client, cams.CamsQuery.live_for(SITE, target, PHOENIX), now=_now)
    started = df["run_start_utc"].iloc[0].to_pydatetime()
    available = df["available_at_utc"].iloc[0].to_pydatetime()
    log.info(
        "cams live: %d rows, run %s published %s after it started",
        len(df),
        started,
        available - started,
    )
    assert len(df) == 48
    assert int(df[cams.VARIABLE].isna().sum()) == 0
    assert started <= cams.issued_run_start(target)
