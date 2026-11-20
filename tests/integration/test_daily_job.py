"""The scheduled job: the forecast, then the compute ledger, even when the forecast fails.

moto stands in for both buckets; AirNow is a fake fetch; the clock is frozen (#15, T8; D-040).
"""

import logging
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import boto3
import pytest
from moto import mock_aws

from airwatch.config import Settings
from airwatch.forecast.job import daily_job
from airwatch.forecast.publish import LATEST_KEY
from airwatch.forecast.record import record_key
from airwatch.forecast.run import NoForecastError
from airwatch.monitoring.compute import MONTHLY_ALERT_MIN, PREFIX, TEARDOWN_PAD_MIN, record_run
from airwatch.storage import S3Store
from tests.unit.forecast.fakes import (
    ISSUE_AT,
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
