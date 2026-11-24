"""Open-Meteo weather (#19, T14; D-051): ERA5 for training, the GFS archive and live GFS.

Three sources, the same 8 hourly variables at each monitor's coordinates:

- `ERA5`: the Historical Weather API with `models=era5`, the training weather. Rows are
  `available_at_utc` when fetched: they are never used as of an issue time.
- `GFS_ARCHIVE`: the Previous Runs API with `models=gfs_global` at `_previous_day3` (the lead
  rule, `airwatch.weather.leads`). Each row carries the run it came from and is available at that
  run's start plus the assumed worst-case delay, which the lead rule's property test checks
  against the issue time.
- `GFS_LIVE`: the Forecast API with `models=gfs_global`. The run is read from the metadata of
  `ncep_gfs013`, the model behind `gfs_global`, before and after the data; a run that changed in
  between is refused, so every row names the run it really came from.

Units are requested explicitly, so a change to Open-Meteo's defaults can't change our numbers
silently. Every response is checked before it becomes rows, and a refusal is a
`WeatherResponseError` whose message holds rule names, counts and dates, never a response value.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Any

import httpx
import pandas as pd

from airwatch.errors import ReportableError
from airwatch.observations.metadata import fetch_json
from airwatch.observations.sites import SITE_COORDS
from airwatch.timeutil import ensure_utc
from airwatch.weather.leads import ARCHIVE_SUFFIX, MAX_PUBLISH_DELAY, archived_run_start

__all__ = [
    "COLUMNS",
    "GFS_META_URL",
    "MAX_GRID_OFFSET_DEG",
    "UNITS",
    "URLS",
    "VARIABLES",
    "LiveRun",
    "Query",
    "Source",
    "WeatherResponseError",
    "fetch_hourly",
    "fetch_live",
    "parse_hourly",
    "parse_live_run",
]


class Source(StrEnum):
    ERA5 = "era5"
    GFS_ARCHIVE = "gfs_archive"
    GFS_LIVE = "gfs_live"


UNITS = {
    "temperature_2m": "°C",
    "relative_humidity_2m": "%",
    "wind_speed_10m": "km/h",
    "wind_direction_10m": "°",
    "precipitation": "mm",
    "surface_pressure": "hPa",
    "cloud_cover": "%",
    "shortwave_radiation": "W/m²",
}
VARIABLES = tuple(UNITS)
COLUMNS = ("site_id", "valid_utc", *VARIABLES, "source", "run_start_utc", "available_at_utc")

URLS = {
    Source.ERA5: "https://archive-api.open-meteo.com/v1/archive",
    Source.GFS_ARCHIVE: "https://previous-runs-api.open-meteo.com/v1/forecast",
    Source.GFS_LIVE: "https://api.open-meteo.com/v1/forecast",
}
GFS_META_URL = "https://api.open-meteo.com/data/ncep_gfs013/static/meta.json"
_MODELS = {Source.ERA5: "era5", Source.GFS_ARCHIVE: "gfs_global", Source.GFS_LIVE: "gfs_global"}
_FIXED_PARAMS = {
    "timezone": "GMT",
    "temperature_unit": "celsius",
    "wind_speed_unit": "kmh",
    "precipitation_unit": "mm",
    "cell_selection": "land",
}
MAX_GRID_OFFSET_DEG = 0.25
_HOUR = timedelta(hours=1)


class WeatherResponseError(ReportableError):
    """An Open-Meteo response refused by a named rule (the message starts with the rule)."""


@dataclass(frozen=True)
class LiveRun:
    """The GFS run the live forecast came from: when it started and when it was published."""

    started_utc: datetime
    available_utc: datetime


@dataclass(frozen=True)
class Query:
    """One request: a source, one monitor at its coordinates, and UTC days `start` to `end`."""

    source: Source
    site: str
    lat: float
    lon: float
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("end before start")

    @classmethod
    def for_site(cls, source: Source, site: str, start: date, end: date) -> Query:
        """A query at `site`'s own coordinates (`airwatch.observations.sites.SITE_COORDS`)."""
        lat, lon = SITE_COORDS[site]
        return cls(source, site, lat, lon, start, end)

    @property
    def suffix(self) -> str:
        return ARCHIVE_SUFFIX if self.source is Source.GFS_ARCHIVE else ""

    def params(self) -> dict[str, str]:
        """The query string, with every unit spelled out."""
        return {
            "latitude": repr(self.lat),
            "longitude": repr(self.lon),
            "hourly": ",".join(v + self.suffix for v in VARIABLES),
            "models": _MODELS[self.source],
            "start_date": self.start.isoformat(),
            "end_date": self.end.isoformat(),
            **_FIXED_PARAMS,
        }

    def hours(self) -> list[datetime]:
        """Every UTC hour the response must hold, in order."""
        first = datetime.combine(self.start, time.min, tzinfo=UTC)
        count = ((self.end - self.start).days + 1) * 24
        return [first + h * _HOUR for h in range(count)]


def _refuse(rule: str, detail: str) -> WeatherResponseError:
    return WeatherResponseError(f"{rule}: {detail}")


