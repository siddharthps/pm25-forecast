"""CAMS global PM2.5 from Open-Meteo (#19, T14; D-052): the stitched history and single runs.

Two sources, `pm2_5` (instant, µg/m³) at each monitor's coordinates:

- `HISTORY`: the Air Quality API with `domains=cams_global`, from 2022-08-04. It is **stitched**:
  each hour comes from the first 12 hours of the run started at or before it, so it is close to
  CAMS's analysis, not a day-ahead forecast. It is the test year's CAMS baseline (D-009), a bar
  stronger than CAMS was live, and the write-up says so.
- `RUN`: the Single Runs API with `models=cams_global` and `run=`, from the 00 UTC run of
  2026-04-02. "As issued" for a target day is the run started at 00 UTC on the issue day
  (`issued_run_start`). The gap between the two is measured on these runs (D-052).
- `LIVE`: the Air Quality API's forecast for the target's UTC days, read between two reads of
  the metadata naming its run (`fetch_live`), for the daily save (D-053).

Rows carry the run each hour came from and when that run was out: for `LIVE`, the metadata's
times; otherwise its start plus `PUBLISH_DELAY`, rounded up from the delays read there. Every
response is checked before it becomes rows; a refusal is a `WeatherResponseError` whose message
holds rule names, counts and dates, never a value.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import pandas as pd

from airwatch.observations.metadata import fetch_json
from airwatch.observations.sites import SITE_COORDS
from airwatch.timeutil import ensure_utc, issue_time_utc, local_day_window_utc
from airwatch.weather.openmeteo import LiveRun, WeatherResponseError, parse_live_run

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    import httpx

__all__ = [
    "COLUMNS",
    "CYCLE",
    "FIRST_RUN",
    "HISTORY_START",
    "MAX_GRID_OFFSET_DEG",
    "META_URL",
    "PUBLISH_DELAY",
    "RUN_LENGTH",
    "STITCHED_LEADS",
    "UNIT",
    "URLS",
    "VARIABLE",
    "CamsQuery",
    "CamsSource",
    "daily_means",
    "fetch",
    "fetch_live",
    "issued_run_start",
    "parse",
    "stitched_run_start",
]


class CamsSource(StrEnum):
    HISTORY = "cams_history"
    RUN = "cams_run"
    LIVE = "cams_live"


URLS = {
    CamsSource.HISTORY: "https://air-quality-api.open-meteo.com/v1/air-quality",
    CamsSource.RUN: "https://single-runs-api.open-meteo.com/v1/forecast",
    CamsSource.LIVE: "https://air-quality-api.open-meteo.com/v1/air-quality",
}
META_URL = "https://air-quality-api.open-meteo.com/data/cams_global/static/meta.json"
VARIABLE = "pm2_5"
UNIT = "μg/m³"
COLUMNS = ("site_id", "valid_utc", VARIABLE, "source", "run_start_utc", "available_at_utc")

HISTORY_START = date(2022, 8, 4)
FIRST_RUN = datetime(2026, 4, 2, tzinfo=UTC)
CYCLE = timedelta(hours=12)
STITCHED_LEADS = timedelta(hours=12)
RUN_LENGTH = timedelta(hours=120)
PUBLISH_DELAY = timedelta(hours=10)
MAX_GRID_OFFSET_DEG = 0.4

_HOUR = timedelta(hours=1)
_FIXED_PARAMS = {"timezone": "GMT", "cell_selection": "land"}


def stitched_run_start(valid: datetime) -> datetime:
    """The run the stitched history takes `valid` from: the last 00 or 12 UTC start at or before."""
    at = ensure_utc(valid)
    midnight = datetime.combine(at.date(), time.min, tzinfo=UTC)
    return midnight + ((at - midnight) // CYCLE) * CYCLE


def issued_run_start(target: date) -> datetime:
    """The as-issued run for `target` (D+1): 00 UTC on the issue day (D-052)."""
    return datetime.combine(issue_time_utc(target).date(), time.min, tzinfo=UTC)


@dataclass(frozen=True)
class CamsQuery:
    """One request at one monitor: UTC days `start` to `end` (history, live), or one `run`."""

    source: CamsSource
    site: str
    lat: float
    lon: float
    start: date | None = None
    end: date | None = None
    run: datetime | None = None

    def __post_init__(self) -> None:
        if self.source is not CamsSource.RUN:
            if self.start is None or self.end is None:
                raise ValueError("a history query needs its days")
            if self.end < self.start:
                raise ValueError("end before start")
        else:
            if self.run is None:
                raise ValueError("a run query needs its run")
            if stitched_run_start(self.run) != self.run:
                raise ValueError("the run time is not a CAMS start (00 or 12 UTC)")

    @classmethod
    def history(cls, site: str, start: date, end: date) -> CamsQuery:
        """The stitched history at `site`'s own coordinates, for UTC days `start` to `end`."""
        if start < HISTORY_START:
            raise ValueError(f"{start} is before the CAMS history starts ({HISTORY_START})")
        lat, lon = SITE_COORDS[site]
        return cls(CamsSource.HISTORY, site, lat, lon, start=start, end=end)

    @classmethod
    def live_for(cls, site: str, target: date, tz: ZoneInfo) -> CamsQuery:
        """The live forecast at `site` for the UTC days that hold `target`'s local day."""
        start, end = local_day_window_utc(target, tz)
        lat, lon = SITE_COORDS[site]
        return cls(CamsSource.LIVE, site, lat, lon, start=start.date(), end=(end - _HOUR).date())

    @classmethod
    def run_at(cls, site: str, run: datetime) -> CamsQuery:
        """One CAMS run at `site`'s own coordinates."""
        lat, lon = SITE_COORDS[site]
        return cls(CamsSource.RUN, site, lat, lon, run=ensure_utc(run))

    def _days(self) -> tuple[date, date]:
        if self.start is None or self.end is None:
            raise ValueError("not a history query")
        return self.start, self.end

    def _run(self) -> datetime:
        if self.run is None:
            raise ValueError("not a run query")
        return ensure_utc(self.run)

    def params(self) -> dict[str, str]:
        """The query string."""
        params = {"latitude": repr(self.lat), "longitude": repr(self.lon), "hourly": VARIABLE}
        if self.source is not CamsSource.RUN:
            start, end = self._days()
            params |= {
                "domains": "cams_global",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            }
        else:
            params |= {"models": "cams_global", "run": self._run().strftime("%Y-%m-%dT%H:%M")}
        return params | _FIXED_PARAMS

    def first_hour(self) -> datetime:
        """The first stamp a response holds: the first day's midnight, or the run day's."""
        day = self._days()[0] if self.source is not CamsSource.RUN else self._run().date()
        return datetime.combine(day, time.min, tzinfo=UTC)

    def hours_ok(self, count: int) -> bool:
        """Whether `count` hourly stamps from `first_hour` are what this query must return.

        A history or live answer holds exactly its days; a run holds whole days, through its
        last hour.
        """
        if self.source is not CamsSource.RUN:
            start, end = self._days()
            return count == ((end - start).days + 1) * 24
        last = self._run() + RUN_LENGTH
        return count % 24 == 0 and self.first_hour() + (count - 1) * _HOUR >= last


