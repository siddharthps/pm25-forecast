"""City data check (T4, #9): the frozen D-006 rules as pure functions, plus one HTTP helper.

Every constant below is a frozen D-006 criterion. Changing one changes the city choice, so it
needs a new D-entry, and never after the check has run.

Field names are AQS daily-summary fields (checked on a real response, D-006 clarifications).
"""

from __future__ import annotations

import csv
import io
import logging
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

__all__ = [
    "BAD_AIR_UG_M3",
    "HISTORY_YEARS",
    "TEST_YEAR",
    "CityScore",
    "FetchError",
    "SiteDay",
    "choose_city",
    "fetch_json",
    "fetch_response",
    "good_years",
    "parse_airnow_active_pm25",
    "score_city",
    "site_days",
    "strip_values",
]

log = logging.getLogger(__name__)

# --- Frozen D-006 criteria --------------------------------------------------------------------
PARAMETER = "88101"  # PM2.5, local conditions
HOURLY_CODE = "1"  # sample_duration_code "1 HOUR": an hourly instrument's daily summary
MIN_HOURS = 18  # valid day: >= 18 of 24 hours
GOOD_YEAR_SHARE = 0.75  # good year: >= 75% of the year's days valid
MIN_GOOD_YEARS = 8
HISTORY_YEARS = range(2009, 2025)  # 2009-2024 (D-008 development period)
LAST_HISTORY_YEAR = 2024  # must itself be a good year
TEST_YEAR = 2025  # counts only; values dropped on read (D-008)
MIN_MONITORS = 5
BAD_AIR_UG_M3 = 35.0  # 24-hour primary PM2.5 NAAQS; a bad-air day is strictly above it
MIN_BAD_AIR_SHARE = 0.005
DEFAULT_CITY = "Chicago"

# Exceptional-event days are kept (D-006): AQS gives such days twice, with the event data
# included and excluded. Any other value is new to us, so the check stops instead of guessing.
KEEP_EVENTS = frozenset({"No Events", "Events Included"})
DROP_EVENTS = frozenset({"Events Excluded", "Concurred Events Excluded"})

# Every field of an AQS daily summary that carries a PM value (stripped from 2025 rows).
VALUE_FIELDS = frozenset({"arithmetic_mean", "first_max_value", "first_max_hour", "aqi"})


@dataclass(frozen=True)
class SiteDay:
    """One monitor (AQS site) on one local day."""

    valid: bool
    mean: float | None  # mean of the site's hourly instruments' daily means; None if dropped


@dataclass(frozen=True)
class CityScore:
    """A candidate's result against the frozen criteria."""

    name: str
    qualifying: tuple[str, ...]
    bad_air_share: float
    test_year_monitors: int
    weather_ok: bool
    passes: bool
    reasons: tuple[str, ...]  # why it failed; empty when it passes


def _site_id(r: Mapping[str, Any]) -> str:
    sid = f"{r['state_code']}{r['county_code']}{r['site_number']}"
    if len(sid) != 9 or not sid.isdigit():  # noqa: PLR2004  (2 + 3 + 4 digits)
        raise ValueError(f"unexpected AQS site id {sid!r}")
    return sid


def site_days(
    rows: Iterable[Mapping[str, Any]], *, keep_values: bool
) -> dict[tuple[str, date], SiteDay]:
    """Group AQS daily-summary rows into one SiteDay per (site, local date).

    Keeps only hourly PM2.5 instruments. `keep_values=False` drops the PM values as they are
    read (used for the 2025 test year).
    """
    per_instrument: dict[tuple[str, date, int], Mapping[str, Any]] = {}
    for r in rows:
        if str(r["parameter_code"]) != PARAMETER or str(r["sample_duration_code"]) != HOURLY_CODE:
            continue
        event = r["event_type"]
        if event in DROP_EVENTS:
            continue
        if event not in KEEP_EVENTS:
            raise ValueError(f"unknown event_type {event!r}: check D-006 before going on")
        inst = (_site_id(r), date.fromisoformat(r["date_local"]), int(r["poc"]))
        if inst in per_instrument:
            raise ValueError(f"duplicate instrument-day {inst}")
        per_instrument[inst] = r

    grouped: dict[tuple[str, date], list[Mapping[str, Any]]] = defaultdict(list)
    for (sid, day, _poc), r in per_instrument.items():
        grouped[(sid, day)].append(r)

    out: dict[tuple[str, date], SiteDay] = {}
    for site_day, instruments in grouped.items():
        valid = any(int(r["observation_count"]) >= MIN_HOURS for r in instruments)
        mean = None
        if keep_values:
            means = [float(r["arithmetic_mean"]) for r in instruments]
            mean = sum(means) / len(means)
        out[site_day] = SiteDay(valid=valid, mean=mean)
    return out


