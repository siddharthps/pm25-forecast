"""The weather download's coverage check (#19, T14; D-051, D-052), on a store the bulk run filled.

Each part is checked against its own days: every hour once, every value present. Gaps are
reported as runs (variable, first and last hour, length), never values, and the GFS archive's
known empty start (before 2024-01-21 12:00 UTC at `_previous_day3`) is counted apart.
"""

import json
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
import pytest

from airwatch.weather import cams
from airwatch.weather.bulk import MANIFEST_KEY, Part, run_download
from airwatch.weather.cams import CamsSource
from airwatch.weather.coverage import (
    ARCHIVE_COMPLETE_FROM,
    check_part,
    check_store,
    render_markdown,
)
from airwatch.weather.openmeteo import COLUMNS, VARIABLES, Source
from tests.unit.forecast.fakes import MemoryStore

SITES = ("040130019",)
TODAY = date(2024, 1, 25)
NOW = datetime(2024, 1, 25, 6, tzinfo=UTC)
SECRET_VALUE = 987.625
ERA5 = range(2023, 2024)


def full_frame(part: Part, today: date = TODAY) -> pd.DataFrame:
    """Every hour of the part's days, every value SECRET_VALUE."""
    start, end = part.days(today)
    first = datetime(start.year, start.month, start.day, tzinfo=UTC)
    hours = [first + timedelta(hours=h) for h in range(((end - start).days + 1) * 24)]
    is_cams = part.source is CamsSource.HISTORY
    columns = cams.COLUMNS if is_cams else COLUMNS
    data: dict[str, Any] = {
        "site_id": part.site_id,
        "valid_utc": pd.to_datetime(hours, utc=True),
        "source": part.source.value,
        "run_start_utc": pd.to_datetime(hours, utc=True),
        "available_at_utc": NOW,
    }
    data |= dict.fromkeys(part.variables, SECRET_VALUE)
    return pd.DataFrame(data, columns=list(columns))


def gfs_with_lead_in(part: Part) -> pd.DataFrame:
    df = full_frame(part)
    if part.source is Source.GFS_ARCHIVE:
        early = df["valid_utc"] < pd.Timestamp(ARCHIVE_COMPLETE_FROM)
        df.loc[early, list(VARIABLES)] = math.nan
    return df


def filled(fetch: Any = gfs_with_lead_in) -> MemoryStore:
    store = MemoryStore()
    run_download(
        store, fetch, SITES, today=TODAY, now=lambda: NOW, pace=lambda _: None, era5_years=ERA5
    )
    return store


GFS_2024 = Part(Source.GFS_ARCHIVE, SITES[0], 2024)


def test_the_archive_is_complete_from_d051s_recorded_hour() -> None:
    assert datetime(2024, 1, 21, 12, tzinfo=UTC) == ARCHIVE_COMPLETE_FROM


def test_a_complete_store_passes_with_the_lead_in_counted_apart() -> None:
    report = check_store(filled(), SITES, today=TODAY, era5_years=ERA5)
    assert report["passed"] is True
    gfs = report["parts"][GFS_2024.key]
    assert gfs["lead_in_hours"] == 36
    assert gfs["gaps"] == []
    assert sum(len(p["gaps"]) for p in report["parts"].values()) == 0
    assert len(report["parts"]) == len(report["planned"])


def test_a_gap_after_the_lead_in_is_one_run_per_variable() -> None:
    df = gfs_with_lead_in(GFS_2024)
    hole = (df["valid_utc"] >= pd.Timestamp("2024-01-23 05:00", tz="UTC")) & (
        df["valid_utc"] <= pd.Timestamp("2024-01-24 09:00", tz="UTC")
    )
    df.loc[hole, "cloud_cover"] = math.nan
    df.loc[df["valid_utc"] == pd.Timestamp("2024-01-23 07:00", tz="UTC"), "cloud_cover"] = 1.0
    result = check_part(GFS_2024, df, today=TODAY)
    assert result["gaps"] == [
        {
            "variable": "cloud_cover",
            "first_utc": "2024-01-23T05:00:00+00:00",
            "last_utc": "2024-01-23T06:00:00+00:00",
            "hours": 2,
        },
        {
            "variable": "cloud_cover",
            "first_utc": "2024-01-23T08:00:00+00:00",
            "last_utc": "2024-01-24T09:00:00+00:00",
            "hours": 26,
        },
    ]
    assert result["lead_in_hours"] == 36


