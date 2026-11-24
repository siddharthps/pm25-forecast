"""Weather bulk download (#19, T14; D-051): resumable, idempotent, private, quiet, paced.

The bucket is the in-memory `MemoryStore` (one test runs the real `S3Store` on moto); Open-Meteo
is a fake fetch that counts calls and can fail on demand.
"""

import io
import json
import logging
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import boto3
import pandas as pd
import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from moto import mock_aws

from airwatch.storage import S3Store
from airwatch.weather.bulk import (
    ARCHIVE_START,
    BUDGET,
    ERA5_YEARS,
    FREE_LIMITS,
    MANIFEST_KEY,
    CallBudget,
    Part,
    call_weight,
    plan_parts,
    run_download,
)
from airwatch.weather.openmeteo import COLUMNS, VARIABLES, Source
from tests.unit.forecast.fakes import MemoryStore

BUCKET = "test-private-bucket"
SITES = ("040130019", "040131003")
TODAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 24, 4, 0, tzinfo=UTC)
SECRET_VALUE = 987.625
SMALL_ERA5 = range(2023, 2025)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def s3_store() -> Iterator[S3Store]:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        yield S3Store(s3, BUCKET)


def frame(part: Part) -> pd.DataFrame:
    """Two rows for `part`; the second holds SECRET_VALUE and one missing value."""
    start, _ = part.days(TODAY)
    t = datetime(start.year, start.month, start.day, tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    for h, value in enumerate((1.0, SECRET_VALUE)):
        row: dict[str, Any] = {
            "site_id": part.site_id,
            "valid_utc": t + timedelta(hours=h),
            "source": part.source.value,
            "run_start_utc": None,
            "available_at_utc": NOW,
        }
        row.update(dict.fromkeys(VARIABLES, value))
        rows.append(row)
    rows[1]["cloud_cover"] = None
    df = pd.DataFrame(rows, columns=list(COLUMNS))
    for column in ("valid_utc", "run_start_utc", "available_at_utc"):
        df[column] = pd.to_datetime(df[column], utc=True)
    return df


class FakeOpenMeteo:
    def __init__(self, fail_on: Part | None = None) -> None:
        self.calls: list[Part] = []
        self.fail_on = fail_on

    def __call__(self, part: Part) -> pd.DataFrame:
        self.calls.append(part)
        if part == self.fail_on:
            raise OSError("network down")
        return frame(part)


class RecordingPace:
    def __init__(self) -> None:
        self.weights: list[float] = []

    def __call__(self, weight: float) -> None:
        self.weights.append(weight)


def run(
    store: MemoryStore | S3Store,
    fetch: FakeOpenMeteo,
    *,
    today: date = TODAY,
    pace: RecordingPace | None = None,
) -> None:
    run_download(
        store,
        fetch,
        SITES,
        today=today,
        now=lambda: NOW,
        pace=pace or RecordingPace(),
        era5_years=SMALL_ERA5,
    )


def manifest(store: MemoryStore | S3Store) -> dict[str, Any]:
    raw = store.get(MANIFEST_KEY)
    assert raw is not None
    loaded: dict[str, Any] = json.loads(raw)
    return loaded


def all_parts(today: date = TODAY) -> set[Part]:
    return set(plan_parts(SITES, today=today, manifest_parts={}, era5_years=SMALL_ERA5))


def test_the_real_plan_is_d051s() -> None:
    assert range(2009, 2025) == ERA5_YEARS
    assert date(2024, 1, 20) == ARCHIVE_START
    parts = plan_parts(("040130019",), today=TODAY, manifest_parts={})
    assert [(p.source, p.year) for p in parts] == [
        *((Source.ERA5, y) for y in range(2009, 2025)),
        (Source.GFS_ARCHIVE, 2024),
        (Source.GFS_ARCHIVE, 2025),
        (Source.GFS_ARCHIVE, 2026),
    ]


def test_parts_live_under_the_private_raw_prefix() -> None:
    assert (
        Part(Source.ERA5, "040130019", 2009).key
        == "raw/weather/source=era5/site=040130019/year=2009.parquet"
    )
    assert MANIFEST_KEY == "raw/weather/manifest.json"


@pytest.mark.parametrize(
    ("part", "days"),
    [
        (Part(Source.ERA5, "040130019", 2012), (date(2012, 1, 1), date(2012, 12, 31))),
        (Part(Source.GFS_ARCHIVE, "040130019", 2024), (ARCHIVE_START, date(2024, 12, 31))),
        (Part(Source.GFS_ARCHIVE, "040130019", 2025), (date(2025, 1, 1), date(2025, 12, 31))),
        (Part(Source.GFS_ARCHIVE, "040130019", 2026), (date(2026, 1, 1), date(2026, 11, 23))),
    ],
    ids=["era5", "archive-first-year", "archive-past-year", "archive-this-year-to-yesterday"],
)
def test_a_part_spans_its_year(part: Part, days: tuple[date, date]) -> None:
    assert part.days(TODAY) == days


@pytest.mark.parametrize(
    ("days", "variables", "weight"),
    [(14, 10, 1.0), (14, 15, 1.5), (28, 15, 3.0), (1, 8, 1.0), (365, 8, 365 / 14)],
    ids=["one-call", "pricing-example-2-weeks", "pricing-example-4-weeks", "small", "a-year"],
)
def test_call_weight_matches_open_meteos_examples(days: int, variables: int, weight: float) -> None:
    assert call_weight(days, variables) == pytest.approx(weight)


def test_a_fresh_run_fetches_every_part_once(store: MemoryStore) -> None:
    fake = FakeOpenMeteo()
    run(store, fake)
    assert sorted(fake.calls) == sorted(all_parts())
    assert len(fake.calls) == len(set(fake.calls))
    assert {e["key"] for e in manifest(store)["parts"].values()} == {p.key for p in all_parts()}


def test_a_run_and_a_rerun_work_against_the_real_s3_store(s3_store: S3Store) -> None:
    run(s3_store, FakeOpenMeteo())
    again = FakeOpenMeteo()
    run(s3_store, again)
    assert again.calls == [Part(Source.GFS_ARCHIVE, s, 2026) for s in SITES]
    assert set(s3_store.list_keys("raw/weather/")) == {p.key for p in all_parts()} | {MANIFEST_KEY}


def test_each_part_is_parquet_with_its_rows_and_counts(store: MemoryStore) -> None:
    run(store, FakeOpenMeteo())
    part = Part(Source.ERA5, SITES[0], 2023)
    raw = store.get(part.key)
    assert raw is not None
    df = pd.read_parquet(io.BytesIO(raw))
    assert tuple(df.columns) == COLUMNS
    assert len(df) == 2
    entry = manifest(store)["parts"][part.key]
    assert (entry["rows"], entry["missing_values"]) == (2, 1)
    assert entry["fetched_at_utc"] == NOW.isoformat()


def test_a_rerun_the_same_day_only_refreshes_this_years_archive(store: MemoryStore) -> None:
    run(store, FakeOpenMeteo())
    again = FakeOpenMeteo()
    run(store, again)
    assert again.calls == [Part(Source.GFS_ARCHIVE, s, 2026) for s in SITES]


def test_an_interrupted_run_resumes_without_refetching_what_is_done(store: MemoryStore) -> None:
    failing = Part(Source.GFS_ARCHIVE, SITES[0], 2025)
    first = FakeOpenMeteo(fail_on=failing)
    with pytest.raises(OSError, match="network down"):
        run(store, first)
    second = FakeOpenMeteo()
    run(store, second)
    done_first = set(first.calls) - {failing}
    final_done = {p for p in done_first if p.year < TODAY.year}
    assert not final_done & set(second.calls)
    assert failing in second.calls
    assert {e["key"] for e in manifest(store)["parts"].values()} == {p.key for p in all_parts()}


def test_a_crash_between_data_and_manifest_is_repaired_by_a_rerun(store: MemoryStore) -> None:
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
        run(store, FakeOpenMeteo())
    store.put = real_put  # type: ignore[method-assign]
    run(store, FakeOpenMeteo())
    entries = manifest(store)["parts"].values()
    assert {e["key"] for e in entries} == {p.key for p in all_parts()}
    assert all(store.get(e["key"]) is not None for e in entries)


def test_the_manifest_never_claims_a_part_whose_data_write_failed(store: MemoryStore) -> None:
    real_put = store.put
    failing_key = Part(Source.ERA5, SITES[1], 2024).key

    def put_failing_data(key: str, data: bytes) -> None:
        if key == failing_key:
            raise OSError("S3 hiccup")
        real_put(key, data)

    store.put = put_failing_data  # type: ignore[method-assign]
    with pytest.raises(OSError, match="hiccup"):
        run(store, FakeOpenMeteo())
    store.put = real_put  # type: ignore[method-assign]
    raw = store.get(MANIFEST_KEY)
    parts = json.loads(raw)["parts"] if raw else {}
    assert failing_key not in parts
    assert all(store.get(e["key"]) is not None for e in parts.values())


def test_this_years_archive_becomes_final_next_year(store: MemoryStore) -> None:
    key = Part(Source.GFS_ARCHIVE, SITES[0], 2026).key
    run(store, FakeOpenMeteo())
    assert manifest(store)["parts"][key]["final"] is False
    later = FakeOpenMeteo()
    run(store, later, today=date(2027, 1, 5))
    assert Part(Source.GFS_ARCHIVE, SITES[0], 2026) in later.calls
    assert manifest(store)["parts"][key]["final"] is True


def test_every_fetch_is_paced_by_its_weight_first(store: MemoryStore) -> None:
    pace = RecordingPace()
    fake = FakeOpenMeteo()
    run(store, fake, pace=pace)
    expected = [call_weight((p.days(TODAY)[1] - p.days(TODAY)[0]).days + 1) for p in fake.calls]
    assert pace.weights == pytest.approx(expected)


def test_logs_hold_counts_never_values(
    store: MemoryStore, caplog: pytest.LogCaptureFixture
) -> None:
    """Only our own records: botocore's debug lines carry S3 checksums, which hold any digits."""
    with caplog.at_level(logging.DEBUG):
        run(store, FakeOpenMeteo())
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("airwatch"))
    assert "2 rows, 1 missing values" in ours
    assert str(SECRET_VALUE) not in ours
    assert "987" not in ours


