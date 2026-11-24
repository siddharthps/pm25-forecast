"""The daily CAMS save (#78; D-053): CAMS as issued for the target day, beside the record.

A frozen clock, a fake live fetch and an in-memory bucket. Checked: what the file holds, that a
second run the same morning fetches nothing and changes nothing, that a dry run writes nothing,
and that a run newer than the as-issued one is never saved as issued.
"""

import json
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from airwatch.errors import ReportableError
from airwatch.timeutil import issue_time_utc
from airwatch.weather import cams
from airwatch.weather.cams import CamsSource, issued_run_start
from airwatch.weather.cams_save import (
    SAVE_VERSION,
    CamsSaveError,
    build_save,
    cams_key,
    save_cams,
)
from tests.unit.forecast.fakes import PHOENIX, SITES, MemoryStore

A, B = SITES
TARGET = date(2026, 11, 25)
RUN = issued_run_start(TARGET)
PUBLISHED = RUN + timedelta(hours=9, minutes=48)
FETCHED = issue_time_utc(TARGET) + timedelta(minutes=5)


def live_rows(
    site: str,
    *,
    base: float = 5.0,
    run: datetime = RUN,
    published: datetime = PUBLISHED,
    gaps: int = 0,
) -> pd.DataFrame:
    """48 hours (the target's two UTC days), each `base + 0.5 x hour of day`; `gaps` hours blank."""
    first = datetime(2026, 11, 25, tzinfo=UTC)
    stamps = [first + timedelta(hours=h) for h in range(48)]
    values = [base + (h % 24) * 0.5 for h in range(48)]
    for h in range(gaps):
        values[10 + h] = math.nan
    return pd.DataFrame(
        {
            "site_id": site,
            "valid_utc": pd.to_datetime(stamps, utc=True),
            cams.VARIABLE: values,
            "source": CamsSource.LIVE.value,
            "run_start_utc": pd.Timestamp(run),
            "available_at_utc": pd.Timestamp(published),
        },
        columns=list(cams.COLUMNS),
    )


class FakeLive:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.calls: list[tuple[str, date]] = []

    def __call__(self, site: str, target: date) -> pd.DataFrame:
        self.calls.append((site, target))
        return live_rows(site, base=5.0 if site == A else 10.0, **self.kwargs)


def save(store: MemoryStore, fetch: Any, *, write: bool = True) -> Any:
    return save_cams(
        TARGET,
        fetch_cams=fetch,
        private=store,
        sites=SITES,
        tz=PHOENIX,
        now=lambda: FETCHED,
        write=write,
    )


def saved(store: MemoryStore) -> dict[str, Any]:
    raw = store.get(cams_key(TARGET))
    assert raw is not None
    loaded: dict[str, Any] = json.loads(raw)
    return loaded


def test_the_file_sits_beside_the_forecast_record() -> None:
    assert cams_key(TARGET) == "records/forecast_date=2026-11-25/cams.json"


def test_a_save_holds_each_monitors_day_and_the_run_it_came_from() -> None:
    store, fetch = MemoryStore(), FakeLive()
    outcome = save(store, fetch)
    assert outcome.status == "saved"
    assert sorted(fetch.calls) == [(A, TARGET), (B, TARGET)]
    body = saved(store)
    assert body["version"] == SAVE_VERSION
    assert body["forecast_date"] == "2026-11-25"
    assert body["city_tz"] == "America/Phoenix"
    assert (body["source"], body["model"], body["variable"]) == (
        "open-meteo air-quality api",
        "cams_global",
        "pm2_5",
    )
    assert body["run_start_utc"] == "2026-11-24T00:00:00+00:00"
    assert body["run_available_utc"] == "2026-11-24T09:48:00+00:00"
    assert body["issue_time_utc"] == "2026-11-24T12:00:00+00:00"
    assert body["published_before_issue"] is True
    assert body["fetched_at_utc"] == "2026-11-24T12:05:00+00:00"
    monitor = body["monitors"][A]
    assert monitor["hours"] == 24
    assert monitor["mean_ug_m3"] == pytest.approx(10.75)
    assert body["monitors"][B]["mean_ug_m3"] == pytest.approx(15.75)
    assert [h["valid_utc"] for h in monitor["hourly"]][:2] == [
        "2026-11-25T07:00:00+00:00",
        "2026-11-25T08:00:00+00:00",
    ]
    assert monitor["hourly"][-1]["valid_utc"] == "2026-11-26T06:00:00+00:00"
    assert monitor["hourly"][0]["pm2_5"] == pytest.approx(8.5)


