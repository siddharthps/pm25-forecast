"""The daily forecast acts at most once (#13, T6; SPEC § Testing: "at most one publish").

moto stands in for both buckets (versioned, so every write leaves a countable version); the
clock is frozen; AirNow is a fake fetch. The rules:

- running twice for one target day writes exactly one record version;
- making each step fail in turn writes at most one record and never a public file without a
  record, and a rerun afterwards completes with still exactly one record;
- the record comes first: a racing writer's record wins, and is what gets published;
- a manual run is a dry run unless told to publish, and writes nothing at all.
"""

import json
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta
from typing import Any

import boto3
import pandas as pd
import pytest
from moto import mock_aws

from airwatch.forecast.publish import HISTORY_KEY, LATEST_KEY
from airwatch.forecast.record import record_key, report_key
from airwatch.forecast.run import NoForecastError, RunOutcome, TooEarlyError, run_daily
from airwatch.storage import S3Store
from airwatch.validation.checks import ValidationFailedError
from tests.unit.forecast.fakes import (
    ISSUE_AT,
    OBSERVED,
    PHOENIX,
    PRIVATE,
    PUBLIC,
    SITES,
    TARGET,
    fetcher,
    object_versions,
    observed_day,
)
from tests.unit.validation.helpers import concat

NOW = ISSUE_AT + timedelta(minutes=5)
RECORD, REPORT = record_key(TARGET), report_key(TARGET)


