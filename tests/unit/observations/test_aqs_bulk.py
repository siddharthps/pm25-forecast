"""AQS bulk history download (#11, T13): resumable, idempotent, private, quiet.

S3 is moto's in-memory fake; AQS is a fake fetch that counts calls and can fail on demand.
"""

import hashlib
import io
import json
import logging
import re
from collections import Counter
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import boto3
import pandas as pd
import pytest
from moto import mock_aws

from airwatch.observations.aqs_bulk import (
    MANIFEST_KEY,
    Part,
    plan_parts,
    run_download,
)
from airwatch.observations.schema import validate_hourly
from airwatch.storage import S3Store

BUCKET = "test-private-bucket"
SITES = ("040130019", "040131003")
TODAY = date(2026, 11, 19)
NOW = datetime(2026, 11, 19, 4, 0, tzinfo=UTC)
SECRET_VALUE = 987.6


@pytest.fixture
def store() -> Iterator[S3Store]:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        yield S3Store(s3, BUCKET)


def fake_rows(site: str, year: int) -> list[dict[str, Any]]:
    """Two hourly AQS rows for `site` in `year` (the second carries SECRET_VALUE)."""
    t = datetime(year, 3, 1, 12, tzinfo=UTC)
    return [
        {
            "state_code": site[:2],
            "county_code": site[2:5],
            "site_number": site[5:],
            "parameter_code": "88101",
            "poc": 1,
            "date_gmt": (t + timedelta(hours=h)).date().isoformat(),
            "time_gmt": (t + timedelta(hours=h)).strftime("%H:%M"),
            "sample_duration_code": "1",
            "sample_measurement": SECRET_VALUE if h else 8.0,
            "units_of_measure": "Micrograms/cubic meter (LC)",
            "method_code": "170",
            "method_type": "FEM",
            "qualifier": None,
            "date_of_last_change": f"{year + 1}-06-01",
        }
        for h in range(2)
    ]


class FakeAqs:
    """Counts calls per part; raises on the `fail_on`-th call (1-based) if set."""

    def __init__(self, fail_on: int | None = None) -> None:
        self.calls: Counter[tuple[str, int]] = Counter()
        self.n = 0
        self.fail_on = fail_on

    def __call__(self, site: str, year: int) -> list[dict[str, Any]]:
        self.n += 1
        if self.fail_on is not None and self.n == self.fail_on:
            raise RuntimeError("network down")
        self.calls[(site, year)] += 1
        return fake_rows(site, year)


def run(store: S3Store, fetch: Callable[[str, int], list[dict[str, Any]]], today: date = TODAY):
    return run_download(store, fetch, SITES, first_year=2024, today=today, now=lambda: NOW)


def manifest(store: S3Store) -> dict[str, Any]:
    raw = store.get(MANIFEST_KEY)
    assert raw is not None
    data: dict[str, Any] = json.loads(raw)
    return data


ALL_PARTS = {(s, y) for s in SITES for y in (2024, 2025, 2026)}


def test_parts_live_under_the_private_raw_prefix() -> None:
    p = Part("040130019", 2021)
    assert p.key == "raw/aqs/hourly/site=040130019/year=2021.parquet"
    assert MANIFEST_KEY.startswith("raw/")


def test_a_fresh_run_fetches_every_part_once(store: S3Store) -> None:
    fetch = FakeAqs()
    summary = run(store, fetch)
    assert set(fetch.calls) == ALL_PARTS
    assert set(fetch.calls.values()) == {1}
    m = manifest(store)
    assert {(e["site_id"], e["year"]) for e in m["parts"].values()} == ALL_PARTS
    assert summary.rows == 2 * len(ALL_PARTS)


def test_each_part_is_a_valid_parquet_file(store: S3Store) -> None:
    run(store, FakeAqs())
    raw = store.get(Part("040130019", 2025).key)
    assert raw is not None
    df = pd.read_parquet(io.BytesIO(raw))
    validate_hourly(df)
    assert len(df) == 2


def test_a_rerun_the_same_day_only_refreshes_the_current_year(store: S3Store) -> None:
    run(store, FakeAqs())
    again = FakeAqs()
    run(store, again)
    assert set(again.calls) == {(s, 2026) for s in SITES}


def test_an_interrupted_run_resumes_without_duplicates(store: S3Store) -> None:
    first = FakeAqs(fail_on=4)
    with pytest.raises(RuntimeError, match="network down"):
        run(store, first)
    second = FakeAqs()
    run(store, second)
    total = first.calls + second.calls
    assert all(total[p] == 1 for p in ALL_PARTS if p[1] < TODAY.year)
    assert {(e["site_id"], e["year"]) for e in manifest(store)["parts"].values()} == ALL_PARTS