def _refuse(rule: str, detail: str) -> WeatherResponseError:
    return WeatherResponseError(f"{rule}: {detail}")


def _check(query: CamsQuery, payload: Mapping[str, Any]) -> list[datetime]:
    if payload.get("error"):
        raise _refuse("error_payload", "Open-Meteo refused the request")
    if payload.get("utc_offset_seconds") != 0:
        raise _refuse("not_utc", "the response is not on UTC (GMT) time")
    hourly: Mapping[str, list[Any]] = payload.get("hourly") or {}
    missing = [n for n in ("time", VARIABLE) if n not in hourly]
    if missing:
        raise _refuse("missing_variable", ", ".join(missing))
    if (payload.get("hourly_units") or {}).get(VARIABLE) != UNIT:
        raise _refuse("unit", f"{VARIABLE} is not in the expected unit")
    times = hourly["time"]
    if len(hourly[VARIABLE]) != len(times):
        raise _refuse("column_length", f"{VARIABLE} differs in length from the times")
    stamps = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in times]
    first = query.first_hour()
    if stamps != [first + h * _HOUR for h in range(len(stamps))] or not query.hours_ok(len(stamps)):
        raise _refuse(
            "hours", f"{len(stamps)} hourly stamps not as expected from {first.isoformat()}"
        )
    off = max(
        abs(float(payload["latitude"]) - query.lat), abs(float(payload["longitude"]) - query.lon)
    )
    if off > MAX_GRID_OFFSET_DEG:
        raise _refuse("grid_too_far", f"the grid point is over {MAX_GRID_OFFSET_DEG} degrees away")
    return stamps