@pytest.fixture(scope="module")
def aws() -> Iterator[Any]:
    """One fake AWS per worker for this file (starting moto costs ~0.4 s); emptied per test."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        for bucket in (PRIVATE, PUBLIC):
            client.create_bucket(Bucket=bucket)
            client.put_bucket_versioning(
                Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
            )
        yield client


@pytest.fixture
def s3(aws: Any) -> Iterator[Any]:
    for bucket in (PRIVATE, PUBLIC):
        listing = aws.list_object_versions(Bucket=bucket)
        for v in listing.get("Versions", []) + listing.get("DeleteMarkers", []):
            aws.delete_object(Bucket=bucket, Key=v["Key"], VersionId=v["VersionId"])
        assert not aws.list_object_versions(Bucket=bucket).get("Versions")
    yield aws


class Failing(S3Store):
    """An S3Store whose writes to keys starting with `prefix` raise, until `healed`."""

    def __init__(self, client: Any, bucket: str, prefix: str) -> None:
        super().__init__(client, bucket, retry_pause_s=0)
        self.prefix, self.healed = prefix, False

    def _check(self, key: str) -> None:
        if not self.healed and key.startswith(self.prefix):
            raise RuntimeError("storage down")

    def put(self, key: str, data: bytes) -> None:
        self._check(key)
        super().put(key, data)

    def create_if_absent(self, key: str, data: bytes) -> bool:
        self._check(key)
        return super().create_if_absent(key, data)


def run(  # noqa: PLR0913  (each argument is one injected edge)
    s3: Any,
    *,
    fetch: Callable[[date], tuple[pd.DataFrame, dict[str, int]]] | None = None,
    private: S3Store | None = None,
    public: S3Store | None = None,
    now: datetime = NOW,
    publish: bool = True,
    target: date = TARGET,
) -> RunOutcome:
    return run_daily(
        target,
        fetch_day=fetch or fetcher(observed_day()),
        private=private or S3Store(s3, PRIVATE),
        public=public or S3Store(s3, PUBLIC),
        now=lambda: now,
        tz=PHOENIX,
        sites=SITES,
        publish=publish,
    )


def stored(s3: Any, bucket: str, key: str) -> dict[str, Any] | None:
    raw = S3Store(s3, bucket).get(key)
    return None if raw is None else json.loads(raw)


def keys(s3: Any, bucket: str) -> list[str]:
    return sorted(o["Key"] for o in s3.list_objects_v2(Bucket=bucket).get("Contents", []))


def test_a_first_run_records_then_publishes(s3: Any) -> None:
    outcome = run(s3)
    assert outcome.status == "recorded"
    record = stored(s3, PRIVATE, RECORD)
    assert record == outcome.record
    assert record is not None
    assert record["forecast_date"] == "2026-11-21"
    assert record["issued_at_utc"] == "2026-11-20T12:00:00+00:00"
    assert record["observed_day"] == "2026-11-19"
    assert record["method"] == "persistence"
    assert [f["site_id"] for f in record["forecasts"]] == list(SITES)
    latest = stored(s3, PUBLIC, LATEST_KEY)
    assert latest is not None
    assert latest["forecast_date"] == "2026-11-21"
    assert [f["site_id"] for f in latest["forecasts"]] == list(SITES)


def test_running_twice_writes_one_record_and_one_public_file(s3: Any) -> None:
    fetch = fetcher(observed_day())
    first = run(s3, fetch=fetch)
    second = run(s3, fetch=fetch, now=NOW + timedelta(hours=2))
    assert (first.status, second.status) == ("recorded", "already_recorded")
    assert second.record == first.record
    assert fetch.calls == 1  # type: ignore[attr-defined]
    assert object_versions(s3, PRIVATE, RECORD) == 1
    assert object_versions(s3, PUBLIC, LATEST_KEY) == 1
    assert object_versions(s3, PUBLIC, HISTORY_KEY) == 1


def _fetch_down(_: date) -> tuple[pd.DataFrame, dict[str, int]]:
    raise RuntimeError("AirNow down")


STEPS = ["fetch", "validate", "compute", "report", "record", "publish"]


@pytest.mark.parametrize("step", STEPS)
def test_a_failure_at_any_step_acts_at_most_once(s3: Any, step: str) -> None:
    df = observed_day()
    fetch = fetcher(df)
    private: S3Store = S3Store(s3, PRIVATE)
    public: S3Store = S3Store(s3, PUBLIC)
    if step == "fetch":
        fetch = _fetch_down
    elif step == "validate":
        fetch = fetcher(concat(df, df.iloc[[0]]))
    elif step == "compute":
        fetch = fetcher(observed_day({SITES[0]: 10, SITES[1]: 10}))
    elif step in ("report", "record"):
        private = Failing(s3, PRIVATE, "reports/" if step == "report" else "records/")
    else:
        public = Failing(s3, PUBLIC, "")

    with pytest.raises((RuntimeError, ValidationFailedError, NoForecastError)):
        run(s3, fetch=fetch, private=private, public=public)

    assert object_versions(s3, PRIVATE, RECORD) == (1 if step == "publish" else 0)
    if stored(s3, PUBLIC, LATEST_KEY) is not None:
        assert stored(s3, PRIVATE, RECORD) is not None
    assert stored(s3, PUBLIC, LATEST_KEY) is None

    outcome = run(s3, fetch=fetcher(df), now=NOW + timedelta(minutes=30))
    assert outcome.status == ("already_recorded" if step == "publish" else "recorded")
    assert object_versions(s3, PRIVATE, RECORD) == 1
    assert object_versions(s3, PUBLIC, LATEST_KEY) == 1
    latest = stored(s3, PUBLIC, LATEST_KEY)
    assert latest is not None
    assert latest["issued_at_utc"] == outcome.record["issued_at_utc"]


def test_a_hard_validation_failure_still_saves_its_report(s3: Any) -> None:
    df = observed_day()
    with pytest.raises(ValidationFailedError):
        run(s3, fetch=fetcher(concat(df, df.iloc[[0]])))
    report = stored(s3, PRIVATE, REPORT)
    assert report is not None
    assert report["passed"] is False
    assert keys(s3, PRIVATE) == [REPORT]


def test_no_qualifying_monitor_writes_no_record(s3: Any) -> None:
    with pytest.raises(NoForecastError, match="no monitor"):
        run(s3, fetch=fetcher(observed_day({SITES[0]: 0, SITES[1]: 17})))
    assert keys(s3, PRIVATE) == [REPORT]
    assert keys(s3, PUBLIC) == []


class Racing(S3Store):
    """Another run's record lands between our check and our write."""

    def __init__(self, client: Any, bucket: str, theirs: dict[str, Any]) -> None:
        super().__init__(client, bucket)
        self.theirs = theirs

    def create_if_absent(self, key: str, data: bytes) -> bool:
        super().create_if_absent(key, json.dumps(self.theirs).encode())
        return super().create_if_absent(key, data)


