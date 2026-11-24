"""The daily CAMS save (#78; D-052, D-053): CAMS's forecast for the target day, as issued.

Each scheduled run, after the forecast and scoring, saves CAMS global's PM2.5 for the target day
at every monitor, from the live Air Quality API (`cams.fetch_live`), to
`records/forecast_date=<target>/cams.json` in the private bucket:

- **Create-only:** a run that finds the file fetches nothing, and a lost race keeps the file
  already there, so a save is never changed once written.
- **As issued:** every monitor must come from one run, and that run may not have started after
  the as-issued run (00 UTC on the issue day). An older run is saved with its own start. The
  file records when the run was published and whether that was before the issue time.
- **Per monitor:** the 24 hourly values of the target's local day, the hours present, and the
  daily mean when all 24 are (D-052).

A refusal is a `CamsSaveError` whose message holds rule names, dates and counts, never a value.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

from airwatch.errors import ReportableError
from airwatch.forecast.record import Store
from airwatch.timeutil import ensure_utc, issue_time_utc, local_day_window_utc
from airwatch.weather.cams import VARIABLE, daily_means, issued_run_start

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

__all__ = [
    "SAVE_VERSION",
    "CamsSaveError",
    "FetchCams",
    "SaveOutcome",
    "build_save",
    "cams_key",
    "save_cams",
]

SAVE_VERSION = 1
FetchCams = Callable[[str, date], pd.DataFrame]


class CamsSaveError(ReportableError):
    """A CAMS save refused by a named rule (the message starts with the rule)."""


@dataclass(frozen=True)
class SaveOutcome:
    target: date
    status: str
    save: dict[str, Any] | None


def cams_key(target: date) -> str:
    """The save's key, beside the forecast record of the same target day."""
    return f"records/forecast_date={target.isoformat()}/cams.json"


def _iso(ts: Any) -> str:
    return ensure_utc(pd.Timestamp(ts).to_pydatetime()).isoformat()


def _one_run(rows: pd.DataFrame, target: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    runs = rows[["run_start_utc", "available_at_utc"]].drop_duplicates()
    if len(runs) != 1:
        raise CamsSaveError(f"mixed_runs: {target}: the monitors came from {len(runs)} runs")
    start, available = runs.iloc[0]
    if start > pd.Timestamp(issued_run_start(target)):
        raise CamsSaveError(
            f"run_after_as_issued: {target}: the run started after "
            f"{issued_run_start(target).isoformat()}"
        )
    return start, available


def _monitor(rows: pd.DataFrame, target: date, tz: ZoneInfo) -> dict[str, Any]:
    start, end = local_day_window_utc(target, tz)
    inside = rows[(rows["valid_utc"] >= start) & (rows["valid_utc"] < end)].sort_values("valid_utc")
    mean = daily_means(rows, [target], tz)["cams_mean"]
    value = float(mean.iloc[0]) if len(mean) else math.nan
    hourly = [
        {"valid_utc": _iso(t), VARIABLE: None if math.isnan(v) else float(v)}
        for t, v in zip(inside["valid_utc"], inside[VARIABLE], strict=True)
    ]
    return {
        "hourly": hourly,
        "hours": sum(1 for h in hourly if h[VARIABLE] is not None),
        "mean_ug_m3": None if math.isnan(value) else value,
    }


def build_save(
    target: date, rows: pd.DataFrame, *, tz: ZoneInfo, sites: Iterable[str], fetched_utc: datetime
) -> dict[str, Any]:
    """The file's content, from every monitor's live rows; refused by a named rule."""
    wanted = tuple(sites)
    missing = [s for s in wanted if s not in set(rows["site_id"])]
    if missing:
        raise CamsSaveError(f"monitor_missing: {target}: {len(missing)} monitor(s) without rows")
    run_start, run_available = _one_run(rows, target)
    issue = issue_time_utc(target)
    return {
        "version": SAVE_VERSION,
        "forecast_date": target.isoformat(),
        "city_tz": tz.key,
        "source": "open-meteo air-quality api",
        "model": "cams_global",
        "variable": VARIABLE,
        "run_start_utc": _iso(run_start),
        "run_available_utc": _iso(run_available),
        "issue_time_utc": issue.isoformat(),
        "published_before_issue": bool(run_available <= pd.Timestamp(issue)),
        "fetched_at_utc": ensure_utc(fetched_utc).isoformat(),
        "monitors": {s: _monitor(rows[rows["site_id"] == s], target, tz) for s in wanted},
    }


def _encode(save: dict[str, Any]) -> bytes:
    return json.dumps(save, indent=1, sort_keys=True, allow_nan=False).encode("utf-8")


def save_cams(  # noqa: PLR0913  (the day, each injected edge and the run's context)
    target: date,
    *,
    fetch_cams: FetchCams,
    private: Store,
    sites: Iterable[str],
    tz: ZoneInfo,
    now: Callable[[], datetime],
    write: bool,
) -> SaveOutcome:
    """Save CAMS as issued for `target` once. `write=False` fetches and builds, writes nothing."""
    key = cams_key(target)
    existing = private.get(key)
    if existing is not None:
        return SaveOutcome(target, "already_saved", json.loads(existing))
    wanted = tuple(sites)
    rows = pd.concat([fetch_cams(site, target) for site in wanted], ignore_index=True)
    save = build_save(target, rows, tz=tz, sites=wanted, fetched_utc=now())
    if not write:
        return SaveOutcome(target, "dry_run", save)
    if private.create_if_absent(key, _encode(save)):
        return SaveOutcome(target, "saved", save)
    stored = private.get(key)
    return SaveOutcome(target, "already_saved", json.loads(stored) if stored else save)
