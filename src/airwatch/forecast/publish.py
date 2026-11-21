"""The public files the page reads (#13 T6, #14 T7; D-012, D-025, D-028, D-036).

- `latest.json`: the newest forecast day. The city summary is the **highest monitor** (EPA's
  AQI TAD, p. 13); each monitor shows PM2.5 truncated to 1 decimal, its AQI, category and
  standard colour, all from `airwatch.aqi`. Labelled preliminary (AirNow inputs, D-025).
- `history.json`: every recorded day, newest first, rebuilt from the private records on each
  run. The records are the source of truth, so the history can't drift from them. A scored
  day (T10, D-042) also carries its `score`: each monitor's actual (truncated like the
  forecast, with its AQI) and error (forecast minus actual, from the unrounded values, to 2
  decimals), and the city's MAE and bias.

Only derived values go public, never raw rows or the private records. Before any upload, the
payload must pass a strict JSON schema (`schemas/`, no field outside the list) and a secret
scan; a refusal raises before anything is written.

Publishing is idempotent and only moves forward: the same content is never written twice, and
`latest.json` never goes back to an older forecast day.
"""

from __future__ import annotations

import json
import re
from functools import cache
from importlib import resources
from typing import Any

import jsonschema

from airwatch.aqi import (
    TAD_SOURCE,
    aqi_category,
    aqi_scale,
    pm25_aqi,
    text_color,
    truncate_pm25,
)
from airwatch.forecast.record import SCORE_PREFIX, Store
from airwatch.observations.sites import SITE_NAMES

__all__ = [
    "HISTORY_KEY",
    "LATEST_KEY",
    "PublishRefusedError",
    "check_public",
    "history_payload",
    "public_payload",
    "publish",
    "publish_history",
]

LATEST_KEY = "latest.json"
HISTORY_KEY = "history.json"
PUBLIC_VERSION = 2
RECORD_FILE = "/forecast.json"
SCORE_FILE = "/score.json"

SECRET_PATTERNS = (
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)aws_secret_access_key|secret[_-]?key|api[_-]?key|password|token"),
)


class PublishRefusedError(RuntimeError):
    """A public payload failed its schema or the secret scan; nothing was written."""


def _monitor(site_id: str, forecast_ug_m3: float) -> dict[str, Any]:
    pm25 = truncate_pm25(forecast_ug_m3)
    aqi = pm25_aqi(pm25)
    category = aqi_category(aqi)
    return {
        "site_id": site_id,
        "site_name": SITE_NAMES[site_id],
        "pm25_ug_m3": pm25,
        "aqi": aqi,
        "category": category.name,
        "color": category.hex,
        "text_color": text_color(category),
    }


def _city(record: dict[str, Any]) -> dict[str, Any]:
    """The highest monitor (TAD p. 13); a tie goes to the first site ID."""
    top = min(record["forecasts"], key=lambda f: (-f["forecast_ug_m3"], f["site_id"]))
    return _monitor(top["site_id"], top["forecast_ug_m3"])


def public_payload(record: dict[str, Any]) -> dict[str, Any]:
    """The public view of one record."""
    return {
        "version": PUBLIC_VERSION,
        "forecast_date": record["forecast_date"],
        "issued_at_utc": record["issued_at_utc"],
        "method": record["method"],
        "preliminary": True,
        "aqi_source": TAD_SOURCE,
        "aqi_scale": aqi_scale(),
        "city": _city(record),
        "forecasts": [_monitor(f["site_id"], f["forecast_ug_m3"]) for f in record["forecasts"]],
        "no_forecast": [
            {"site_id": m["site_id"], "site_name": SITE_NAMES[m["site_id"]]}
            for m in record["no_forecast"]
        ],
    }


def _brief(monitor: dict[str, Any]) -> dict[str, Any]:
    return {k: monitor[k] for k in ("site_id", "pm25_ug_m3", "aqi", "category")}


def _round(value: float | None, places: int = 2) -> float | None:
    return None if value is None else round(value, places)


def _public_score(score: dict[str, Any]) -> dict[str, Any]:
    """The public view of one score: actuals as displayed, errors and the city's MAE."""
    monitors = []
    for m in score["monitors"]:
        actual = truncate_pm25(m["actual_ug_m3"])
        aqi = pm25_aqi(actual)
        monitors.append(
            {
                "site_id": m["site_id"],
                "actual_ug_m3": actual,
                "aqi": aqi,
                "category": aqi_category(aqi).name,
                "error_ug_m3": _round(m["error_ug_m3"]),
            }
        )
    return {
        "mae_ug_m3": _round(score["city"]["mae_ug_m3"]),
        "bias_ug_m3": _round(score["city"]["bias_ug_m3"]),
        "n_scored": score["city"]["n_scored"],
        "monitors": monitors,
        "no_actual": [{"site_id": m["site_id"]} for m in score["no_actual"]],
    }


def history_payload(
    records: list[dict[str, Any]], scores: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Every record, newest first, in brief; a scored day with its score."""
    days = []
    for record in sorted(records, key=lambda r: r["forecast_date"], reverse=True):
        full = public_payload(record)
        day: dict[str, Any] = {
            "forecast_date": full["forecast_date"],
            "issued_at_utc": full["issued_at_utc"],
            "city": _brief(full["city"]),
            "forecasts": [_brief(m) for m in full["forecasts"]],
        }
        score = (scores or {}).get(record["forecast_date"])
        if score is not None:
            day["score"] = _public_score(score)
        days.append(day)
    return {
        "version": PUBLIC_VERSION,
        "preliminary": True,
        "aqi_source": TAD_SOURCE,
        "days": days,
    }


@cache
def _schema(name: str) -> dict[str, Any]:
    text = resources.files("airwatch.forecast").joinpath(f"schemas/{name}.schema.json")
    schema: dict[str, Any] = json.loads(text.read_text(encoding="utf-8"))
    return schema


def check_public(payload: dict[str, Any], schema: str) -> None:
    """Raise PublishRefusedError unless `payload` fits its schema and holds nothing secret."""
    try:
        jsonschema.validate(payload, _schema(schema))
    except jsonschema.ValidationError as exc:
        where = "/".join(str(p) for p in exc.absolute_path) or "(top)"
        raise PublishRefusedError(f"{schema} schema: refused at {where}") from None
    text = json.dumps(payload)
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise PublishRefusedError(f"{schema}: secret scan matched a forbidden shape")


def _encode(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def publish(store: Store, record: dict[str, Any]) -> bool:
    """Write `latest.json` for `record`. True if written; False if unchanged or older."""
    payload = public_payload(record)
    check_public(payload, "latest")
    data = _encode(payload)
    current = store.get(LATEST_KEY)
    if current is not None:
        if current == data:
            return False
        if json.loads(current)["forecast_date"] > record["forecast_date"]:
            return False
    store.put(LATEST_KEY, data)
    return True


def publish_history(public: Store, private: Store) -> bool:
    """Rebuild `history.json` from every private record and score. True if it changed."""
    records = []
    for key in private.list_keys("records/"):
        raw = private.get(key) if key.endswith(RECORD_FILE) else None
        if raw is not None:
            records.append(json.loads(raw))
    scores = {}
    for key in private.list_keys(SCORE_PREFIX):
        raw = private.get(key) if key.endswith(SCORE_FILE) else None
        if raw is not None:
            score = json.loads(raw)
            scores[score["forecast_date"]] = score
    payload = history_payload(records, scores)
    check_public(payload, "history")
    data = _encode(payload)
    if public.get(HISTORY_KEY) == data:
        return False
    public.put(HISTORY_KEY, data)
    return True
