"""AQS bulk history download (T13, #11): Phoenix's training sites, 2009 to today, into private S3.

    cd ~/code/pm25-forecast                      # always run from the project folder
    uv run python scripts/aqs_bulk.py            # dry run: shows the plan, writes nothing
    uv run python scripts/aqs_bulk.py --apply    # fetch from AQS and upload to the private bucket

AWS access: your SSO profile (`aws sso login --profile pm25`, then AWS_PROFILE=pm25). The logic
is in airwatch.observations.aqs_bulk and tested there; this script only wires the real edges:
the AQS client (paced as AQS's terms ask), boto3, and the clock. It never prints credentials,
URLs or measurements.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any

import boto3
import httpx

from airwatch.config import get_settings
from airwatch.observations.aqs import fetch_site_year
from airwatch.observations.aqs_bulk import (
    FIRST_YEAR,
    S3Store,
    load_manifest,
    plan_parts,
    run_download,
)
from airwatch.observations.sites import TRAINING_SITES

AQS_PAUSE_S = 6.0  # AQS terms: <= 10 requests a minute, a 5-second pause between requests

log = logging.getLogger("aqs_bulk")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="fetch and upload (default: dry run)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    # The AWS SDK logs its own retries and token refreshes (with tracebacks); keep it quiet and
    # never let it log request details. Our own messages say what matters.
    for name in ("botocore", "boto3", "urllib3"):
        logging.getLogger(name).setLevel(logging.ERROR)

    settings = get_settings()
    session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
    store = S3Store(session.client("s3"), settings.data_bucket)
    today = datetime.now(UTC).date()

    parts = plan_parts(
        TRAINING_SITES,
        first_year=FIRST_YEAR,
        today=today,
        manifest_parts=load_manifest(store)["parts"],
    )
    log.info(
        "bucket %s: %d part(s) to fetch, about %d min at the AQS pace",
        settings.data_bucket,
        len(parts),
        round(len(parts) * AQS_PAUSE_S / 60) + 1,
    )
    if not args.apply:
        log.info("dry run: nothing fetched or written. Re-run with --apply to download.")
        return 0

    auth = {
        "email": settings.aqs_email.get_secret_value(),
        "key": settings.aqs_api_key.get_secret_value(),
    }
    last = [0.0]
    with httpx.Client(timeout=httpx.Timeout(300.0, connect=20.0)) as client:

        def fetch(site: str, year: int) -> list[dict[str, Any]]:
            wait = AQS_PAUSE_S - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            try:
                return fetch_site_year(client, auth, site, year)
            finally:
                last[0] = time.monotonic()

        summary = run_download(
            store,
            fetch,
            TRAINING_SITES,
            first_year=FIRST_YEAR,
            today=today,
            now=lambda: datetime.now(UTC),
        )
    log.info("done: %d part(s) fetched, %d hourly rows", summary.fetched, summary.rows)
    return 0


if __name__ == "__main__":
    from botocore.exceptions import NoCredentialsError, SSOError, TokenRetrievalError

    try:
        sys.exit(main())
    except (TokenRetrievalError, SSOError, NoCredentialsError) as exc:
        # The SSO session lasts 8 hours (notes/TOKENS.md); say how to renew it, no traceback.
        log.error("AWS login needed (%s): run `aws sso login --profile pm25`", type(exc).__name__)
        sys.exit(3)