def test_a_day_with_a_blank_hour_keeps_its_hours_but_no_mean() -> None:
    store = MemoryStore()
    save(store, FakeLive(gaps=1))
    monitor = saved(store)["monitors"][A]
    assert (monitor["hours"], monitor["mean_ug_m3"]) == (23, None)
    assert monitor["hourly"][3] == {"valid_utc": "2026-11-25T10:00:00+00:00", "pm2_5": None}


def test_a_second_run_the_same_morning_fetches_nothing() -> None:
    store, first = MemoryStore(), FakeLive()
    save(store, first)
    again = FakeLive()
    outcome = save(store, again)
    assert outcome.status == "already_saved"
    assert again.calls == []
    assert outcome.save == saved(store)


@settings(max_examples=25, deadline=None)
@given(
    st.floats(min_value=0, max_value=500, allow_nan=False), st.integers(min_value=0, max_value=30)
)
def test_a_second_run_never_changes_a_saved_file(base: float, gaps: int) -> None:
    store = MemoryStore()
    save(store, FakeLive())
    before = store.get(cams_key(TARGET))

    def other(site: str, _target: date) -> pd.DataFrame:
        return live_rows(site, base=base, gaps=gaps)

    save(store, other)
    assert store.get(cams_key(TARGET)) == before


def test_a_dry_run_builds_the_save_but_writes_nothing() -> None:
    store = MemoryStore()
    outcome = save(store, FakeLive(), write=False)
    assert outcome.status == "dry_run"
    assert outcome.save is not None
    assert outcome.save["monitors"][A]["hours"] == 24
    assert store.objects == {}


def test_a_lost_race_keeps_the_file_already_there() -> None:
    store = MemoryStore()
    first = build_save(
        TARGET,
        pd.concat([live_rows(A), live_rows(B)]),
        tz=PHOENIX,
        sites=SITES,
        fetched_utc=FETCHED,
    )
    real_get = store.get
    calls = {"n": 0}

    def get_once_empty(key: str) -> bytes | None:
        calls["n"] += 1
        if calls["n"] == 1:
            store.objects[cams_key(TARGET)] = json.dumps(first).encode()
            return None
        return real_get(key)

    store.get = get_once_empty  # type: ignore[method-assign]
    outcome = save(store, FakeLive())
    assert outcome.status == "already_saved"
    assert outcome.save == first


def test_a_run_newer_than_the_as_issued_one_is_refused() -> None:
    store = MemoryStore()
    with pytest.raises(CamsSaveError, match=r"^run_after_as_issued:"):
        save(store, FakeLive(run=RUN + timedelta(hours=12), published=FETCHED))
    assert store.objects == {}


def test_an_older_run_is_saved_with_its_own_start() -> None:
    store = MemoryStore()
    older = RUN - timedelta(hours=12)
    save(store, FakeLive(run=older, published=older + timedelta(hours=9, minutes=55)))
    body = saved(store)
    assert body["run_start_utc"] == "2026-11-23T12:00:00+00:00"
    assert body["published_before_issue"] is True


def test_a_run_published_after_the_issue_time_says_so() -> None:
    store = MemoryStore()
    late = issue_time_utc(TARGET) + timedelta(minutes=1)
    save(store, FakeLive(published=late))
    assert saved(store)["published_before_issue"] is False


def test_monitors_from_two_runs_are_refused() -> None:
    def mixed(site: str, _target: date) -> pd.DataFrame:
        return live_rows(site, run=RUN if site == A else RUN - timedelta(hours=12))

    with pytest.raises(CamsSaveError, match=r"^mixed_runs:"):
        save(MemoryStore(), mixed)


def test_a_monitor_without_rows_is_refused() -> None:
    def one_site(_site: str, _target: date) -> pd.DataFrame:
        return live_rows(A)

    with pytest.raises(CamsSaveError, match=r"^monitor_missing:"):
        save(MemoryStore(), one_site)


def test_refusals_are_reportable() -> None:
    assert issubclass(CamsSaveError, ReportableError)
