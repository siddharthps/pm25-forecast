"""Validation report (#12, T12a): JSON + Markdown per run, counts only, never a measurement.

The command-line loaders are tested on fakes: moto for the private bucket, a mock transport
for AirNow. Their real runs are manual (`python -m airwatch.validation.report`).
"""

import io
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import boto3
import httpx
import pandas as pd
import pytest
from moto import mock_aws

from airwatch.observations.aqs_bulk import MANIFEST_KEY, Part
from airwatch.observations.sites import SITE_COORDS, TRAINING_SITES
from airwatch.storage import S3Store
from airwatch.validation.checks import Window, run_checks
from airwatch.validation.reference import Monitor, Reference
from airwatch.validation.report import (
    MARKDOWN_ITEM_CAP,
    build_report,
    load_aqs_bulk,
    render_markdown,
    save_report,
    validate_airnow_day,
    validate_aqs_bulk,
)
from tests.unit.observations.airnow_fakes import day_transport
from tests.unit.validation.helpers import SITE_A, SITE_B, START, concat, frame, varying

PHOENIX = ZoneInfo("America/Phoenix")
DAY = Window(START, START + timedelta(days=1))
NOW = datetime(2026, 11, 20, 1, 2, 3, tzinfo=UTC)
SECRET = 123.456


