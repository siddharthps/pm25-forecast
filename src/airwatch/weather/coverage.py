"""The weather download's coverage check (#19, T14; D-051, D-052): every hour, every value.

    cd ~/code/pm25-forecast
    AWS_PROFILE=pm25 uv run python -m airwatch.weather.coverage   # reads only; writes the report

Reads the bulk download's manifest and parts from the private bucket and checks each planned
part (`airwatch.weather.bulk.plan_parts`, as if nothing were done) against its own days:

- **hard** (`failures`, exit 1): `not_in_manifest`, `file_missing`, `sha256_mismatch` (the file
  isn't the one recorded), `missing_hours` and `duplicate_hours` (a stamp absent or repeated).
  T12b's dates (#20, D-054): `hours_outside_part` (a stamp outside the part's days, so also any
  hour after yesterday), `run_after_valid` (a forecast whose run starts after its hour) and
  `available_before_run` (a row available before its run started).
- **reported:** `gaps`, each run of consecutive missing values in one variable, with its first
  and last hour. The GFS archive's known empty start, before `ARCHIVE_COMPLETE_FROM` (D-051),
  is counted as `lead_in_hours` instead. `outside_physical_range`: per variable, how many
  values fall below or above `PHYSICAL_RANGE` (kept as received; D-031).

Units and the grid point are checked when a response is read (`airwatch.weather.openmeteo`,
`airwatch.weather.cams`), so a wrong unit or a far grid point never reaches the store.

The report holds keys, variables, times and counts, never a value. It goes to
`data/reports/weather/` (gitignored).
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

__all__ = [
    "ARCHIVE_COMPLETE_FROM",
    "PHYSICAL_RANGE",
    "REPORT_DIR",
    "check_part",
    "check_store",
    "render_markdown",
]

log = logging.getLogger(__name__)

ARCHIVE_COMPLETE_FROM = datetime(2024, 1, 21, 12, tzinfo=UTC)
REPORT_DIR = Path("data/reports/weather")
_HOUR = timedelta(hours=1)
_HARD_COUNTS = (
    "missing_hours",
    "duplicate_hours",
    "hours_outside_part",
    "run_after_valid",
    "available_before_run",
)
PHYSICAL_RANGE: dict[str, tuple[float, float]] = {
    "temperature_2m": (-60.0, 60.0),
    "relative_humidity_2m": (0.0, 100.0),
    "wind_speed_10m": (0.0, 400.0),
    "wind_direction_10m": (0.0, 360.0),
    "precipitation": (0.0, 500.0),
    "surface_pressure": (500.0, 1100.0),
    "cloud_cover": (0.0, 100.0),
    "shortwave_radiation": (0.0, 1500.0),
    "pm2_5": (0.0, 10000.0),
}
"""Each variable's possible values, in its stored unit (`openmeteo.UNITS`, µg/m³ for CAMS).
Percentages, directions and non-negative amounts by definition; the temperature, pressure,
wind, rain and sunlight bounds are generous limits far outside anything Phoenix sees (D-054)."""


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
    runs = pd.to_datetime(df["run_start_utc"], utc=True)
    available = pd.to_datetime(df["available_at_utc"], utc=True)
    has_run = runs.notna()
    return {
        "source": part.source.value,
        "site_id": part.site_id,
        "year": part.year,
        "expected_hours": len(expected),
        "rows": len(df),
        "missing_hours": int((~expected.isin(stamps)).sum()),
        "duplicate_hours": int(stamps.duplicated().sum()),
        "hours_outside_part": int((~stamps.isin(expected)).sum()),
        "run_after_valid": int((has_run & (runs > stamps)).sum()),
        "available_before_run": int((has_run & (available < runs)).sum()),
        "lead_in_hours": lead_in_hours,
        "gaps": gaps,
        "outside_physical_range": _outside_physical(df, part.variables),
    }


def _outside_physical(df: pd.DataFrame, variables: Iterable[str]) -> list[dict[str, Any]]:
    """Per variable, how many values lie below or above `PHYSICAL_RANGE` (missing ones: gaps)."""
    out = []
    for v in variables:
        lo, hi = PHYSICAL_RANGE[v]
        low, high = int((df[v] < lo).sum()), int((df[v] > hi).sum())
        if low or high:
            out.append({"variable": v, "low": low, "high": high})
    return out


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
        if not part["gaps"] and not part["lead_in_hours"] and not part["outside_physical_range"]:
            continue
        lines += ["", f"## `{key}`", "", f"- lead-in hours: {part['lead_in_hours']}"]
        lines += [
            f"- gap in {g['variable']}: {g['first_utc']} to {g['last_utc']}, {g['hours']} h"
            for g in part["gaps"]
        ]
        lines += [
            f"- outside the physical range in {r['variable']}: {r['low']} low, {r['high']} high"
            for r in part["outside_physical_range"]
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