def _check(query: Query, payload: Mapping[str, Any]) -> list[datetime]:
    if payload.get("error"):
        raise _refuse("error_payload", "Open-Meteo refused the request")
    if payload.get("utc_offset_seconds") != 0:
        raise _refuse("not_utc", "the response is not on UTC (GMT) time")
    hourly: Mapping[str, list[Any]] = payload.get("hourly") or {}
    units: Mapping[str, str] = payload.get("hourly_units") or {}
    names = ["time", *(v + query.suffix for v in VARIABLES)]
    missing = [n for n in names if n not in hourly]
    if missing:
        raise _refuse("missing_variable", ", ".join(missing))
    wrong = [v for v in VARIABLES if units.get(v + query.suffix) != UNITS[v]]
    if wrong:
        raise _refuse("unit", f"{len(wrong)} not in the expected unit: {', '.join(wrong)}")
    times = hourly["time"]
    short = [n for n in names if len(hourly[n]) != len(times)]
    if short:
        raise _refuse("column_length", f"{len(short)} column(s) differ in length from the times")
    stamps = [datetime.fromisoformat(t).replace(tzinfo=UTC) for t in times]
    expected = query.hours()
    if stamps != expected:
        raise _refuse(
            "hours",
            f"{len(stamps)} hourly stamps, expected {len(expected)} from {query.start} to "
            f"{query.end}",
        )
    off_lat = abs(float(payload["latitude"]) - query.lat)
    off_lon = abs(float(payload["longitude"]) - query.lon)
    if max(off_lat, off_lon) > MAX_GRID_OFFSET_DEG:
        raise _refuse("grid_too_far", f"the grid point is over {MAX_GRID_OFFSET_DEG} degrees away")
    return stamps


def _floats(values: list[Any]) -> list[float]:
    return [math.nan if v is None else float(v) for v in values]


def _runs(
    query: Query, stamps: list[datetime], fetched: datetime, live_run: LiveRun | None
) -> tuple[list[datetime | None], list[datetime]]:
    if query.source is Source.GFS_ARCHIVE:
        runs = [archived_run_start(s) for s in stamps]
        return list(runs), [r + MAX_PUBLISH_DELAY for r in runs]
    if query.source is Source.GFS_LIVE:
        if live_run is None:
            raise ValueError("live rows need the run they came from")
        return [live_run.started_utc] * len(stamps), [live_run.available_utc] * len(stamps)
    return [None] * len(stamps), [fetched] * len(stamps)


def parse_hourly(
    query: Query,
    payload: Mapping[str, Any],
    *,
    fetched_utc: datetime,
    live_run: LiveRun | None = None,
) -> pd.DataFrame:
    """One checked response as rows (`COLUMNS`), one per UTC hour of the query."""
    fetched = ensure_utc(fetched_utc)
    if live_run is not None and live_run.available_utc > fetched:
        raise _refuse("run_from_the_future", "the run was published after the fetch")
    stamps = _check(query, payload)
    runs, available = _runs(query, stamps, fetched, live_run)
    hourly = payload["hourly"]
    return pd.DataFrame(
        {
            "site_id": query.site,
            "valid_utc": pd.to_datetime(stamps, utc=True),
            **{v: _floats(hourly[v + query.suffix]) for v in VARIABLES},
            "source": query.source.value,
            "run_start_utc": pd.to_datetime(pd.Series(runs, dtype=object), utc=True),
            "available_at_utc": pd.to_datetime(available, utc=True),
        },
        columns=list(COLUMNS),
    )


def parse_live_run(meta: Mapping[str, Any]) -> LiveRun:
    """The latest run in an Open-Meteo model's `meta.json`."""
    try:
        started = int(meta["last_run_initialisation_time"])
        available = int(meta["last_run_availability_time"])
    except (KeyError, TypeError, ValueError):
        raise _refuse("missing_run_time", "the metadata has no usable run times") from None
    return LiveRun(
        started_utc=datetime.fromtimestamp(started, UTC),
        available_utc=datetime.fromtimestamp(available, UTC),
    )


def fetch_hourly(
    client: httpx.Client,
    query: Query,
    *,
    now: Callable[[], datetime],
    attempts: int = 4,
    backoff_s: float = 5.0,
) -> pd.DataFrame:
    """Fetch and parse ERA5 or the GFS archive (the live forecast goes through `fetch_live`)."""
    if query.source is Source.GFS_LIVE:
        raise ValueError("the live forecast needs its run: use fetch_live")
    payload = fetch_json(
        client, URLS[query.source], query.params(), attempts=attempts, backoff_s=backoff_s
    )
    return parse_hourly(query, payload, fetched_utc=now())


def fetch_live(
    client: httpx.Client,
    query: Query,
    *,
    now: Callable[[], datetime],
    attempts: int = 4,
    backoff_s: float = 5.0,
) -> pd.DataFrame:
    """Fetch the live GFS forecast, between two reads of the run it came from."""
    if query.source is not Source.GFS_LIVE:
        raise ValueError("fetch_live takes a GFS_LIVE query")

    def run() -> LiveRun:
        return parse_live_run(
            fetch_json(client, GFS_META_URL, {}, attempts=attempts, backoff_s=backoff_s)
        )

    before = run()
    payload = fetch_json(
        client, URLS[Source.GFS_LIVE], query.params(), attempts=attempts, backoff_s=backoff_s
    )
    fetched = now()
    if run().started_utc != before.started_utc:
        raise _refuse("run_changed", "a new GFS run was published during the fetch")
    return parse_hourly(query, payload, fetched_utc=fetched, live_run=before)
