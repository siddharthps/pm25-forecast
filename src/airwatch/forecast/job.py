"""The scheduled job: forecast, scores, CAMS as issued, then the minutes (D-040, D-042, D-053).

This is what the Prefect flow calls. It builds the real edges (S3 through the run's federated AWS
credentials, AirNow's public hourly files) unless a test hands in fakes, and then:

1. runs the forecast (recorded and published once);
2. scores every settled day not yet scored, and rebuilds `history.json` so the new scores go
   public. That happens even if a day failed to score, so the others still appear. Scoring comes
   after the forecast, so a scoring failure can never stop or undo that morning's forecast;
3. saves CAMS's forecast for the target day as issued (#78), even if scoring failed; a failure
   here is logged by type and fails the run, after the forecast and scores are done;
4. always files the run's minutes, even when a step fails, before the failure is re-raised.
"""

import logging
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from airwatch.config import Settings
from airwatch.forecast.publish import publish_history
from airwatch.forecast.run import RunOutcome, latest_target_day, run_daily
from airwatch.monitoring.compute import MONTHLY_ALERT_MIN, MONTHLY_FREE_MIN, Usage, record_run
from airwatch.monitoring.score import ScoreOutcome, score_due
from airwatch.observations.sites import TRAINING_SITES
from airwatch.storage import S3Store
from airwatch.weather.cams_save import FetchCams, SaveOutcome, save_cams

__all__ = ["JobOutcome", "daily_job"]

log = logging.getLogger(__name__)

FetchDay = Callable[[date], tuple[pd.DataFrame, dict[str, int]]]


@dataclass(frozen=True)
class JobOutcome:
    run: RunOutcome
    usage: Usage
    scores: tuple[ScoreOutcome, ...] = ()
    cams: SaveOutcome | None = None


def _real_s3(settings: Settings) -> Any:  # pragma: no cover  (real AWS only)
    import boto3  # noqa: PLC0415

    session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
    return session.client("s3")


def _real_fetch(
    settings: Settings, stack: ExitStack, sites: Iterable[str]
) -> FetchDay:  # pragma: no cover
    import httpx  # noqa: PLC0415

    from airwatch.observations.airnow import fetch_local_day  # noqa: PLC0415

    client = stack.enter_context(httpx.Client(timeout=60))
    wanted = tuple(sites)
    return lambda d: fetch_local_day(client, d, settings.city_tz, wanted)


def _real_cams(
    settings: Settings, stack: ExitStack, now: Callable[[], datetime]
) -> FetchCams:  # pragma: no cover  (real Open-Meteo only)
    import httpx  # noqa: PLC0415

    from airwatch.weather.cams import CamsQuery, fetch_live  # noqa: PLC0415

    client = stack.enter_context(httpx.Client(timeout=60))
    return lambda site, target: fetch_live(
        client, CamsQuery.live_for(site, target, settings.city_tz), now=now
    )


def _save_cams_logged(target: date, **kwargs: Any) -> SaveOutcome:
    try:
        outcome = save_cams(target, **kwargs)
    except Exception as exc:
        log.error("%s: CAMS save failed (%s)", target, type(exc).__name__)
        raise
    log.info("%s: CAMS %s", target, outcome.status)
    return outcome


def _log_usage(usage: Usage) -> None:
    line = "compute: this run about %d min; this month %d of %d free min (alert line %d)"
    args = (usage.minutes, usage.month_total, MONTHLY_FREE_MIN, MONTHLY_ALERT_MIN)
    if usage.over_alert:
        log.warning(line + ": OVER THE ALERT LINE", *args)
    else:
        log.info(line, *args)


def daily_job(  # noqa: PLR0913  (each argument is one injected edge or the run's context)
    settings: Settings,
    *,
    run_id: str,
    scheduled_start: datetime,
    publish: bool,
    target_day: date | None = None,
    s3: Any = None,
    fetch_day: FetchDay | None = None,
    fetch_cams: FetchCams | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sites: Iterable[str] = TRAINING_SITES,
) -> JobOutcome:
    """Forecast, score, save CAMS (dry runs unless `publish`), then file this run's minutes."""
    client = s3 if s3 is not None else _real_s3(settings)
    private = S3Store(client, settings.data_bucket)
    public = S3Store(client, settings.public_bucket)
    wanted = tuple(sites)
    with ExitStack() as stack:
        fetch = fetch_day if fetch_day is not None else _real_fetch(settings, stack, wanted)
        cams_fetch = fetch_cams if fetch_cams is not None else _real_cams(settings, stack, now)
        target = target_day or latest_target_day(now())
        try:
            run = run_daily(
                target,
                fetch_day=fetch,
                private=private,
                public=public,
                now=now,
                tz=settings.city_tz,
                sites=wanted,
                publish=publish,
            )
            try:
                try:
                    scores = score_due(
                        fetch_day=fetch, private=private, sites=wanted, now=now, write=publish
                    )
                finally:
                    if publish:
                        publish_history(public, private)
            finally:
                cams = _save_cams_logged(
                    target,
                    fetch_cams=cams_fetch,
                    private=private,
                    sites=wanted,
                    tz=settings.city_tz,
                    now=now,
                    write=publish,
                )
        finally:
            usage = record_run(private, run_id, scheduled_start, now())
            _log_usage(usage)
    log.info("%s: %s", target, run.status)
    return JobOutcome(run=run, usage=usage, scores=tuple(scores), cams=cams)
