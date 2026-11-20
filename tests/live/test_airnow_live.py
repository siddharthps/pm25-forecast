"""Live check (opt-in: `uv run pytest -m live`): yesterday's Phoenix day from real AirNow files.

Reports row counts only, never values. Never runs in CI or the core suite (pyproject markers).
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd
import pytest

from airwatch.config import get_settings
from airwatch.observations.airnow import (
    fetch_hour,
    hours_for_local_day,
    keep_sites,
    parse_hourly_aqobs,
)
from airwatch.observations.aqs import daily_means
from airwatch.observations.sites import TRAINING_SITES

log = logging.getLogger(__name__)


@pytest.mark.live
def test_yesterday_in_phoenix_from_airnow(caplog: pytest.LogCaptureFixture) -> None:
    tz = get_settings().city_tz
    yesterday = (datetime.now(UTC).astimezone(tz) - timedelta(days=1)).date()
    hours = hours_for_local_day(yesterday, tz)
    frames, dropped_total, unmatched_total = [], 0, 0
    with httpx.Client(timeout=60) as client:
        for h in hours:
            text, published = fetch_hour(client, h)
            df, dropped = parse_hourly_aqobs(text, published)
            kept, unmatched = keep_sites(df, TRAINING_SITES)
            frames.append(kept)
            dropped_total += sum(dropped.values())
            unmatched_total += unmatched
    hourly = pd.concat(frames, ignore_index=True)
    daily = daily_means(hourly, tz)
    with caplog.at_level(logging.INFO):
        log.info(
            "AirNow %s (%s): %d files, %d training-site hours, %d rows dropped, %d unmatched "
            "monitor-hours, %d of %d sites with a valid daily mean",
            yesterday,
            tz,
            len(hours),
            len(hourly),
            dropped_total,
            unmatched_total,
            daily["site_id"].nunique(),
            len(TRAINING_SITES),
        )
    assert len(hours) == 24
    assert daily["site_id"].nunique() >= 1
    assert (
        daily["available_at_utc"] > daily["date_local"].map(lambda d: pd.Timestamp(d, tz=tz))
    ).all()
