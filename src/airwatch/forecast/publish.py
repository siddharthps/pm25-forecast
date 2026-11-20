"""The public files the page reads (#13 T6, #14 T7; D-012, D-025, D-028, D-036).

- `latest.json`: the newest forecast day. The city summary is the **highest monitor** (EPA's
  AQI TAD, p. 13); each monitor shows PM2.5 truncated to 1 decimal, its AQI, category and
  standard colour, all from `airwatch.aqi`. Labelled preliminary (AirNow inputs, D-025).
- `history.json`: every recorded day, newest first, rebuilt from the private records on each
  run. The records are the source of truth, so the history can't drift from them.

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

from airwatch.aqi import TAD_SOURCE, aqi_category, pm25_aqi, text_color, truncate_pm25
from airwatch.forecast.record import Store
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

# Shapes that must never reach a public file, whatever field they hide in.
SECRET_PATTERNS = (
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key IDs
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
        "city": _city(record),
        "forecasts": [_monitor(f["site_id"], f["forecast_ug_m3"]) for f in record["forecasts"]],
        "no_forecast": [
            {"site_id": m["site_id"], "site_name": SITE_NAMES[m["site_id"]]}
            for m in record["no_forecast"]
        ],
    }


def _brief(monitor: dict[str, Any]) -> dict[str, Any]:
    return {k: monitor[k] for k in ("site_id", "pm25_ug_m3", "aqi", "category")}


def history_payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Every record, newest first, in brief."""
    days = []
    for record in sorted(records, key=lambda r: r["forecast_date"], reverse=True):
        full = public_payload(record)
        days.append(
            {
                "forecast_date": full["forecast_date"],
                "issued_at_utc": full["issued_at_utc"],
                "city": _brief(full["city"]),
                "forecasts": [_brief(m) for m in full["forecasts"]],
            }
        )
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
    """Rebuild `history.json` from every private record. True if it changed."""
    records = []
    for key in private.list_keys("records/"):
        raw = private.get(key) if key.endswith(RECORD_FILE) else None
        if raw is not None:
            records.append(json.loads(raw))
    payload = history_payload(records)
    check_public(payload, "history")
    data = _encode(payload)
    if public.get(HISTORY_KEY) == data:
        return False
    public.put(HISTORY_KEY, data)
    return True
