"""The public file the page reads (#13, T6 minimal; T7 adds history and the page itself).

Only derived values go public (D-012, D-028): per-monitor forecasts rounded for display, the
dates, and the "preliminary" flag (AirNow inputs, D-025). Never raw rows or private records.

Publishing is idempotent and only moves forward:

- the same content is never written twice (a rerun leaves no second version);
- `latest.json` never goes back to an older forecast day (a late manual run can't replace it).
"""

from __future__ import annotations

import json
from typing import Any

from airwatch.forecast.record import Store

__all__ = ["LATEST_KEY", "public_payload", "publish"]

LATEST_KEY = "latest.json"
PUBLIC_VERSION = 1
DISPLAY_DECIMALS = 1


def public_payload(record: dict[str, Any]) -> dict[str, Any]:
    """The public view of one record."""
    return {
        "version": PUBLIC_VERSION,
        "forecast_date": record["forecast_date"],
        "issued_at_utc": record["issued_at_utc"],
        "method": record["method"],
        "preliminary": True,  # built from AirNow's preliminary data (D-025)
        "forecasts": [
            {"site_id": f["site_id"], "pm25_ug_m3": round(f["forecast_ug_m3"], DISPLAY_DECIMALS)}
            for f in record["forecasts"]
        ],
        "no_forecast": [m["site_id"] for m in record["no_forecast"]],
    }


def publish(store: Store, record: dict[str, Any]) -> bool:
    """Write `latest.json` for `record`. True if written; False if unchanged or older."""
    data = (json.dumps(public_payload(record), indent=2, sort_keys=True) + "\n").encode()
    current = store.get(LATEST_KEY)
    if current is not None:
        if current == data:
            return False
        if json.loads(current)["forecast_date"] > record["forecast_date"]:
            return False
    store.put(LATEST_KEY, data)
    return True
