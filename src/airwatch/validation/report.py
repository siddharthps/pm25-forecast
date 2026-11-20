"""Validation report (#12, T12a): one JSON + one Markdown file per run, counts only.

    cd ~/code/pm25-forecast
    AWS_PROFILE=pm25 uv run python -m airwatch.validation.report --source aqs     # bulk history
    uv run python -m airwatch.validation.report --source airnow                   # yesterday
    AWS_PROFILE=pm25 uv run python -m airwatch.validation.report --source all

Reads only: the private bucket's AQS download (its manifest and parts) and AirNow's public
hourly files. Writes the reports to `data/reports/validation/` (gitignored). Exits 1 when a hard
rule fails, so a caller can stop. Reports and logs carry counts, sites and times, never a
measurement or a credential.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import boto3
import httpx
import pandas as pd

from airwatch.config import get_settings
from airwatch.observations.airnow import fetch_local_day
from airwatch.observations.aqs_bulk import FIRST_YEAR, MANIFEST_KEY, S3Store
from airwatch.observations.schema import HOURLY_COLUMNS, concat_hourly, validate_hourly
from airwatch.observations.sites import TRAINING_SITES
from airwatch.timeutil import ensure_utc, local_day_window_utc
from airwatch.validation.checks import ValidationResult, Window, run_checks

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

__all__ = [
    "MARKDOWN_ITEM_CAP",
    "REPORT_DIR",
    "build_report",
    "load_aqs_bulk",
    "main",
    "render_markdown",
    "save_report",
    "validate_airnow_day",
    "validate_aqs_bulk",
]

log = logging.getLogger(__name__)

REPORT_VERSION = 1
REPORT_DIR = Path("data/reports/validation")
MARKDOWN_ITEM_CAP = 20  # the JSON keeps every item; the Markdown shows the first few per rule


# --- the report ----------------------------------------------------------------------------


def build_report(
    result: ValidationResult,
    *,
    source: str,
    window: Window,
    generated_at_utc: datetime,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The run as plain JSON-ready data."""
    generated = ensure_utc(generated_at_utc)
    return {
        "version": REPORT_VERSION,
        "source": source,
        "generated_at_utc": generated.isoformat(),
        "window_utc": {"start": window.start.isoformat(), "end": window.end.isoformat()},
        "passed": result.passed,
        "rows_in": result.rows_in,
        "rows_kept": len(result.clean),
        "findings": [
            {
                "problem_class": f.problem_class,
                "rule": f.rule,
                "severity": str(f.severity),
                "count": f.count,
                "excluded": f.excluded,
                "items": [dict(i) for i in f.items],
            }
            for f in result.findings
        ],
        "extra": dict(extra or {}),
    }


def render_markdown(report: dict[str, Any]) -> str:
    """A short human-readable view: the verdict first, then one table row per rule."""
    findings: list[dict[str, Any]] = report["findings"]
    hard = [f for f in findings if f["severity"] == "hard" and f["count"]]
    verdict = (
        "**PASSED**: no hard rule caught anything."
        if report["passed"]
        else "**FAILED**: " + ", ".join(f"`{f['rule']}` ({f['count']})" for f in hard)
    )
    window = report["window_utc"]
    lines = [
        f"# Validation report: {report['source']}",
        "",
        f"Generated {report['generated_at_utc']} · coverage window {window['start']} to "
        f"{window['end']} (UTC, end excluded)",
        "",
        verdict,
        "",
        f"Rows: {report['rows_in']} in, {report['rows_kept']} kept "
        f"({report['rows_in'] - report['rows_kept']} excluded).",
    ]
    if report["extra"]:
        lines += ["", "Run facts: " + ", ".join(f"{k} {v}" for k, v in report["extra"].items())]
    lines += [
        "",
        "| Class | Rule | Severity | Count | Excluded |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {f['problem_class']} | `{f['rule']}` | {f['severity']} | {f['count']} | "
        f"{f['excluded']} |"
        for f in findings
    ]
    for f in findings:
        if not f["items"]:
            continue
        lines += ["", f"## `{f['rule']}`", ""]
        shown = f["items"][:MARKDOWN_ITEM_CAP]
        lines += ["- " + ", ".join(f"{k} {v}" for k, v in item.items()) for item in shown]
        if len(f["items"]) > MARKDOWN_ITEM_CAP:
            lines.append(f"- … and {len(f['items']) - MARKDOWN_ITEM_CAP} more (see the JSON)")
    return "\n".join(lines) + "\n"


