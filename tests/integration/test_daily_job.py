"""The scheduled job: the forecast, then the compute ledger, even when the forecast fails.

moto stands in for both buckets; AirNow is a fake fetch; the clock is frozen (#15, T8; D-040).
"""

import json
import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import boto3
import pytest
from moto import mock_aws

from airwatch.config import Settings
from airwatch.forecast.job import daily_job
from airwatch.forecast.publish import HISTORY_KEY, LATEST_KEY
from airwatch.forecast.record import record_key, score_key
from airwatch.forecast.run import NoForecastError
from airwatch.monitoring.compute import MONTHLY_ALERT_MIN, PREFIX, TEARDOWN_PAD_MIN, record_run
from airwatch.monitoring.score import ScoringError
from airwatch.storage import S3Store
from airwatch.timeutil import local_day_window_utc
from tests.unit.forecast.fakes import (
    ISSUE_AT,
    PHOENIX,
    PRIVATE,
    PUBLIC,
    SITES,
    TARGET,
    fetcher,
    object_versions,
    observed_day,
)

RUN = "0f8c2a5e-6a3b-4b9e-9a51-3d2f0c7e1b44"
NOW = ISSUE_AT + timedelta(minutes=4)


@pytest.fixture
def s3() -> Iterator[Any]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        for bucket in (PRIVATE, PUBLIC):
            client.create_bucket(Bucket=bucket)
            client.put_bucket_versioning(
                Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
            )
        yield client


def _job(s3: Any, *, publish: bool, fetch: Any = None, run_id: str = RUN) -> Any:
    return daily_job(
        Settings(_env_file=None, data_bucket=PRIVATE, public_bucket=PUBLIC),
        run_id=run_id,
        scheduled_start=ISSUE_AT,
        publish=publish,
        s3=s3,
        fetch_day=fetch or fetcher(observed_day()),
        now=lambda: NOW,
        sites=SITES,
    )


def _ledger(s3: Any) -> list[str]:
    return S3Store(s3, PRIVATE).list_keys(PREFIX)


def test_a_scheduled_run_forecasts_publishes_and_logs_its_minutes(s3: Any) -> None:
    outcome = _job(s3, publish=True)
    assert outcome.run.status == "recorded"
    assert object_versions(s3, PRIVATE, record_key(TARGET)) == 1
    assert object_versions(s3, PUBLIC, LATEST_KEY) == 1
    assert outcome.usage.minutes == 4 + TEARDOWN_PAD_MIN
    assert _ledger(s3) == [f"{PREFIX}month=2026-11/run={RUN}.json"]


def test_the_target_defaults_to_the_latest_due(s3: Any) -> None:
    assert _job(s3, publish=True).run.record["forecast_date"] == TARGET.isoformat()


def test_a_manual_dry_run_writes_only_its_minutes(s3: Any) -> None:
    outcome = _job(s3, publish=False)
    assert outcome.run.status == "dry_run"
    assert object_versions(s3, PRIVATE, record_key(TARGET)) == 0
    assert S3Store(s3, PUBLIC).list_keys("") == []
    assert len(_ledger(s3)) == 1


def test_a_failed_forecast_still_logs_its_minutes_and_then_fails(s3: Any) -> None:
    empty = fetcher(observed_day({SITES[0]: 10, SITES[1]: 10}))
    with pytest.raises(NoForecastError):
        _job(s3, publish=True, fetch=empty)
    assert len(_ledger(s3)) == 1
    assert object_versions(s3, PRIVATE, record_key(TARGET)) == 0


def test_a_prefect_retry_of_the_same_run_acts_once(s3: Any) -> None:
    _job(s3, publish=True)
    again = _job(s3, publish=True)
    assert again.run.status == "already_recorded"
    assert object_versions(s3, PRIVATE, record_key(TARGET)) == 1
    assert len(_ledger(s3)) == 1
    assert again.usage.month_total == again.usage.minutes


