"""The durable record of each day's forecast (#13, T6; D-034): private, written at most once.

`records/forecast_date=<target day>/forecast.json` is created with S3's conditional write
(`S3Store.create_if_absent`). The record is the proof that a day's forecast exists: the watchdog
(T9), scoring (T10) and the page (T7) all start from it, never from a local file.

If another run's record is already there, that record wins: it's read back and used, so the
day's published forecast can never be one that wasn't recorded.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Protocol

from airwatch.errors import ReportableError
from airwatch.timeutil import ISSUE_TZ, ensure_utc
from airwatch.validation.checks import ValidationResult

__all__ = [
    "RECORD_VERSION",
    "SCORE_PREFIX",
    "Store",
    "build_record",
    "encode",
    "record_key",
    "report_key",
    "score_key",
    "write_once",
]

RECORD_VERSION = 1
SCORE_PREFIX = "reports/scores/"


class Store(Protocol):
    """What the forecast needs from a bucket (airwatch.storage.S3Store, or a test fake)."""

    def get(self, key: str) -> bytes | None: ...
    def put(self, key: str, data: bytes) -> None: ...
    def create_if_absent(self, key: str, data: bytes) -> bool: ...
    def list_keys(self, prefix: str) -> list[str]: ...


def record_key(target_day: date) -> str:
    """Named after the day being forecast (owner's choice, D-034)."""
    return f"records/forecast_date={target_day.isoformat()}/forecast.json"


def report_key(target_day: date) -> str:
    """The validation report of the run for `target_day` (overwritten by a rerun: versioned)."""
    return f"reports/validation/forecast_date={target_day.isoformat()}/validation.json"


def score_key(target_day: date) -> str:
    """The score of the forecast for `target_day` (T10, D-042), written once."""
    return f"{SCORE_PREFIX}forecast_date={target_day.isoformat()}/score.json"


def build_record(  # noqa: PLR0913  (each argument is one part of the record)
    *,
    target_day: date,
    issue_at_utc: datetime,
    observed_day: date,
    generated_at_utc: datetime,
    city_tz: str,
    forecasts: list[dict[str, Any]],
    no_forecast: list[dict[str, Any]],
    validation: ValidationResult,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """The record as JSON-ready data. Values are stored unrounded; rounding is for display."""
    issued = ensure_utc(issue_at_utc)
    return {
        "version": RECORD_VERSION,
        "forecast_date": target_day.isoformat(),
        "issue_date": issued.astimezone(ISSUE_TZ).date().isoformat(),
        "issued_at_utc": issued.isoformat(),
        "observed_day": observed_day.isoformat(),
        "generated_at_utc": ensure_utc(generated_at_utc).isoformat(),
        "method": "persistence",
        "city_tz": city_tz,
        "forecasts": forecasts,
        "no_forecast": no_forecast,
        "inputs": inputs,
        "validation": {
            "passed": validation.passed,
            "counts": {f.rule: f.count for f in validation.findings},
        },
    }


def encode(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")


class RecordUnreadableError(ReportableError):
    """A write was refused as existing, but the existing record could not be read."""


def write_once(store: Store, record: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Create the record if absent. Returns (created, the record now stored)."""
    key = record_key(date.fromisoformat(record["forecast_date"]))
    if store.create_if_absent(key, encode(record)):
        return True, record
    raw = store.get(key)
    if raw is None:
        raise RecordUnreadableError(f"record refused as existing but not readable: {key}")
    existing: dict[str, Any] = json.loads(raw)
    return False, existing