def report_for(df: pd.DataFrame, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    result = run_checks(df, window=DAY, tz=PHOENIX, sites=(SITE_A, SITE_B), now=NOW)
    return build_report(result, source="aqs", window=DAY, generated_at_utc=NOW, extra=extra)


def test_report_is_json_with_the_run_facts() -> None:
    rep = report_for(frame(varying(24)))
    assert json.loads(json.dumps(rep)) == rep
    assert rep["source"] == "aqs"
    assert rep["generated_at_utc"] == "2026-11-20T01:02:03+00:00"
    assert rep["window_utc"] == {
        "start": "2024-03-01T07:00:00+00:00",
        "end": "2024-03-02T07:00:00+00:00",
    }
    assert rep["passed"] is True
    assert rep["rows_in"] == 24
    assert rep["rows_kept"] == 24
    rules = [f["rule"] for f in rep["findings"]]
    assert "duplicate_hours" in rules
    assert "site_missing" in rules


def test_no_measurement_reaches_the_report() -> None:
    vals = varying(24, base=SECRET)
    vals[2] = 5000.0 + SECRET
    df = concat(frame(vals), frame(vals).iloc[[0]])
    rep = report_for(df)
    assert str(SECRET) not in json.dumps(rep)
    assert str(SECRET) not in render_markdown(rep)


def test_markdown_leads_with_the_verdict_and_lists_every_rule() -> None:
    df = frame(varying(24))
    md = render_markdown(report_for(concat(df, df.iloc[[0]])))
    assert md.splitlines()[0].startswith("# Validation report: aqs")
    assert "**FAILED**" in md
    for rule in ("duplicate_hours", "outside_valid_range", "coverage_gap", "site_missing"):
        assert f"`{rule}`" in md
    assert "**PASSED**" in render_markdown(report_for(df))


def test_markdown_caps_long_item_lists() -> None:
    window = Window(datetime(2020, 1, 1, 7, tzinfo=UTC), datetime(2024, 3, 1, 7, tzinfo=UTC))
    result = run_checks(frame(varying(24)), window=window, tz=PHOENIX, sites=(SITE_A,), now=NOW)
    rep = build_report(result, source="aqs", window=window, generated_at_utc=NOW)
    gaps = next(f for f in rep["findings"] if f["rule"] == "coverage_gap")
    assert len(gaps["items"]) > MARKDOWN_ITEM_CAP
    md = render_markdown(rep)
    assert f"and {len(gaps['items']) - MARKDOWN_ITEM_CAP} more" in md


def test_extra_facts_are_carried_into_the_report() -> None:
    rep = report_for(frame(varying(24)), extra={"parts": 180})
    assert rep["extra"] == {"parts": 180}


def test_a_naive_generation_time_is_refused() -> None:
    result = run_checks(frame(varying(24)), window=DAY, tz=PHOENIX, sites=(SITE_A,), now=NOW)
    with pytest.raises(ValueError, match="time zone"):
        build_report(result, source="aqs", window=DAY, generated_at_utc=datetime(2026, 1, 1))  # noqa: DTZ001


def test_save_writes_json_and_markdown_named_by_source_and_utc_time(tmp_path: Path) -> None:
    rep = report_for(frame(varying(24)))
    json_path, md_path = save_report(rep, tmp_path)
    assert json_path.name == "validation_aqs_20261120T010203Z.json"
    assert md_path.name == "validation_aqs_20261120T010203Z.md"
    assert json.loads(json_path.read_text(encoding="utf-8")) == rep
    assert md_path.read_text(encoding="utf-8") == render_markdown(rep)


def test_save_never_overwrites_an_earlier_report(tmp_path: Path) -> None:
    rep = report_for(frame(varying(24)))
    save_report(rep, tmp_path)
    with pytest.raises(FileExistsError):
        save_report(rep, tmp_path)


BUCKET = "test-private-bucket"


@pytest.fixture
def store() -> Iterator[S3Store]:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        yield S3Store(s3, BUCKET)


def put_part(store: S3Store, part: Part, df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False, engine="pyarrow")
    store.put(part.key, buf.getvalue())


def test_load_reads_every_manifest_part_and_nothing_else(store: S3Store) -> None:
    a, b = Part(SITE_A, 2024), Part(SITE_B, 2024)
    put_part(store, a, frame(varying(24)))
    put_part(store, b, frame(varying(10), site=SITE_B))
    put_part(store, Part(SITE_B, 2023), frame(varying(5), site=SITE_B))
    manifest = {"version": 1, "parts": {a.key: {"rows": 24}, b.key: {"rows": 10}}}
    store.put(MANIFEST_KEY, json.dumps(manifest).encode())
    df, n_parts = load_aqs_bulk(store)
    assert n_parts == 2
    assert len(df) == 34
    assert sorted(df["site_id"].unique()) == [SITE_A, SITE_B]


def test_load_refuses_a_part_whose_rows_disagree_with_the_manifest(store: S3Store) -> None:
    a = Part(SITE_A, 2024)
    put_part(store, a, frame(varying(24)))
    store.put(MANIFEST_KEY, json.dumps({"version": 1, "parts": {a.key: {"rows": 25}}}).encode())
    with pytest.raises(ValueError, match="rows"):
        load_aqs_bulk(store)


def test_load_refuses_a_missing_manifest(store: S3Store) -> None:
    with pytest.raises(FileNotFoundError, match="manifest"):
        load_aqs_bulk(store)


def test_load_keeps_the_schema_for_empty_parts(store: S3Store) -> None:
    a, b = Part(SITE_A, 2009), Part(SITE_A, 2024)
    put_part(store, a, frame([]))
    put_part(store, b, frame(varying(24)))
    manifest = {"version": 1, "parts": {a.key: {"rows": 0}, b.key: {"rows": 24}}}
    store.put(MANIFEST_KEY, json.dumps(manifest).encode())
    df, _ = load_aqs_bulk(store)
    assert len(df) == 24
    assert date(2024, 3, 1) == df["time_utc"].min().date()


def test_the_aqs_run_checks_the_download_and_saves_a_report(store: S3Store, tmp_path: Path) -> None:
    a = Part(SITE_A, 2024)
    put_part(store, a, frame(varying(24)))
    store.put(MANIFEST_KEY, json.dumps({"version": 1, "parts": {a.key: {"rows": 24}}}).encode())
    result = validate_aqs_bulk(
        store, tz=PHOENIX, sites=(SITE_A,), now=NOW, out_dir=tmp_path, reference=None
    )
    assert result.passed
    rep = json.loads((tmp_path / "validation_aqs_20261120T010203Z.json").read_text("utf-8"))
    assert rep["extra"] == {"parts": 1, "reference": "none"}
    assert rep["window_utc"] == {
        "start": "2009-01-01T07:00:00+00:00",
        "end": "2026-01-01T07:00:00+00:00",
    }, "coverage runs over the final years only, Phoenix midnight to Phoenix midnight"


def test_the_aqs_run_reports_a_hard_failure(store: S3Store, tmp_path: Path) -> None:
    a = Part(SITE_A, 2024)
    df = frame(varying(24))
    put_part(store, a, concat(df, df.iloc[[0]]))
    store.put(MANIFEST_KEY, json.dumps({"version": 1, "parts": {a.key: {"rows": 25}}}).encode())
    result = validate_aqs_bulk(
        store, tz=PHOENIX, sites=(SITE_A,), now=NOW, out_dir=tmp_path, reference=None
    )
    assert not result.passed
    assert "**FAILED**" in (tmp_path / "validation_aqs_20261120T010203Z.md").read_text("utf-8")


def test_the_airnow_run_checks_one_local_day(tmp_path: Path) -> None:
    with httpx.Client(transport=day_transport(missing=frozenset({10}))) as client:
        result = validate_airnow_day(
            client,
            date(2026, 11, 18),
            tz=PHOENIX,
            sites=TRAINING_SITES,
            now=NOW,
            out_dir=tmp_path,
            reference=None,
        )
    assert result.passed
    assert result.finding("airnow_rows_dropped").items[0] == {"reason": "file_missing", "rows": 1}
    assert result.finding("coverage_gap").count == 0
    rep = json.loads((tmp_path / "validation_airnow_20261120T010203Z.json").read_text("utf-8"))
    assert rep["extra"] == {"local_day": "2026-11-18", "reference": "none"}
    assert rep["window_utc"]["start"] == "2026-11-18T07:00:00+00:00"


def test_load_refuses_a_manifest_part_missing_from_the_bucket(store: S3Store) -> None:
    a = Part(SITE_A, 2024)
    store.put(MANIFEST_KEY, json.dumps({"version": 1, "parts": {a.key: {"rows": 24}}}).encode())
    with pytest.raises(FileNotFoundError, match="missing"):
        load_aqs_bulk(store)


def test_rows_kept_counts_only_the_usable_rows() -> None:
    vals = varying(24)
    vals[0] = 2000.0
    rep = report_for(frame(vals))
    assert (rep["rows_in"], rep["rows_kept"]) == (24, 23)


def test_save_writes_nothing_if_either_file_already_exists(tmp_path: Path) -> None:
    rep = report_for(frame(varying(24)))
    (tmp_path / "validation_aqs_20261120T010203Z.md").write_text("earlier", encoding="utf-8")
    with pytest.raises(FileExistsError):
        save_report(rep, tmp_path)
    assert not (tmp_path / "validation_aqs_20261120T010203Z.json").exists()


def test_markdown_shows_exactly_the_capped_number_of_items() -> None:
    window = Window(datetime(2020, 1, 1, 7, tzinfo=UTC), datetime(2024, 3, 1, 7, tzinfo=UTC))
    result = run_checks(frame(varying(24)), window=window, tz=PHOENIX, sites=(SITE_A,), now=NOW)
    md = render_markdown(build_report(result, source="aqs", window=window, generated_at_utc=NOW))
    section = md.split("## `coverage_gap`", 1)[1]
    assert sum(line.startswith("- site_id") for line in section.splitlines()) == MARKDOWN_ITEM_CAP


def test_the_aqs_run_applies_the_reference_rules(store: S3Store, tmp_path: Path) -> None:
    a = Part(SITE_A, 2024)
    put_part(store, a, frame(varying(24), method="182"))
    store.put(MANIFEST_KEY, json.dumps({"version": 1, "parts": {a.key: {"rows": 24}}}).encode())
    ref = Reference(
        monitors=(
            Monitor(SITE_A, 1, date(2024, 3, 2), None, *SITE_COORDS[SITE_A], "38060", "182"),
        ),
        airnow_coords={},
        city_cbsa="38060",
    )
    result = validate_aqs_bulk(
        store, tz=PHOENIX, sites=(SITE_A,), now=NOW, out_dir=tmp_path, reference=ref
    )
    assert result.finding("outside_active_period").count == 24
    rep = json.loads((tmp_path / "validation_aqs_20261120T010203Z.json").read_text("utf-8"))
    assert rep["extra"] == {"parts": 1, "reference": "aqs monitors + airnow site list"}