def test_a_crash_between_data_and_manifest_is_repaired_by_a_rerun(store: S3Store) -> None:
    real_put = store.put
    calls = {"n": 0}

    def flaky_put(key: str, data: bytes) -> None:
        if key == MANIFEST_KEY:
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("S3 hiccup")
        real_put(key, data)

    store.put = flaky_put  # type: ignore[method-assign]
    with pytest.raises(OSError, match="hiccup"):
        run(store, FakeAqs())
    store.put = real_put  # type: ignore[method-assign]
    run(store, FakeAqs())
    m = manifest(store)
    assert {(e["site_id"], e["year"]) for e in m["parts"].values()} == ALL_PARTS
    for entry in m["parts"].values():
        assert store.get(entry["key"]) is not None


def test_the_manifest_never_claims_a_part_whose_data_write_failed(store: S3Store) -> None:
    real_put = store.put
    failing_key = Part(SITES[0], 2025).key

    def put_failing_data(key: str, data: bytes) -> None:
        if key == failing_key:
            raise OSError("S3 hiccup")
        real_put(key, data)

    store.put = put_failing_data  # type: ignore[method-assign]
    with pytest.raises(OSError, match="hiccup"):
        run(store, FakeAqs())
    store.put = real_put  # type: ignore[method-assign]
    raw = store.get(MANIFEST_KEY)
    parts = json.loads(raw)["parts"] if raw else {}
    assert failing_key not in parts
    for entry in parts.values():
        assert store.get(entry["key"]) is not None


def test_last_years_partial_part_becomes_final_next_year(store: S3Store) -> None:
    run(store, FakeAqs())
    assert manifest(store)["parts"][Part(SITES[0], 2026).key]["final"] is False
    later = FakeAqs()
    run(store, later, today=date(2027, 1, 5))
    assert (SITES[0], 2026) in later.calls
    assert manifest(store)["parts"][Part(SITES[0], 2026).key]["final"] is True


def test_plan_lists_only_missing_or_unfinished_parts() -> None:
    done = {
        Part("040130019", 2024).key: {"final": True},
        Part("040130019", 2026).key: {"final": False},
    }
    parts = plan_parts(("040130019",), first_year=2024, today=TODAY, manifest_parts=done)
    assert parts == [Part("040130019", 2025), Part("040130019", 2026)]


def test_manifest_records_checksum_rows_and_time(store: S3Store) -> None:
    run(store, FakeAqs())
    entry = manifest(store)["parts"][Part("040130019", 2024).key]
    assert entry["rows"] == 2
    assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
    assert entry["fetched_at_utc"] == NOW.isoformat()
    raw = store.get(entry["key"])
    assert raw is not None
    assert hashlib.sha256(raw).hexdigest() == entry["sha256"]


def test_logs_show_progress_but_never_measurements(
    store: S3Store, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        run(store, FakeAqs())
    assert "040130019" in caplog.text
    assert str(SECRET_VALUE) not in caplog.text


def test_a_year_with_no_data_is_recorded_as_done_with_zero_rows(store: S3Store) -> None:
    """Most monitors didn't exist in 2009: an empty year must still count as finished."""

    def empty(_site: str, _year: int) -> list[dict[str, Any]]:
        return []

    run(store, empty)
    entry = manifest(store)["parts"][Part(SITES[0], 2024).key]
    assert entry["rows"] == 0
    assert entry["final"] is True
    raw = store.get(entry["key"])
    assert raw is not None
    df = pd.read_parquet(io.BytesIO(raw))
    validate_hourly(df)
    assert df.empty
    again = FakeAqs()
    run(store, again)
    assert (SITES[0], 2024) not in again.calls


def test_out_of_range_readings_are_stored_and_counted(
    store: S3Store, caplog: pytest.LogCaptureFixture
) -> None:
    def with_spike(site: str, year: int) -> list[dict[str, Any]]:
        rows = fake_rows(site, year)
        rows[0]["sample_measurement"] = 1167.0
        return rows

    with caplog.at_level(logging.INFO):
        run(store, with_spike)
    entry = manifest(store)["parts"][Part(SITES[0], 2024).key]
    assert entry["outside_crude_range"] == 1
    assert entry["rows"] == 2
    raw = store.get(entry["key"])
    assert raw is not None
    assert pd.read_parquet(io.BytesIO(raw))["value_ug_m3"].max() == 1167.0
    assert "1 outside crude range" in caplog.text
    assert "1167" not in caplog.text