def test_a_month_over_the_alert_line_logs_a_warning(
    s3: Any, caplog: pytest.LogCaptureFixture
) -> None:
    earlier = "11111111-2222-4333-8444-555555555555"
    record_run(
        S3Store(s3, PRIVATE), earlier, ISSUE_AT, ISSUE_AT + timedelta(minutes=MONTHLY_ALERT_MIN)
    )
    with caplog.at_level(logging.INFO, logger="airwatch"):
        outcome = _job(s3, publish=False)
    assert outcome.usage.over_alert is True
    assert any(
        r.levelno == logging.WARNING and "OVER THE ALERT LINE" in r.getMessage()
        for r in caplog.records
    )


SCORED_DAY = TARGET
LATER = datetime(2026, 11, 23, 6, 4, tzinfo=ZoneInfo("America/Chicago")).astimezone(UTC)


def _fetch_days(fail: set[date] | None = None) -> Any:
    """AirNow for each day asked; `fail` days raise, like an unreachable AirNow."""

    def fetch(day: date) -> Any:
        if day in (fail or set()):
            raise ConnectionError("AirNow unreachable")
        published = local_day_window_utc(day, PHOENIX)[1] + timedelta(hours=3)
        return observed_day(day=day, available_at=published), {}

    return fetch


def _later_job(s3: Any, *, publish: bool, fail: set[date] | None = None) -> Any:
    return daily_job(
        Settings(_env_file=None, data_bucket=PRIVATE, public_bucket=PUBLIC),
        run_id="22222222-3333-4444-8555-666666666666",
        scheduled_start=LATER,
        publish=publish,
        s3=s3,
        fetch_day=_fetch_days(fail),
        now=lambda: LATER,
        sites=SITES,
    )


def test_the_t_plus_2_run_scores_the_day_and_republishes_history(s3: Any) -> None:
    _job(s3, publish=True)
    outcome = _later_job(s3, publish=True)
    assert outcome.run.record["forecast_date"] == "2026-11-24"
    assert [s.status for s in outcome.scores if s.day == SCORED_DAY] == ["scored"]
    assert object_versions(s3, PRIVATE, score_key(SCORED_DAY)) == 1
    history = json.loads(S3Store(s3, PUBLIC).get(HISTORY_KEY) or b"")
    days = {d["forecast_date"]: d for d in history["days"]}
    assert days["2026-11-21"]["score"]["n_scored"] == len(SITES)
    assert "score" not in days["2026-11-24"]


def test_a_failed_score_fails_the_run_but_never_its_forecast(s3: Any) -> None:
    _job(s3, publish=True)
    with pytest.raises(ScoringError, match="2026-11-21"):
        _later_job(s3, publish=True, fail={SCORED_DAY})
    assert object_versions(s3, PRIVATE, record_key(date(2026, 11, 24))) == 1
    latest = json.loads(S3Store(s3, PUBLIC).get(LATEST_KEY) or b"")
    assert latest["forecast_date"] == "2026-11-24"
    assert object_versions(s3, PRIVATE, score_key(SCORED_DAY)) == 0
    assert len(_ledger(s3)) == 2


def test_a_dry_run_scores_but_writes_no_score(s3: Any) -> None:
    _job(s3, publish=True)
    outcome = _later_job(s3, publish=False)
    assert [s.status for s in outcome.scores if s.day == SCORED_DAY] == ["dry_run"]
    assert object_versions(s3, PRIVATE, score_key(SCORED_DAY)) == 0


def test_a_rerun_scores_nothing_twice(s3: Any) -> None:
    _job(s3, publish=True)
    _later_job(s3, publish=True)
    history_versions = object_versions(s3, PUBLIC, HISTORY_KEY)
    again = _later_job(s3, publish=True)
    assert [s.status for s in again.scores if s.day == SCORED_DAY] == ["already_scored"]
    assert object_versions(s3, PRIVATE, score_key(SCORED_DAY)) == 1
    assert object_versions(s3, PUBLIC, HISTORY_KEY) == history_versions
