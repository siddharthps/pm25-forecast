"""Daily scoring: each recorded day against its settled AirNow actuals (#17, T10; D-013, D-042).

Day T is scored on the morning of T+2 (owner's choice, 2026-11-20). By then every AirNow file for T
has stopped changing (they're rewritten for about 7.7 hours, D-034), so a fresh download of T gives
all its hours and the same answer whenever the run happens. The 06:00 forecast's own view of a day
would miss its last hours.

- **Actual:** each monitor's mean over the local day, with the forecast's own rule (18+ valid
  hours, `day_means`), after the same validation. A monitor without one is left out and counted.
- **Score:** per monitor, forecast minus actual (positive = forecast too high) and its absolute
  value; for the city, the mean absolute error (MAE) and the mean error (bias) over the scored
  monitors. Values are kept unrounded; rounding is for the public file.
- **Once per day:** a score is written create-only under `reports/scores/` and then reused, so a
  retry or a second run never changes it. A dry run computes and writes nothing.
- Each run looks back a week, so a day missed by a failed run is scored by the next one. A failing
  day doesn't stop the others; the failures are raised together at the end.

Live scores are preliminary (AirNow). The AQS re-score comes later (T26, D-004).
"""

import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from airwatch.forecast.record import SCORE_PREFIX, Store, record_key, score_key
from airwatch.forecast.run import FetchDay, day_means, latest_target_day
from airwatch.timeutil import ensure_utc, issue_time_utc, local_day_window_utc
from airwatch.validation.checks import Window, run_checks

__all__ = [
    "LOOKBACK_DAYS",
    "SCORE_PREFIX",
    "NotSettledError",
    "ScoreOutcome",
    "ScoringError",
    "due_days",
    "score_day",
    "score_due",
    "score_key",
    "score_ready_at",
]

log = logging.getLogger(__name__)

LOOKBACK_DAYS = 7
SETTLE_DAYS = 2

Status = Literal["scored", "already_scored", "dry_run", "no_record"]


class NotSettledError(RuntimeError):
    """Asked to score a day before the T+2 morning run: its AirNow files may still change."""


class ScoringError(RuntimeError):
    """One or more days couldn't be scored. They stay unscored, so a later run tries again."""


@dataclass(frozen=True)
class ScoreOutcome:
    day: date
    status: Status
    score: dict[str, Any] | None


def score_ready_at(day: date) -> datetime:
    """06:00 Chicago on `day` + 2: the issue time of the run that scores it."""
    return issue_time_utc(day + timedelta(days=SETTLE_DAYS + 1))


def due_days(now: datetime) -> list[date]:
    """The days a run at `now` scores, newest first: the latest settled day and the week before."""
    latest = latest_target_day(now) - timedelta(days=SETTLE_DAYS + 1)
    return [latest - timedelta(days=i) for i in range(LOOKBACK_DAYS)]


def _encode(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def build_score(
    record: dict[str, Any],
    actuals: dict[str, tuple[float, int]],
    hours_without: dict[str, int],
    scored_at: datetime,
) -> dict[str, Any]:
    """The score of one record against its actuals, as JSON-ready data."""
    monitors: list[dict[str, Any]] = []
    no_actual: list[dict[str, Any]] = []
    for f in sorted(record["forecasts"], key=lambda f: f["site_id"]):
        site = f["site_id"]
        if site in actuals:
            actual, n = actuals[site]
            error = float(f["forecast_ug_m3"]) - actual
            monitors.append(
                {
                    "site_id": site,
                    "forecast_ug_m3": float(f["forecast_ug_m3"]),
                    "actual_ug_m3": actual,
                    "error_ug_m3": error,
                    "abs_error_ug_m3": abs(error),
                    "n_hours": n,
                }
            )
        else:
            no_actual.append({"site_id": site, "n_hours": hours_without.get(site, 0)})
    errors = [m["error_ug_m3"] for m in monitors]
    return {
        "forecast_date": record["forecast_date"],
        "scored_at_utc": ensure_utc(scored_at).isoformat(),
        "actual_source": "airnow",
        "city_tz": record["city_tz"],
        "monitors": monitors,
        "no_actual": no_actual,
        "city": {
            "n_scored": len(monitors),
            "mae_ug_m3": _mean([abs(e) for e in errors]),
            "bias_ug_m3": _mean(errors),
        },
    }


def score_day(  # noqa: PLR0913  (each argument is one injected edge or the run's context)
    day: date,
    *,
    fetch_day: FetchDay,
    private: Store,
    sites: Iterable[str],
    now: datetime,
    write: bool,
) -> ScoreOutcome:
    """Score one day once. `write=False` computes and writes nothing (a dry run)."""
    if ensure_utc(now) < score_ready_at(day):
        raise NotSettledError(f"{day}: scored from {score_ready_at(day).isoformat()}")
    existing = private.get(score_key(day))
    if existing is not None:
        return ScoreOutcome(day, "already_scored", json.loads(existing))
    raw_record = private.get(record_key(day))
    if raw_record is None:
        return ScoreOutcome(day, "no_record", None)
    record = json.loads(raw_record)
    tz = ZoneInfo(record["city_tz"])
    wanted = tuple(sites)
    hourly, drops = fetch_day(day)
    result = run_checks(
        hourly,
        window=Window(*local_day_window_utc(day, tz)),
        tz=tz,
        sites=wanted,
        ingest_drops=drops,
    )
    result.raise_if_failed()
    actuals, hours_without = day_means(result.clean, day, tz, wanted)
    score = build_score(record, actuals, hours_without, now)
    if not write:
        return ScoreOutcome(day, "dry_run", score)
    if private.create_if_absent(score_key(day), _encode(score)):
        return ScoreOutcome(day, "scored", score)
    stored = private.get(score_key(day))
    return ScoreOutcome(day, "already_scored", json.loads(stored) if stored else score)


def score_due(
    *,
    fetch_day: FetchDay,
    private: Store,
    sites: Iterable[str],
    now: Callable[[], datetime],
    write: bool,
) -> list[ScoreOutcome]:
    """Score every due day not yet scored; raise ScoringError at the end if any day failed."""
    at = now()
    wanted = tuple(sites)
    outcomes: list[ScoreOutcome] = []
    failed: list[str] = []
    for day in due_days(at):
        try:
            outcome = score_day(
                day, fetch_day=fetch_day, private=private, sites=wanted, now=at, write=write
            )
        except Exception as exc:
            failed.append(f"{day.isoformat()} ({type(exc).__name__})")
            log.exception("%s: scoring failed", day)
            continue
        outcomes.append(outcome)
        if outcome.score is not None and outcome.status != "already_scored":
            city = outcome.score["city"]
            log.info(
                "%s: %s, %d monitor(s), MAE %s µg/m³",
                day,
                outcome.status,
                city["n_scored"],
                "n/a" if city["mae_ug_m3"] is None else f"{city['mae_ug_m3']:.2f}",
            )
    if failed:
        raise ScoringError("couldn't score " + ", ".join(failed))
    return outcomes