def strip_values(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Copies of `rows` without any PM value field: for the 2025 test year (D-008).

    Call this before 2025 rows are stored anywhere, so their values never reach disk.
    """
    return [{k: v for k, v in r.items() if k not in VALUE_FIELDS} for r in rows]


def _days_in_year(year: int) -> int:
    return (date(year + 1, 1, 1) - date(year, 1, 1)).days


def good_years(days: Mapping[tuple[str, date], SiteDay]) -> dict[str, set[int]]:
    """Return, per site, the calendar years with >= 75% valid days."""
    valid: dict[tuple[str, int], int] = defaultdict(int)
    for (sid, day), d in days.items():
        if d.valid:
            valid[(sid, day.year)] += 1
    out: dict[str, set[int]] = defaultdict(set)
    for (sid, year), n in valid.items():
        if n >= GOOD_YEAR_SHARE * _days_in_year(year):
            out[sid].add(year)
    return dict(out)


def parse_airnow_active_pm25(text: str) -> set[str]:
    """AQS site ids with an Active PM2.5 row in AirNow's Monitoring_Site_Locations_V2.dat."""
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    return {
        r["AQSID"]
        for r in reader
        if r.get("Parameter") == "PM2.5" and r.get("Status") == "Active" and r.get("AQSID")
    }


def score_city(
    name: str,
    *,
    history_rows: Iterable[Mapping[str, Any]],
    test_rows: Iterable[Mapping[str, Any]],
    airnow_active: set[str],
    weather_ok: bool,
) -> CityScore:
    """Score one candidate against every frozen D-006 rule.

    `test_rows` (2025) must already be stripped of PM values (`strip_values`).
    """
    test_rows = list(test_rows)
    if any(VALUE_FIELDS & r.keys() for r in test_rows):
        raise ValueError(f"{TEST_YEAR} rows still carry PM values: strip them before storing")
    hist = {
        k: v
        for k, v in site_days(history_rows, keep_values=True).items()
        if k[1].year in HISTORY_YEARS
    }
    test = {
        k: v for k, v in site_days(test_rows, keep_values=False).items() if k[1].year == TEST_YEAR
    }

    hist_good = good_years(hist)
    qualifying = tuple(
        sorted(
            sid
            for sid, years in hist_good.items()
            if len(years) >= MIN_GOOD_YEARS and LAST_HISTORY_YEAR in years and sid in airnow_active
        )
    )

    q = set(qualifying)
    monitor_days = [d for (sid, _), d in hist.items() if sid in q and d.valid]
    bad = sum(1 for d in monitor_days if d.mean is not None and d.mean > BAD_AIR_UG_M3)
    share = bad / len(monitor_days) if monitor_days else 0.0

    test_good = good_years(test)
    test_monitors = sum(1 for sid in qualifying if TEST_YEAR in test_good.get(sid, set()))

    reasons = []
    if len(qualifying) < MIN_MONITORS:
        reasons.append(f"{len(qualifying)} qualifying monitors (< {MIN_MONITORS})")
    if share < MIN_BAD_AIR_SHARE:
        reasons.append(f"bad-air share {share:.2%} (< {MIN_BAD_AIR_SHARE:.1%})")
    if test_monitors < MIN_MONITORS:
        reasons.append(f"{test_monitors} monitors with a good {TEST_YEAR} (< {MIN_MONITORS})")
    if not weather_ok:
        reasons.append("no weather coverage")

    return CityScore(
        name=name,
        qualifying=qualifying,
        bad_air_share=share,
        test_year_monitors=test_monitors,
        weather_ok=weather_ok,
        passes=not reasons,
        reasons=tuple(reasons),
    )


def choose_city(scores: Iterable[CityScore]) -> str | None:
    """Chicago if it passes; else most qualifying monitors, then higher bad-air share."""
    passing = [s for s in scores if s.passes]
    if any(s.name == DEFAULT_CITY for s in passing):
        return DEFAULT_CITY
    if not passing:
        return None
    best = max(passing, key=lambda s: (len(s.qualifying), s.bad_air_share))
    return best.name


TOO_MANY_REQUESTS = 429
SERVER_ERROR = 500


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == TOO_MANY_REQUESTS or code >= SERVER_ERROR
    return False


def _quiet_http_loggers() -> None:
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


class FetchError(RuntimeError):
    """A request that failed for good. Carries the HTTP status (None for a network error)."""

    def __init__(self, message: str, status: int | None) -> None:
        super().__init__(message)
        self.status = status


def fetch_response(
    client: httpx.Client,
    url: str,
    params: Mapping[str, str] | None = None,
    *,
    attempts: int = 4,
    backoff_s: float = 5.0,
) -> httpx.Response:
    """GET with retries on network errors, 429 and 5xx. Never logs the URL or the params.

    AQS takes credentials as query parameters, so failures are reported by type and status only.
    httpx and httpcore log every request URL at INFO/DEBUG; those loggers are held at WARNING so
    a credentialed URL can never reach a log, whatever level the caller's logging is set to.
    """
    _quiet_http_loggers()
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            status = "-" if code is None else code
            if not _retryable(exc) or attempt == attempts:
                msg = f"request failed after {attempt} attempt(s): {type(exc).__name__}, {status}"
                raise FetchError(msg, code) from None
            log.warning("attempt %d failed (%s, %s); retrying", attempt, type(exc).__name__, status)
            time.sleep(backoff_s * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


def fetch_json(
    client: httpx.Client,
    url: str,
    params: Mapping[str, str],
    *,
    attempts: int = 4,
    backoff_s: float = 5.0,
) -> Any:
    """`fetch_response`, decoded as JSON."""
    return fetch_response(client, url, params, attempts=attempts, backoff_s=backoff_s).json()
