"""The CAMS archive gap (#19, T14; D-052): how much easier the stitched history is than live.

For each target day from `FIRST_TARGET`, at each monitor, three daily means over the local day:

- **as issued:** CAMS's run started at 00 UTC on the issue day (`cams.issued_run_start`), from
  the Single Runs API;
- **stitched:** the history the test's CAMS baseline uses, from the bulk download;
- **observed:** AirNow, through the scoring path (validation, then the 18-hour daily rule).

The summary gives the MAE of each CAMS mean against the observed one, their difference, and the
mean absolute difference between the two CAMS means, over monitor-days with all three. Skipped
monitor-days are counted by their first reason. Declared in D-052 before any figure was seen;
descriptive only, never used to choose or adjust anything.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pandas as pd

from airwatch.forecast.run import day_means
from airwatch.timeutil import local_day_window_utc
from airwatch.validation.checks import ValidationFailedError, Window, run_checks
from airwatch.weather.cams import FIRST_RUN, daily_means, issued_run_start

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

__all__ = [
    "FIRST_TARGET",
    "SKIP_REASONS",
    "FetchDay",
    "FetchRun",
    "measure",
    "observed_means",
    "summarise",
    "target_days",
]

FIRST_TARGET = FIRST_RUN.date() + timedelta(days=1)
SKIP_REASONS = (
    "no_as_issued_run",
    "as_issued_incomplete",
    "stitched_incomplete",
    "observed_failed_validation",
    "no_observed",
)
PAIR_COLUMNS = ["site_id", "day", "as_issued", "stitched", "observed"]

FetchRun = Callable[[str, datetime], pd.DataFrame]
FetchDay = Callable[[date], tuple[pd.DataFrame, Mapping[str, int]]]


def target_days(today: date) -> list[date]:
    """Target days from `FIRST_TARGET` to two days before `today`, when AirNow is settled."""
    last = today - timedelta(days=2)
    return [FIRST_TARGET + timedelta(days=i) for i in range((last - FIRST_TARGET).days + 1)]


def observed_means(
    fetch_day: FetchDay, day: date, tz: ZoneInfo, sites: Iterable[str]
) -> dict[str, float] | None:
    """Each monitor's valid observed mean for `day`, as scoring takes it; None on a hard failure."""
    wanted = tuple(sites)
    hourly, drops = fetch_day(day)
    result = run_checks(
        hourly,
        window=Window(*local_day_window_utc(day, tz)),
        tz=tz,
        sites=wanted,
        ingest_drops=drops,
    )
    try:
        result.raise_if_failed()
    except ValidationFailedError:
        return None
    actuals, _ = day_means(result.clean, day, tz, wanted)
    return {site: mean for site, (mean, _) in actuals.items()}


def _hours_and_mean(means: pd.DataFrame, site: str, day: date) -> tuple[int, float]:
    row = means[(means["site_id"] == site) & (means["day"] == day)]
    if row.empty:
        return 0, float("nan")
    return int(row["hours"].iloc[0]), float(row["cams_mean"].iloc[0])


def measure(  # noqa: PLR0913  (the days, the monitors, the zone and each injected edge)
    days: Iterable[date],
    sites: Iterable[str],
    tz: ZoneInfo,
    *,
    fetch_run: FetchRun,
    stitched_rows: pd.DataFrame,
    fetch_day: FetchDay,
) -> dict[str, Any]:
    """The D-052 gap over `days` at `sites`."""
    wanted, targets = tuple(sites), list(days)
    stitched = daily_means(stitched_rows, targets, tz)
    pairs: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for day in targets:
        observed = observed_means(fetch_day, day, tz, wanted)
        for site in wanted:
            issued_hours, issued = _hours_and_mean(
                daily_means(fetch_run(site, issued_run_start(day)), [day], tz), site, day
            )
            _, stitched_mean = _hours_and_mean(stitched, site, day)
            if issued_hours == 0:
                skipped["no_as_issued_run"] += 1
            elif math.isnan(issued):
                skipped["as_issued_incomplete"] += 1
            elif math.isnan(stitched_mean):
                skipped["stitched_incomplete"] += 1
            elif observed is None:
                skipped["observed_failed_validation"] += 1
            elif site not in observed:
                skipped["no_observed"] += 1
            else:
                pairs.append(
                    {
                        "site_id": site,
                        "day": day,
                        "as_issued": issued,
                        "stitched": stitched_mean,
                        "observed": observed[site],
                    }
                )
    return summarise(pd.DataFrame(pairs, columns=PAIR_COLUMNS), skipped)


def summarise(pairs: pd.DataFrame, skipped: Mapping[str, int]) -> dict[str, Any]:
    """The declared figures (D-052) over `pairs`, and the skips by reason."""
    summary: dict[str, Any] = {
        "monitor_days": len(pairs),
        "first_day": None,
        "last_day": None,
        "mae_as_issued": None,
        "mae_stitched": None,
        "mae_difference": None,
        "mean_abs_cams_difference": None,
        "skipped": {reason: int(skipped.get(reason, 0)) for reason in SKIP_REASONS},
    }
    if pairs.empty:
        return summary
    as_issued = float((pairs["as_issued"] - pairs["observed"]).abs().mean())
    stitched = float((pairs["stitched"] - pairs["observed"]).abs().mean())
    summary |= {
        "first_day": min(pairs["day"]).isoformat(),
        "last_day": max(pairs["day"]).isoformat(),
        "mae_as_issued": as_issued,
        "mae_stitched": stitched,
        "mae_difference": as_issued - stitched,
        "mean_abs_cams_difference": float((pairs["as_issued"] - pairs["stitched"]).abs().mean()),
    }
    return summary
