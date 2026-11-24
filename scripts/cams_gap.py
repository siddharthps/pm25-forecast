"""The CAMS archive gap (T14, #19; D-052): as-issued CAMS against the stitched history.

    cd ~/code/pm25-forecast
    AWS_PROFILE=pm25 uv run python scripts/cams_gap.py            # reads only; writes the report
    AWS_PROFILE=pm25 uv run python scripts/cams_gap.py --days 2   # a timing run: the first 2 days

Reads the stitched CAMS history from the private bucket (the bulk download), one Single Runs
request per monitor and target day (paced), and AirNow's public hourly files. Writes the summary
to data/reports/cams_gap/ (gitignored). The logic is in airwatch.weather.cams_gap and tested
there; this script only wires the real edges. Logs hold counts and days, never a value or a URL.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import boto3
import httpx
import pandas as pd

from airwatch.config import get_settings
from airwatch.logutil import configure
from airwatch.observations.airnow import fetch_local_day
from airwatch.observations.sites import TRAINING_SITES
from airwatch.storage import S3Store
from airwatch.weather import cams
from airwatch.weather.bulk import CallBudget, Part, call_weight
from airwatch.weather.cams import CamsQuery, CamsSource
from airwatch.weather.cams_gap import measure, target_days

log = logging.getLogger("cams_gap")
REPORT_DIR = Path("data/reports/cams_gap")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, help="only the first N target days (a timing run)")
    args = parser.parse_args()
    configure()
    settings = get_settings()
    session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
    store = S3Store(session.client("s3"), settings.data_bucket)
    today = datetime.now(UTC).date()
    days = target_days(today)[: args.days]
    years = sorted({d.year for d in days})

    frames = []
    for site in TRAINING_SITES:
        for year in years:
            raw = store.get(Part(CamsSource.HISTORY, site, year).key)
            if raw is None:
                log.error("no CAMS history: site %s, %d (run weather_bulk.py)", site, year)
                return 1
            frames.append(pd.read_parquet(io.BytesIO(raw)))
    stitched = pd.concat(frames, ignore_index=True)
    log.info(
        "%d target days (%s to %s), %d monitors", len(days), days[0], days[-1], len(TRAINING_SITES)
    )

    pace = CallBudget(monotonic=time.monotonic, sleep=time.sleep)
    with httpx.Client(timeout=httpx.Timeout(120.0, connect=20.0)) as client:
        calls = {"n": 0}

        def fetch_run(site: str, run: datetime) -> pd.DataFrame:
            pace(call_weight(7, 1))
            calls["n"] += 1
            if calls["n"] % 200 == 0:
                log.info("%d runs fetched", calls["n"])
            return cams.fetch(client, CamsQuery.run_at(site, run))

        summary = measure(
            days,
            TRAINING_SITES,
            settings.city_tz,
            fetch_run=fetch_run,
            stitched_rows=stitched,
            fetch_day=lambda d: fetch_local_day(client, d, settings.city_tz, TRAINING_SITES),
        )

    summary["computed_at_utc"] = datetime.now(UTC).isoformat()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = f"-first{args.days}" if args.days else ""
    path = REPORT_DIR / f"cams-gap-{today.isoformat()}{suffix}.json"
    path.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    log.info(
        "%d monitor-days compared, %d skipped; summary in %s",
        summary["monitor_days"],
        sum(summary["skipped"].values()),
        path,
    )
    return 0


if __name__ == "__main__":
    from botocore.exceptions import NoCredentialsError, SSOError, TokenRetrievalError

    try:
        sys.exit(main())
    except (TokenRetrievalError, SSOError, NoCredentialsError) as exc:
        log.error("AWS login needed (%s): run `aws sso login --profile pm25`", type(exc).__name__)
        sys.exit(3)