def test_the_plan_lists_only_missing_or_unfinished_parts() -> None:
    done = {
        Part(Source.ERA5, "040130019", 2023).key: {"final": True},
        Part(Source.GFS_ARCHIVE, "040130019", 2025).key: {"final": True},
        Part(Source.GFS_ARCHIVE, "040130019", 2026).key: {"final": False},
    }
    parts = plan_parts(("040130019",), today=TODAY, manifest_parts=done, era5_years=SMALL_ERA5)
    assert parts == [
        Part(Source.ERA5, "040130019", 2024),
        Part(Source.GFS_ARCHIVE, "040130019", 2024),
        Part(Source.GFS_ARCHIVE, "040130019", 2026),
    ]


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def budget_on(clock: FakeClock, limits: dict[float, float] | None = None) -> CallBudget:
    return CallBudget(limits or BUDGET, monotonic=clock.monotonic, sleep=clock.sleep)


def test_the_budget_is_half_of_each_published_limit() -> None:
    assert FREE_LIMITS == {60.0: 600, 3600.0: 5000, 86400.0: 10000}
    assert BUDGET == {60.0: 300, 3600.0: 2500, 86400.0: 5000}


def test_the_minute_window_paces_a_burst_of_year_files() -> None:
    """The 2026-11-24 failure: 37 year files (26 calls each) in 20 s tripped the 600/min limit."""
    clock = FakeClock()
    budget = budget_on(clock)
    year = call_weight(365)
    for _ in range(11):
        budget(year)
    assert clock.slept == []
    budget(year)
    assert clock.slept == [pytest.approx(60)]