def save_report(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    """Write `validation_<source>_<UTC time>.json` and `.md`. Never overwrites a report."""
    stamp = datetime.fromisoformat(report["generated_at_utc"]).strftime("%Y%m%dT%H%M%SZ")
    stem = out_dir / f"validation_{report['source']}_{stamp}"
    json_path, md_path = stem.with_suffix(".json"), stem.with_suffix(".md")
    for path in (json_path, md_path):
        if path.exists():
            raise FileExistsError(f"report already exists: {path.name}")
    out_dir.mkdir(parents=True, exist_ok=True)
    with json_path.open("x", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    with md_path.open("x", encoding="utf-8") as fh:
        fh.write(render_markdown(report))
    return json_path, md_path


# --- loading the sources (read-only) -------------------------------------------------------


def load_aqs_bulk(store: S3Store) -> tuple[pd.DataFrame, int]:
    """Every part the manifest lists, stacked; and how many parts. Checks each part's row count."""
    raw = store.get(MANIFEST_KEY)
    if raw is None:
        raise FileNotFoundError("no AQS bulk manifest in the bucket: run the download first")
    parts: dict[str, dict[str, Any]] = json.loads(raw)["parts"]
    frames = []
    for key in sorted(parts):
        data = store.get(key)
        if data is None:
            raise FileNotFoundError(f"manifest lists a part that is missing: {key}")
        df = pd.read_parquet(io.BytesIO(data), engine="pyarrow").astype(HOURLY_COLUMNS)
        if len(df) != parts[key]["rows"]:
            raise ValueError(f"{key}: {len(df)} rows, manifest says {parts[key]['rows']}")
        frames.append(df)
    hourly = concat_hourly(frames)
    validate_hourly(hourly)
    return hourly, len(parts)


def _aqs_window(today: date, tz: ZoneInfo) -> Window:
    """FIRST_YEAR to the start of this year: the final years only (a year is final once over)."""
    start = local_day_window_utc(date(FIRST_YEAR, 1, 1), tz)[0]
    end = local_day_window_utc(date(today.year, 1, 1), tz)[0]
    return Window(start, end)


# --- command line --------------------------------------------------------------------------


def _summarise(source: str, result: ValidationResult, paths: tuple[Path, Path]) -> None:
    counts = ", ".join(f"{f.rule} {f.count}" for f in result.findings if f.count)
    log.info(
        "%s: %s; %d rows in, %d kept; %s. Report: %s",
        source,
        "passed" if result.passed else "FAILED",
        result.rows_in,
        len(result.clean),
        counts or "nothing flagged",
        paths[1],
    )


def validate_aqs_bulk(
    store: S3Store, *, tz: ZoneInfo, sites: Sequence[str], now: datetime, out_dir: Path
) -> ValidationResult:
    """Check the whole bulk download (final years for coverage) and save its report."""
    hourly, n_parts = load_aqs_bulk(store)
    window = _aqs_window(ensure_utc(now).astimezone(tz).date(), tz)
    result = run_checks(hourly, window=window, tz=tz, sites=sites, coverage_from="first_reading")
    report = build_report(
        result, source="aqs", window=window, generated_at_utc=now, extra={"parts": n_parts}
    )
    _summarise("aqs", result, save_report(report, out_dir))
    return result


def validate_airnow_day(  # noqa: PLR0913  (the client, the day, and the run's context)
    client: httpx.Client,
    day: date,
    *,
    tz: ZoneInfo,
    sites: Sequence[str],
    now: datetime,
    out_dir: Path,
) -> ValidationResult:
    """Check one local day of AirNow (as the daily flow sees it) and save its report."""
    hourly, drops = fetch_local_day(client, day, tz, sites)
    window = Window(*local_day_window_utc(day, tz))
    result = run_checks(hourly, window=window, tz=tz, sites=sites, ingest_drops=drops)
    report = build_report(
        result,
        source="airnow",
        window=window,
        generated_at_utc=now,
        extra={"local_day": day.isoformat()},
    )
    _summarise("airnow", result, save_report(report, out_dir))
    return result


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover  (real edges only)
    parser = argparse.ArgumentParser(description="Data-quality report (reads only).")
    parser.add_argument("--source", choices=["aqs", "airnow", "all"], required=True)
    parser.add_argument(
        "--day", type=date.fromisoformat, help="AirNow local day (default: yesterday)"
    )
    parser.add_argument("--out", type=Path, default=REPORT_DIR)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    for name in ("botocore", "boto3", "urllib3"):
        logging.getLogger(name).setLevel(logging.ERROR)

    settings = get_settings()
    tz = settings.city_tz
    now = datetime.now(UTC).replace(microsecond=0)
    passed = True
    if args.source in ("aqs", "all"):
        session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
        store = S3Store(session.client("s3"), settings.data_bucket)
        result = validate_aqs_bulk(store, tz=tz, sites=TRAINING_SITES, now=now, out_dir=args.out)
        passed &= result.passed
    if args.source in ("airnow", "all"):
        day = args.day or (now.astimezone(tz) - timedelta(days=1)).date()
        with httpx.Client(timeout=60) as client:
            result = validate_airnow_day(
                client, day, tz=tz, sites=TRAINING_SITES, now=now, out_dir=args.out
            )
        passed &= result.passed
    return 0 if passed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