def parse(
    query: CamsQuery, payload: Mapping[str, Any], live_run: LiveRun | None = None
) -> pd.DataFrame:
    """One checked response as rows (`COLUMNS`), one per UTC hour it holds."""
    if query.source is CamsSource.LIVE and live_run is None:
        raise ValueError("live rows need the run they came from")
    stamps = _check(query, payload)
    values = [math.nan if v is None else float(v) for v in payload["hourly"][VARIABLE]]
    if live_run is not None and query.source is CamsSource.LIVE:
        runs = [live_run.started_utc] * len(stamps)
    elif query.source is CamsSource.HISTORY:
        runs = [stitched_run_start(s) for s in stamps]
    else:
        run = query._run()
        early = sum(1 for s, v in zip(stamps, values, strict=True) if s < run and not math.isnan(v))
        if early:
            raise _refuse("before_run_start", f"{early} value(s) stamped before the run started")
        runs = [run] * len(stamps)
    if live_run is not None and query.source is CamsSource.LIVE:
        available = [live_run.available_utc] * len(stamps)
    else:
        available = [r + PUBLISH_DELAY for r in runs]
    return pd.DataFrame(
        {
            "site_id": query.site,
            "valid_utc": pd.to_datetime(stamps, utc=True),
            VARIABLE: values,
            "source": query.source.value,
            "run_start_utc": pd.to_datetime(runs, utc=True),
            "available_at_utc": pd.to_datetime(available, utc=True),
        },
        columns=list(COLUMNS),
    )


def fetch(
    client: httpx.Client, query: CamsQuery, *, attempts: int = 4, backoff_s: float = 5.0
) -> pd.DataFrame:
    """Fetch and parse one history or run query (the live forecast goes through `fetch_live`)."""
    if query.source is CamsSource.LIVE:
        raise ValueError("the live forecast needs its run: use fetch_live")
    payload = fetch_json(
        client, URLS[query.source], query.params(), attempts=attempts, backoff_s=backoff_s
    )
    return parse(query, payload)


def fetch_live(
    client: httpx.Client,
    query: CamsQuery,
    *,
    now: Callable[[], datetime],
    attempts: int = 4,
    backoff_s: float = 5.0,
) -> pd.DataFrame:
    """The live forecast, between two reads of the run it came from (refused if it changed)."""
    if query.source is not CamsSource.LIVE:
        raise ValueError("fetch_live takes a LIVE query")

    def run() -> LiveRun:
        return parse_live_run(
            fetch_json(client, META_URL, {}, attempts=attempts, backoff_s=backoff_s)
        )

    before = run()
    payload = fetch_json(
        client, URLS[CamsSource.LIVE], query.params(), attempts=attempts, backoff_s=backoff_s
    )
    fetched = ensure_utc(now())
    if run().started_utc != before.started_utc:
        raise _refuse("run_changed", "a new CAMS run was published during the fetch")
    if before.available_utc > fetched:
        raise _refuse("run_from_the_future", "the run was published after the fetch")
    return parse(query, payload, live_run=before)


def daily_means(rows: pd.DataFrame, days: Iterable[date], tz: ZoneInfo) -> pd.DataFrame:
    """Each site's mean over each local day's 24 hourly stamps, only when all 24 are present.

    The window is the local day's half-open UTC window, the same day as the target (D-005).
    `hours` counts the stamps present; `cams_mean` is NaN when it is under 24.
    """
    out = []
    present = rows.dropna(subset=[VARIABLE])
    for site, group in present.groupby("site_id", sort=True):
        values = group.set_index("valid_utc")[VARIABLE]
        for day in days:
            start, end = local_day_window_utc(day, tz)
            inside = values[(values.index >= start) & (values.index < end)]
            expected = (end - start) // _HOUR
            mean = float(inside.mean()) if len(inside) == expected else math.nan
            out.append({"site_id": site, "day": day, "hours": len(inside), "cams_mean": mean})
    return pd.DataFrame(out, columns=["site_id", "day", "hours", "cams_mean"])
