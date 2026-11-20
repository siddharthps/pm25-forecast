"""City data check (T4, #9): fetch metadata and coverage, score with the frozen D-006 rules.

    uv run python scripts/city_check.py            # fetch what's missing, score, print the table

Raw responses are cached under data/raw/city_check/ (gitignored), so a rerun scores the same
inputs without refetching. 2025 rows are stripped of PM values *before* they are cached (D-008).
All the rules live in airwatch.observations.metadata and are unit-tested there; this script only
does I/O. It never prints credentials or request URLs.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from airwatch.config import get_settings
from airwatch.observations.metadata import (
    HISTORY_YEARS,
    TEST_YEAR,
    CityScore,
    choose_city,
    fetch_json,
    parse_airnow_active_pm25,
    score_city,
    strip_values,
)

log = logging.getLogger("city_check")

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "raw" / "city_check"
AQS = "https://aqs.epa.gov/data/api/"
AIRNOW_SITES = "https://files.airnowtech.org/airnow/today/Monitoring_Site_Locations_V2.dat"
OPEN_METEO = {
    "weather": ("https://archive-api.open-meteo.com/v1/archive", "temperature_2m"),
    "cams": ("https://air-quality-api.open-meteo.com/v1/air-quality", "pm2_5"),
}
CANDIDATES = {
    "Chicago": "16980",
    "Salt Lake City": "41620",
    "Los Angeles": "31080",
    "Phoenix": "38060",
}
FALLBACK_CODES = {"Los Angeles": "31100"}
AQS_PAUSE_S = 6.0


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


class Aqs:
    """AQS client: credentials from settings, polite pacing, cached responses."""

    def __init__(self, client: httpx.Client) -> None:
        self._auth = get_settings().aqs_credentials()
        self._client = client
        self._last = 0.0

    def get(self, service: str, **params: str) -> list[dict[str, Any]]:
        wait = AQS_PAUSE_S - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        data = fetch_json(self._client, AQS + service, {**self._auth, **params})
        self._last = time.monotonic()
        header = data.get("Header", [{}])[0]
        status = str(header.get("status", ""))
        if status.startswith("No data"):
            return []
        if status != "Success":
            raise RuntimeError(f"AQS {service}: status {status!r}")
        rows: list[dict[str, Any]] = data.get("Data", [])
        return rows


def resolve_cbsas(aqs: Aqs) -> dict[str, tuple[str, str]]:
    path = CACHE / "aqs" / "cbsas.json"
    if not path.exists():
        _write_json(path, aqs.get("list/cbsas"))
    rows = json.loads(path.read_text(encoding="utf-8"))
    names = {r["code"]: r["value_represented"] for r in rows}
    out: dict[str, tuple[str, str]] = {}
    for city, code in CANDIDATES.items():
        name = names.get(code, "")
        if not name.startswith((f"{city}-", f"{city},")):
            raise RuntimeError(f"{city}: AQS names CBSA {code} {name!r}; check D-006")
        out[city] = (code, name)
    return out


def daily_rows(aqs: Aqs, cbsa: str, year: int) -> list[dict[str, Any]]:
    path = CACHE / "aqs" / cbsa / f"{year}.json"
    if not path.exists():
        log.info("fetching AQS daily data: CBSA %s, %d", cbsa, year)
        rows = aqs.get(
            "dailyData/byCBSA", param="88101", bdate=f"{year}0101", edate=f"{year}1231", cbsa=cbsa
        )
        _write_json(path, strip_values(rows) if year == TEST_YEAR else rows)
    rows_out: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return rows_out


def airnow_active(client: httpx.Client) -> tuple[set[str], str]:
    today = datetime.now(UTC).date().isoformat()
    path = CACHE / "airnow" / f"Monitoring_Site_Locations_V2_{today}.dat"
    if not path.exists():
        response = client.get(AIRNOW_SITES)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    return parse_airnow_active_pm25(path.read_text(encoding="utf-8", errors="replace")), today


def weather_ok(client: httpx.Client, rows: list[dict[str, Any]]) -> bool:
    """One request to each Open-Meteo service at the centre of the CBSA's PM2.5 monitors."""
    coords = {(float(r["latitude"]), float(r["longitude"])) for r in rows}
    lat = sum(c[0] for c in coords) / len(coords)
    lon = sum(c[1] for c in coords) / len(coords)
    for url, var in OPEN_METEO.values():
        params = {
            "latitude": f"{lat:.3f}",
            "longitude": f"{lon:.3f}",
            "hourly": var,
            "start_date": "2024-01-01",
            "end_date": "2024-01-01",
        }
        values = fetch_json(client, url, params).get("hourly", {}).get(var, [])
        if not any(v is not None for v in values):
            return False
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    started = datetime.now(UTC)
    with httpx.Client(timeout=httpx.Timeout(180.0, connect=20.0)) as client:
        aqs = Aqs(client)
        cbsas = resolve_cbsas(aqs)
        active, airnow_date = airnow_active(client)
        scores: list[CityScore] = []
        fallbacks: dict[str, list[int]] = {}
        for city, (code, name) in cbsas.items():

            def year_rows(year: int, city: str = city, code: str = code) -> list[dict[str, Any]]:
                rows = daily_rows(aqs, code, year)
                if not rows and city in FALLBACK_CODES:
                    rows = daily_rows(aqs, FALLBACK_CODES[city], year)
                    fallbacks.setdefault(city, []).append(year)
                return rows

            hist = [r for y in HISTORY_YEARS for r in year_rows(y)]
            test = year_rows(TEST_YEAR)
            scores.append(
                score_city(
                    city,
                    history_rows=hist,
                    test_rows=test,
                    airnow_active=active,
                    weather_ok=weather_ok(client, hist),
                )
            )
            log.info("scored %s (CBSA %s, %s)", city, code, name)

    chosen = choose_city(scores)
    result = {
        "run_started_utc": started.isoformat(),
        "airnow_site_list_date_utc": airnow_date,
        "cbsas": {c: {"code": code, "name": n} for c, (code, n) in cbsas.items()},
        "fallback_years": fallbacks,
        "scores": [asdict(s) for s in scores],
        "chosen": chosen,
    }
    _write_json(ROOT / "data" / "city_check" / "result.json", result)

    out = sys.stdout
    out.write(
        "\n| City | CBSA | Qualifying monitors | Bad-air share | Good 2025 | Weather | Passes |\n"
    )
    out.write("| --- | --- | --- | --- | --- | --- | --- |\n")
    for s in scores:
        code = cbsas[s.name][0]
        out.write(
            f"| {s.name} | {code} | {len(s.qualifying)} | {s.bad_air_share:.2%} | "
            f"{s.test_year_monitors} | {'yes' if s.weather_ok else 'no'} | "
            f"{'yes' if s.passes else 'no: ' + '; '.join(s.reasons)} |\n"
        )
    out.write(f"\nChosen: {chosen or 'none (stop and ask the owner, D-006)'}\n")
    return 0 if chosen else 2


if __name__ == "__main__":
    sys.exit(main())
