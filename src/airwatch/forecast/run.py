"""The daily persistence forecast (#13, T6): issue, validate, record once, then publish.

    cd ~/code/pm25-forecast
    uv run python -m airwatch.forecast.run                         # dry run: writes nothing
    AWS_PROFILE=pm25 uv run python -m airwatch.forecast.run --publish

Rules (D-009 clarification, D-019, D-033, D-034):

- The forecast for target day D+1 is issued at 06:00 Chicago on D. A run before that is refused.
- **Persistence:** each monitor's forecast is its daily mean on D-1, the last complete local
  day (>= 18 of 24 hours, co-located instruments averaged per hour first).
- Only AirNow rows published by the issue time are used. AirNow rewrites each hourly file for
  about 7.7 hours, so a late run drops the rewritten hours and counts them.
- A monitor without a valid D-1 is listed with its hour count. No monitor at all: no record.
- Order: validation report, then the hard-failure stop, then the **record (at most once)**, then
  the public file. An existing record is reused, never recomputed, so a retry after any failure
  publishes the recorded forecast.
- **Fail loudly:** every failure raises, and the command exits 1 (Prefect marks the run failed,
  T8; email alerts come in T9). Logs carry counts and dates, never a value or a credential.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd

from airwatch.errors import ReportableError
from airwatch.forecast.publish import publish as publish_latest
from airwatch.forecast.publish import publish_history
from airwatch.forecast.record import Store, build_record, record_key, report_key, write_once
from airwatch.observations.aqs import daily_means
from airwatch.timeutil import ISSUE_TZ, ensure_utc, issue_time_utc, local_day_window_utc
from airwatch.validation.checks import Window, run_checks
from airwatch.validation.report import build_report

__all__ = [
    "NoForecastError",
    "Plan",
    "RunOutcome",
    "TooEarlyError",
    "day_means",
    "drop_after_issue",
    "latest_target_day",
    "main",
    "persistence",
    "plan_for",
    "run_daily",
]

log = logging.getLogger(__name__)

FetchDay = Callable[[date], tuple[pd.DataFrame, dict[str, int]]]
Status = Literal["dry_run", "recorded", "already_recorded"]


class TooEarlyError(ReportableError):
    """The run started before its issue time: D-1 isn't complete yet."""


class NoForecastError(ReportableError):
    """No monitor had a valid D-1, so there is nothing to forecast from (no record written)."""


@dataclass(frozen=True)
class Plan:
    target_day: date
    issue_at_utc: datetime
    issue_date: date
    observed_day: date


@dataclass(frozen=True)
class RunOutcome:
    status: Status
    record: dict[str, Any]
    published: bool


def plan_for(target_day: date) -> Plan:
    issue_at = issue_time_utc(target_day)
    return Plan(
        target_day=target_day,
        issue_at_utc=issue_at,
        issue_date=issue_at.astimezone(ISSUE_TZ).date(),
        observed_day=target_day - timedelta(days=2),
    )


def latest_target_day(now: datetime) -> date:
    """The target day whose issue time is the latest one at or before `now`."""
    today = ensure_utc(now).astimezone(ISSUE_TZ).date()
    tomorrow = today + timedelta(days=1)
    return tomorrow if ensure_utc(now) >= issue_time_utc(tomorrow) else today


def drop_after_issue(hourly: pd.DataFrame, issue_at_utc: datetime) -> tuple[pd.DataFrame, int]:
    """Rows published by the issue time, and how many later ones were dropped (D-034)."""
    late = hourly["available_at_utc"] > pd.Timestamp(ensure_utc(issue_at_utc))
    return hourly[~late].reset_index(drop=True), int(late.sum())


def day_means(
    hourly: pd.DataFrame, day: date, tz: ZoneInfo, sites: Iterable[str]
) -> tuple[dict[str, tuple[float, int]], dict[str, int]]:
    """Each site's valid mean over the local `day` (18+ hours), with its hours; and the hours of
    each site without a valid day. The one home of the daily rule for forecast and score."""
    start, end = local_day_window_utc(day, tz)
    in_day = hourly[(hourly["time_utc"] >= start) & (hourly["time_utc"] < end)]
    daily = daily_means(in_day, tz)
    valid = {
        str(site): (float(mean), int(n))
        for site, mean, n in daily[["site_id", "mean_ug_m3", "n_hours"]].itertuples(index=False)
    }
    hours = in_day.groupby("site_id")["time_utc"].nunique()
    wanted = sorted(set(sites))
    missing = {site: int(hours.get(site, 0)) for site in wanted if site not in valid}
    return {site: valid[site] for site in wanted if site in valid}, missing


