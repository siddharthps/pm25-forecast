"""Weather bulk history (T14, #19; D-051): ERA5 and the GFS archive at every monitor, into S3.

    cd ~/code/pm25-forecast                          # always run from the project folder
    uv run python scripts/weather_bulk.py            # dry run: shows the plan, writes nothing
    uv run python scripts/weather_bulk.py --apply    # fetch from Open-Meteo, upload to the bucket

AWS access: your SSO profile (`aws sso login --profile pm25`, then AWS_PROFILE=pm25). The logic
is in airwatch.weather.bulk and tested there; this script only wires the real edges: the
Open-Meteo client, boto3, the clock and the hourly budget. It never prints values or URLs.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime

import boto3
import httpx
import pandas as pd

from airwatch.config import get_settings
from airwatch.logutil import configure
from airwatch.observations.sites import TRAINING_SITES
from airwatch.storage import S3Store
from airwatch.weather.bulk import (
    HOURLY_BUDGET,
    HourlyBudget,
    Part,
    call_weight,
    load_manifest,
    plan_parts,
    run_download,
)
from airwatch.weather.openmeteo import Query, fetch_hourly

log = logging.getLogger("weather_bulk")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="fetch and upload (default: dry run)")
    args = parser.parse_args()
    configure()

    settings = get_settings()
    session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
    store = S3Store(session.client("s3"), settings.data_bucket)
    today = datetime.now(UTC).date()

    parts = plan_parts(TRAINING_SITES, today=today, manifest_parts=load_manifest(store)["parts"])
    weight = sum(call_weight((p.days(today)[1] - p.days(today)[0]).days + 1) for p in parts)
    log.info(
        "bucket %s: %d part(s), about %.0f weighted Open-Meteo calls, about %.1f h at %.0f an hour",
        settings.data_bucket,
        len(parts),
        weight,
        weight / HOURLY_BUDGET,
        HOURLY_BUDGET,
    )
    if not args.apply:
        log.info("dry run: nothing fetched or written. Re-run with --apply to download.")
        return 0

    with httpx.Client(timeout=httpx.Timeout(300.0, connect=20.0)) as client:

        def fetch(part: Part) -> pd.DataFrame:
            query = Query.for_site(part.source, part.site_id, *part.days(today))
            return fetch_hourly(client, query, now=lambda: datetime.now(UTC))

        summary = run_download(
            store,
            fetch,
            TRAINING_SITES,
            today=today,
            now=lambda: datetime.now(UTC),
            pace=HourlyBudget(monotonic=time.monotonic, sleep=time.sleep),
        )
    log.info("done: %d part(s) fetched, %d hourly rows", summary.fetched, summary.rows)
    return 0


if __name__ == "__main__":
    from botocore.exceptions import NoCredentialsError, SSOError, TokenRetrievalError

    try:
        sys.exit(main())
    except (TokenRetrievalError, SSOError, NoCredentialsError) as exc:
        log.error("AWS login needed (%s): run `aws sso login --profile pm25`", type(exc).__name__)
        sys.exit(3)