def test_missing_values_before_the_lead_in_ends_are_not_gaps_only_for_the_archive() -> None:
    part = Part(CamsSource.HISTORY, SITES[0], 2024)
    df = full_frame(part)
    df.loc[df["valid_utc"] < pd.Timestamp("2024-01-01 03:00", tz="UTC"), cams.VARIABLE] = math.nan
    result = check_part(part, df, today=TODAY)
    assert (result["lead_in_hours"], [g["hours"] for g in result["gaps"]]) == (0, [3])


@pytest.mark.parametrize(
    ("edit", "rule", "count"),
    [
        (lambda df: df.drop(index=[40, 41]), "missing_hours", 2),
        (lambda df: pd.concat([df, df.iloc[[50]]]), "duplicate_hours", 1),
    ],
    ids=["two_hours_dropped", "one_hour_twice"],
)
def test_hour_faults_fail_the_store(edit: Any, rule: str, count: int) -> None:
    def fetch(part: Part) -> pd.DataFrame:
        df = gfs_with_lead_in(part)
        return edit(df) if part == GFS_2024 else df

    report = check_store(filled(fetch), SITES, today=TODAY, era5_years=ERA5)
    assert report["passed"] is False
    assert report["parts"][GFS_2024.key][rule] == count
    assert report["failures"] == [{"key": GFS_2024.key, "rule": rule}]


def test_a_planned_part_absent_from_the_manifest_fails() -> None:
    store = filled()
    manifest = json.loads(store.get(MANIFEST_KEY) or b"{}")
    del manifest["parts"][GFS_2024.key]
    store.put(MANIFEST_KEY, json.dumps(manifest).encode())
    report = check_store(store, SITES, today=TODAY, era5_years=ERA5)
    assert report["failures"] == [{"key": GFS_2024.key, "rule": "not_in_manifest"}]


def test_a_file_that_differs_from_its_manifest_entry_fails() -> None:
    store = filled()
    other = filled(lambda p: full_frame(p).iloc[:-1] if p == GFS_2024 else gfs_with_lead_in(p))
    store.put(GFS_2024.key, other.get(GFS_2024.key) or b"")
    report = check_store(store, SITES, today=TODAY, era5_years=ERA5)
    assert {"key": GFS_2024.key, "rule": "sha256_mismatch"} in report["failures"]
    assert report["passed"] is False


def test_the_report_and_its_markdown_hold_no_value() -> None:
    def fetch(part: Part) -> pd.DataFrame:
        df = gfs_with_lead_in(part)
        if part == GFS_2024:
            df.loc[
                df["valid_utc"] == pd.Timestamp("2024-01-23 05:00", tz="UTC"), "precipitation"
            ] = math.nan
        return df

    report = check_store(filled(fetch), SITES, today=TODAY, era5_years=ERA5)
    text = json.dumps(report) + render_markdown(report)
    assert "987" not in text
    assert "precipitation" in render_markdown(report)
    assert "2024-01-23T05:00:00+00:00" in render_markdown(report)


def test_a_recorded_part_whose_file_is_gone_fails() -> None:
    store = filled()
    del store.objects[GFS_2024.key]
    report = check_store(store, SITES, today=TODAY, era5_years=ERA5)
    assert report["failures"] == [{"key": GFS_2024.key, "rule": "file_missing"}]
    assert GFS_2024.key not in report["parts"]