def persistence(
    hourly: pd.DataFrame, observed_day: date, tz: ZoneInfo, sites: Iterable[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Each site's D-1 daily mean as its forecast; the sites without a valid day, with hours."""
    valid, missing = day_means(hourly, observed_day, tz, sites)
    forecasts = [
        {"site_id": site, "forecast_ug_m3": mean, "n_hours": n} for site, (mean, n) in valid.items()
    ]
    return forecasts, [{"site_id": site, "n_hours": n} for site, n in missing.items()]


def _encode(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _publish_all(public: Store, private: Store, record: dict[str, Any]) -> bool:
    """latest.json, then history.json (rebuilt from the records). True if latest changed."""
    latest = publish_latest(public, record)
    publish_history(public, private)
    return latest


def run_daily(  # noqa: PLR0913  (each argument is one injected edge or the run's context)
    target_day: date,
    *,
    fetch_day: FetchDay,
    private: Store,
    public: Store,
    now: Callable[[], datetime],
    tz: ZoneInfo,
    sites: Sequence[str],
    publish: bool,
) -> RunOutcome:
    """One daily run. `publish=False` is a dry run: it computes, and writes nothing anywhere."""
    plan = plan_for(target_day)
    started = ensure_utc(now())
    if started < plan.issue_at_utc:
        raise TooEarlyError(f"{target_day}: issue time {plan.issue_at_utc.isoformat()} not reached")

    existing = private.get(record_key(target_day))
    if existing is not None:
        record: dict[str, Any] = json.loads(existing)
        published = publish and _publish_all(public, private, record)
        log.info("%s: record exists; reused (published: %s)", target_day, published)
        return RunOutcome("already_recorded", record, published)

    hourly, drops = fetch_day(plan.observed_day)
    hourly, late = drop_after_issue(hourly, plan.issue_at_utc)
    window = Window(*local_day_window_utc(plan.observed_day, tz))
    result = run_checks(
        hourly,
        window=window,
        tz=tz,
        sites=sites,
        ingest_drops={**drops, "published_after_issue": late},
    )
    if publish:
        report = build_report(result, source="airnow", window=window, generated_at_utc=started)
        private.put(report_key(target_day), _encode(report))
    result.raise_if_failed()

    forecasts, missing = persistence(result.clean, plan.observed_day, tz, sites)
    if not forecasts:
        raise NoForecastError(f"{target_day}: no monitor has a valid {plan.observed_day}")
    record = build_record(
        target_day=target_day,
        issue_at_utc=plan.issue_at_utc,
        observed_day=plan.observed_day,
        generated_at_utc=started,
        city_tz=str(tz),
        forecasts=forecasts,
        no_forecast=missing,
        validation=result,
        inputs={"rows": result.rows_in, "dropped_published_after_issue": late, "drops": drops},
    )
    if not publish:
        log.info("%s: dry run, %d monitor(s) forecast; nothing written", target_day, len(forecasts))
        return RunOutcome("dry_run", record, published=False)

    created, record = write_once(private, record)
    published = _publish_all(public, private, record)
    log.info(
        "%s: %s, %d monitor(s), %d without a valid day (published: %s)",
        target_day,
        "recorded" if created else "another run's record reused",
        len(record["forecasts"]),
        len(record["no_forecast"]),
        published,
    )
    return RunOutcome("recorded" if created else "already_recorded", record, published)


def failure_line(target: date, exc: BaseException) -> str:
    """The log line for a failed run: always the type; the message only if it's ours (#56)."""
    line = f"{target}: forecast FAILED: {type(exc).__name__}"
    return f"{line}: {exc}" if isinstance(exc, ReportableError) else line


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover  (real edges only)
    import boto3  # noqa: PLC0415
    import httpx  # noqa: PLC0415

    from airwatch.config import get_settings  # noqa: PLC0415
    from airwatch.observations.airnow import fetch_local_day  # noqa: PLC0415
    from airwatch.observations.sites import TRAINING_SITES  # noqa: PLC0415
    from airwatch.storage import S3Store  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Daily persistence forecast (dry run by default).")
    parser.add_argument("--target-day", type=date.fromisoformat, help="default: the latest due")
    parser.add_argument("--publish", action="store_true", help="write the record and public file")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    for name in ("botocore", "boto3", "urllib3"):
        logging.getLogger(name).setLevel(logging.ERROR)

    settings = get_settings()
    now = datetime.now(UTC)
    target = args.target_day or latest_target_day(now)
    session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
    s3 = session.client("s3")
    with httpx.Client(timeout=60) as client:
        try:
            outcome = run_daily(
                target,
                fetch_day=lambda d: fetch_local_day(client, d, settings.city_tz, TRAINING_SITES),
                private=S3Store(s3, settings.data_bucket),
                public=S3Store(s3, settings.public_bucket),
                now=lambda: datetime.now(UTC),
                tz=settings.city_tz,
                sites=TRAINING_SITES,
                publish=args.publish,
            )
        except Exception as exc:
            log.error(failure_line(target, exc))
            return 1
    log.info("%s: %s", target, outcome.status)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