def test_the_hour_window_waits_for_its_oldest_call_to_expire() -> None:
    clock = FakeClock()
    budget = budget_on(clock, {3600.0: 2500})
    budget(1000)
    clock.t += 60
    budget(1000)
    assert clock.slept == []
    budget(1000)
    assert clock.slept == [pytest.approx(3600 - 60)]


def test_the_budget_never_waits_with_room_in_every_window() -> None:
    clock = FakeClock()
    budget = budget_on(clock)
    for _ in range(11):
        budget(25)
        clock.t += 6
    assert clock.slept == []


def test_the_budget_refuses_a_request_over_its_smallest_window() -> None:
    budget = budget_on(FakeClock())
    with pytest.raises(ValueError, match="over the budget of one window"):
        budget(301)


def test_a_call_still_counts_until_its_whole_window_has_passed() -> None:
    clock = FakeClock()
    budget = budget_on(clock)
    budget(300)
    clock.t += 31
    budget(1)
    assert clock.slept == [pytest.approx(29)]


gaps = st.one_of(st.floats(min_value=0, max_value=40), st.floats(min_value=0, max_value=900))
requests = st.lists(
    st.tuples(st.floats(min_value=1, max_value=60), gaps),
    min_size=1,
    max_size=80,
)


@given(requests=requests)
@example(requests=[(60.0, 0.0)] * 5 + [(60.0, 31.0)])
def test_no_window_ever_holds_more_than_its_budget(requests: list[tuple[float, float]]) -> None:
    clock = FakeClock()
    budget = budget_on(clock)
    sent: list[tuple[float, float]] = []
    for weight, gap in requests:
        clock.t += gap
        budget(weight)
        sent.append((clock.t, weight))
    for window, limit in BUDGET.items():
        for t0, _ in sent:
            spent = sum(w for t, w in sent if t0 <= t < t0 + window)
            assert spent <= limit + 1e-9, (window, t0)