def test_a_racing_writers_record_wins_and_is_what_gets_published(s3: Any) -> None:
    theirs = run(s3, publish=False).record | {"generated_at_utc": "2026-11-20T12:01:00+00:00"}
    outcome = run(s3, private=Racing(s3, PRIVATE, theirs))
    assert outcome.status == "already_recorded"
    assert outcome.record == theirs
    assert stored(s3, PRIVATE, RECORD) == theirs
    assert object_versions(s3, PRIVATE, RECORD) == 1


def test_the_public_file_never_moves_back_to_an_older_day(s3: Any) -> None:
    run(s3)
    older = TARGET - timedelta(days=1)
    older_day = fetcher(
        observed_day(
            day=OBSERVED - timedelta(days=1), available_at=ISSUE_AT - timedelta(days=1, hours=3)
        ),
        day=OBSERVED - timedelta(days=1),
    )
    run(s3, target=older, fetch=older_day)
    latest = stored(s3, PUBLIC, LATEST_KEY)
    assert latest is not None
    assert latest["forecast_date"] == TARGET.isoformat()
    assert stored(s3, PRIVATE, record_key(older)) is not None


def test_a_dry_run_writes_nothing_anywhere(s3: Any) -> None:
    outcome = run(s3, publish=False)
    assert outcome.status == "dry_run"
    assert outcome.record["forecasts"]
    assert keys(s3, PRIVATE) == []
    assert keys(s3, PUBLIC) == []


def test_a_dry_run_after_the_record_exists_still_writes_nothing(s3: Any) -> None:
    run(s3)
    older = json.dumps({"forecast_date": "2026-11-20"}).encode()
    S3Store(s3, PUBLIC).put(LATEST_KEY, older)
    outcome = run(s3, publish=False, now=NOW + timedelta(hours=1))
    assert outcome.status == "already_recorded"
    assert not outcome.published
    assert S3Store(s3, PUBLIC).get(LATEST_KEY) == older


def test_a_run_exactly_at_the_issue_time_goes_ahead(s3: Any) -> None:
    assert run(s3, now=ISSUE_AT).status == "recorded"


def test_a_run_before_the_issue_time_is_refused(s3: Any) -> None:
    fetch = fetcher(observed_day())
    with pytest.raises(TooEarlyError):
        run(s3, fetch=fetch, now=ISSUE_AT - timedelta(seconds=1))
    assert fetch.calls == 0  # type: ignore[attr-defined]
    assert keys(s3, PRIVATE) == []


def test_a_late_run_drops_hours_rewritten_after_the_issue_time(s3: Any) -> None:
    on_time = observed_day()
    late_hours = on_time["time_utc"] >= on_time["time_utc"].max() - pd.Timedelta(hours=1)
    df = on_time.copy()
    df.loc[late_hours, "available_at_utc"] = pd.Timestamp(ISSUE_AT + timedelta(hours=2))
    outcome = run(s3, fetch=fetcher(df), now=ISSUE_AT + timedelta(hours=3))
    record = outcome.record
    assert record["inputs"]["dropped_published_after_issue"] == int(late_hours.sum())
    assert record["validation"]["counts"]["airnow_rows_dropped"] == int(late_hours.sum())
    assert all(f["n_hours"] == 22 for f in record["forecasts"])


def test_the_validation_summary_is_in_the_record(s3: Any) -> None:
    record = run(s3, fetch=fetcher(observed_day(), {"unmatched_site": 7})).record
    assert record["validation"]["passed"] is True
    assert record["validation"]["counts"]["airnow_unmatched_site"] == 7


def test_the_next_days_forecast_replaces_the_public_file(s3: Any) -> None:
    run(s3)
    newer = TARGET + timedelta(days=1)
    next_day = fetcher(
        observed_day(day=OBSERVED + timedelta(days=1), available_at=ISSUE_AT + timedelta(hours=21)),
        day=OBSERVED + timedelta(days=1),
    )
    run(s3, target=newer, fetch=next_day, now=NOW + timedelta(days=1))
    latest = stored(s3, PUBLIC, LATEST_KEY)
    assert latest is not None
    assert latest["forecast_date"] == newer.isoformat()
    assert object_versions(s3, PUBLIC, LATEST_KEY) == 2
