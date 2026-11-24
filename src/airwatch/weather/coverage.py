"""The weather download's coverage check (#19, T14; D-051, D-052): every hour, every value.

    cd ~/code/pm25-forecast
    AWS_PROFILE=pm25 uv run python -m airwatch.weather.coverage   # reads only; writes the report

Reads the bulk download's manifest and parts from the private bucket and checks each planned
part (`airwatch.weather.bulk.plan_parts`, as if nothing were done) against its own days:

- **hard** (`failures`, exit 1): `not_in_manifest`, `file_missing`, `sha256_mismatch` (the file
  isn't the one recorded), `missing_hours` and `duplicate_hours` (a stamp absent or repeated).
- **reported:** `gaps`, each run of consecutive missing values in one variable, with its first
  and last hour. The GFS archive's known empty start, before `ARCHIVE_COMPLETE_FROM` (D-051),
  is counted as `lead_in_hours` instead.

The report holds keys, variables, times and counts, never a value. It goes to
`data/reports/weather/` (gitignored); T12b adds the other problem classes.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import sys
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
import pandas as pd

from airwatch.config import get_settings
from airwatch.forecast.record import Store
from airwatch.logutil import configure
from airwatch.observations.sites import TRAINING_SITES
from airwatch.storage import S3Store
from airwatch.weather.bulk import ERA5_YEARS, Part, load_manifest, plan_parts
from airwatch.weather.openmeteo import Source

__all__ = ["ARCHIVE_COMPLETE_FROM", "REPORT_DIR", "check_part", "check_store", "render_markdown"]

log = logging.getLogger(__name__)

ARCHIVE_COMPLETE_FROM = datetime(2024, 1, 21, 12, tzinfo=UTC)
REPORT_DIR = Path("data/reports/weather")
_HOUR = timedelta(hours=1)
_HARD_COUNTS = ("missing_hours", "duplicate_hours")


def _iso(ts: pd.Timestamp) -> str:
    return ts.to_pydatetime().isoformat()


def _gaps(stamps: pd.Series, missing: pd.Series, variable: str) -> list[dict[str, Any]]:
    """Runs of missing values, where consecutive means one hour apart."""
    runs: list[dict[str, Any]] = []
    for ts in stamps[missing.to_numpy()]:
        last = runs[-1] if runs else None
        if last is not None and ts - last["_last"] == _HOUR:
            last["_last"], last["hours"] = ts, last["hours"] + 1
        else:
            runs.append({"variable": variable, "_first": ts, "_last": ts, "hours": 1})
    return [
        {
            "variable": r["variable"],
            "first_utc": _iso(r["_first"]),
            "last_utc": _iso(r["_last"]),
            "hours": r["hours"],
        }
        for r in runs
    ]


def check_part(part: Part, df: pd.DataFrame, *, today: date) -> dict[str, Any]:
    """One part's hours and values against its own days."""
    start, end = part.days(today)
    first = pd.Timestamp(datetime(start.year, start.month, start.day, tzinfo=UTC))
    expected = pd.date_range(first, periods=((end - start).days + 1) * 24, freq="h")
    stamps = pd.to_datetime(df["valid_utc"], utc=True)
    rows = df.assign(valid_utc=stamps).sort_values("valid_utc").drop_duplicates("valid_utc")
    lead_in = (
        rows["valid_utc"] < pd.Timestamp(ARCHIVE_COMPLETE_FROM)
        if part.source is Source.GFS_ARCHIVE
        else pd.Series(False, index=rows.index)
    )
    gaps = [
        gap
        for v in part.variables
        for gap in _gaps(rows["valid_utc"], rows[v].isna() & ~lead_in, v)
    ]
    lead_in_hours = int((rows[list(part.variables)].isna().any(axis=1) & lead_in).sum())
    return {
        "source": part.source.value,
        "site_id": part.site_id,
        "year": part.year,
        "expected_hours": len(expected),
        "rows": len(df),
        "missing_hours": int((~expected.isin(stamps)).sum()),
        "duplicate_hours": int(stamps.duplicated().sum()),
        "lead_in_hours": lead_in_hours,
        "gaps": gaps,
    }


def check_store(
    store: Store, sites: Iterable[str], *, today: date, era5_years: range = ERA5_YEARS
) -> dict[str, Any]:
    """Every planned part in the store, checked; `passed` is False on any hard failure."""
    recorded = load_manifest(store)["parts"]
    planned = plan_parts(sites, today=today, manifest_parts={}, era5_years=era5_years)
    failures: list[dict[str, str]] = []
    parts: dict[str, Any] = {}
    for part in planned:
        entry = recorded.get(part.key)
        raw = store.get(part.key) if entry else None
        if entry is None or raw is None:
            failures.append(
                {"key": part.key, "rule": "not_in_manifest" if not entry else "file_missing"}
            )
            continue
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            failures.append({"key": part.key, "rule": "sha256_mismatch"})
        result = check_part(part, pd.read_parquet(io.BytesIO(raw)), today=today)
        failures += [{"key": part.key, "rule": r} for r in _HARD_COUNTS if result[r]]
        parts[part.key] = result
    return {
        "version": 1,
        "today": today.isoformat(),
        "planned": [p.key for p in planned],
        "passed": not failures,
        "failures": failures,
        "parts": parts,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """The report as a short page: failures, then each part with gaps or a lead-in."""
    lines = [
        f"# Weather coverage, {report['today']}",
        "",
        f"{'Passed' if report['passed'] else 'FAILED'}: {len(report['parts'])} of "
        f"{len(report['planned'])} planned parts checked, {len(report['failures'])} failure(s).",
        "",
    ]
    lines += [f"- **{f['rule']}:** `{f['key']}`" for f in report["failures"]]
    for key, part in sorted(report["parts"].items()):
        if not part["gaps"] and not part["lead_in_hours"]:
            continue
        lines += ["", f"## `{key}`", "", f"- lead-in hours: {part['lead_in_hours']}"]
        lines += [
            f"- gap in {g['variable']}: {g['first_utc']} to {g['last_utc']}, {g['hours']} h"
            for g in part["gaps"]
        ]
    return "\n".join(lines) + "\n"


def main() -> int:  # pragma: no cover  (real edges only)
    configure()
    settings = get_settings()
    session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
    store = S3Store(session.client("s3"), settings.data_bucket)
    report = check_store(store, TRAINING_SITES, today=datetime.now(UTC).date())
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stem = REPORT_DIR / f"coverage-{report['today']}"
    stem.with_suffix(".json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    stem.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
    gaps = sum(len(p["gaps"]) for p in report["parts"].values())
    log.info(
        "%d part(s) checked, %d failure(s), %d gap(s); report %s.md",
        len(report["parts"]),
        len(report["failures"]),
        gaps,
        stem,
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
