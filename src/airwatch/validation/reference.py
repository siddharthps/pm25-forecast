"""Reference data for validation (#20, T12b; D-054): AQS's monitor records and AirNow's site list.

Only the data-quality report fetches it (`airwatch.validation.report`). The daily run carries no
reference, so the rules that need one (`site_outside_city`, `site_moved`,
`airnow_method_stale`, `outside_active_period`) don't run there. Neither source holds a
measurement: dates, coordinates, codes.
"""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from airwatch.observations.aqs import AQS_BASE, PARAMETER
from airwatch.observations.metadata import fetch_json, fetch_response

__all__ = [
    "AIRNOW_SITES_URL",
    "MAX_SITE_OFFSET_KM",
    "Monitor",
    "Reference",
    "distance_km",
    "fetch_reference",
    "parse_airnow_sites",
    "parse_monitors",
]

AIRNOW_SITES_URL = "https://files.airnowtech.org/airnow/today/Monitoring_Site_Locations_V2.dat"
MAX_SITE_OFFSET_KM = 1.0
EARTH_RADIUS_KM = 6371.0
_FIRST_DAY = "20090101"
_LAST_DAY = "20991231"

Coords = tuple[float, float]


@dataclass(frozen=True)
class Monitor:
    """One AQS monitor record (a site's instrument, by POC), as `monitors/bySite` gives it."""

    site_id: str
    poc: int
    open_date: date
    close_date: date | None
    lat: float
    lon: float
    cbsa_code: str | None
    last_method_code: str | None


@dataclass(frozen=True)
class Reference:
    """AQS's monitors for the listed sites, AirNow's PM2.5 positions, and the city's CBSA."""

    monitors: tuple[Monitor, ...]
    airnow_coords: Mapping[str, tuple[Coords, ...]]
    city_cbsa: str


def distance_km(a: Coords, b: Coords) -> float:
    """Great-circle distance between two (latitude, longitude) points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _date(value: Any) -> date | None:
    return None if value in (None, "") else date.fromisoformat(str(value))


def parse_monitors(rows: Iterable[Mapping[str, Any]]) -> tuple[Monitor, ...]:
    """AQS `monitors/bySite` rows for PM2.5 (88101). Raises ValueError on a missing field."""
    out = []
    for r in rows:
        if str(r.get("parameter_code")) != PARAMETER:
            continue
        for field in ("latitude", "longitude", "open_date", "poc"):
            if r.get(field) in (None, ""):
                raise ValueError(f"an AQS monitor record has no {field}")
        out.append(
            Monitor(
                site_id=f"{r['state_code']}{r['county_code']}{r['site_number']}",
                poc=int(r["poc"]),
                open_date=date.fromisoformat(str(r["open_date"])),
                close_date=_date(r.get("close_date")),
                lat=float(r["latitude"]),
                lon=float(r["longitude"]),
                cbsa_code=None if r.get("cbsa_code") in (None, "") else str(r["cbsa_code"]),
                last_method_code=(
                    None if r.get("last_method_code") in (None, "") else str(r["last_method_code"])
                ),
            )
        )
    return tuple(out)


def parse_airnow_sites(text: str) -> dict[str, tuple[Coords, ...]]:
    """Each AQS site ID's PM2.5 positions in AirNow's `Monitoring_Site_Locations_V2.dat`."""
    coords: defaultdict[str, list[Coords]] = defaultdict(list)
    for r in csv.DictReader(io.StringIO(text), delimiter="|"):
        if r.get("Parameter") == "PM2.5" and r.get("AQSID"):
            point = (float(r["Latitude"]), float(r["Longitude"]))
            if point not in coords[r["AQSID"]]:
                coords[r["AQSID"]].append(point)
    return {site: tuple(points) for site, points in coords.items()}


def fetch_reference(
    client: httpx.Client,
    auth: Mapping[str, str],
    sites: Sequence[str],
    *,
    city_cbsa: str,
    backoff_s: float = 5.0,
) -> Reference:
    """AQS's monitor records for each site, and AirNow's current site list.

    Credentials travel in `auth`; nothing here logs a URL or a parameter.
    """
    monitors: list[Monitor] = []
    for site in sites:
        params = {
            **auth,
            "param": PARAMETER,
            "bdate": _FIRST_DAY,
            "edate": _LAST_DAY,
            "state": site[:2],
            "county": site[2:5],
            "site": site[5:],
        }
        data = fetch_json(client, AQS_BASE + "monitors/bySite", params, backoff_s=backoff_s)
        status = str(data.get("Header", [{}])[0].get("status", ""))
        if status.startswith("No data"):
            continue
        if status != "Success":
            raise RuntimeError(f"AQS monitors: status {status!r} for site {site}")
        monitors.extend(parse_monitors(data.get("Data", [])))
    text = fetch_response(client, AIRNOW_SITES_URL, backoff_s=backoff_s).text
    return Reference(tuple(monitors), parse_airnow_sites(text), city_cbsa)
