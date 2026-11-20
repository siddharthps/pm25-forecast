"""The public files (#14, T7): derived values only, AQI per EPA's TAD, checked before upload.

- `latest.json`: the city summary (the highest monitor, TAD p. 13) and every monitor, each with
  PM2.5 truncated to 1 decimal, its AQI, category and standard colour (aqi.py); "preliminary".
- `history.json`: every recorded day, newest first, rebuilt from the private records.
- Before any upload: a strict JSON schema (no field outside the list) and a secret scan.
"""

import json
from datetime import date, timedelta
from typing import Any

import pytest

from airwatch.aqi import aqi_scale
from airwatch.forecast.publish import (
    HISTORY_KEY,
    LATEST_KEY,
    PublishRefusedError,
    check_public,
    history_payload,
    public_payload,
    publish,
    publish_history,
)
from airwatch.forecast.record import encode, record_key
from tests.unit.forecast.fakes import MemoryStore

A, B, C = "040130019", "040131003", "040131004"


def record(day: str = "2026-11-21", **values: float) -> dict[str, Any]:
    vals = values or {"a": 8.4567, "b": 35.97}
    sites = dict(zip("abc", (A, B, C), strict=True))
    return {
        "forecast_date": day,
        "issued_at_utc": f"{_day_before(day)}T12:00:00+00:00",
        "method": "persistence",
        "forecasts": [
            {"site_id": sites[k], "forecast_ug_m3": v, "n_hours": 24} for k, v in vals.items()
        ],
        "no_forecast": [{"site_id": C, "n_hours": 12}] if "c" not in vals else [],
        "inputs": {"rows": 48},
    }


def _day_before(day: str) -> str:
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def test_the_latest_payload() -> None:
    payload = public_payload(record())
    assert payload.pop("aqi_scale") == aqi_scale()
    assert payload == {
        "version": 2,
        "forecast_date": "2026-11-21",
        "issued_at_utc": "2026-11-20T12:00:00+00:00",
        "method": "persistence",
        "preliminary": True,
        "aqi_source": "EPA-403/B-26-003 (May 2026)",
        "city": {
            "site_id": B,
            "site_name": "Mesa - Brooks Reservoir",
            "pm25_ug_m3": 35.9,
            "aqi": 102,
            "category": "Unhealthy for Sensitive Groups",
            "color": "#ff7e00",
            "text_color": "#000000",
        },
        "forecasts": [
            {
                "site_id": A,
                "site_name": "West Phoenix",
                "pm25_ug_m3": 8.4,
                "aqi": 47,
                "category": "Good",
                "color": "#00e400",
                "text_color": "#000000",
            },
            {
                "site_id": B,
                "site_name": "Mesa - Brooks Reservoir",
                "pm25_ug_m3": 35.9,
                "aqi": 102,
                "category": "Unhealthy for Sensitive Groups",
                "color": "#ff7e00",
                "text_color": "#000000",
            },
        ],
        "no_forecast": [{"site_id": C, "site_name": "North Phoenix"}],
    }


def test_the_city_is_the_highest_monitor() -> None:
    city = public_payload(record(a=60.0, b=12.0))["city"]
    assert (city["site_id"], city["aqi"], city["category"]) == (A, 154, "Unhealthy"), (
        "Equation 1: (200 - 151) / (125.4 - 55.5) * (60.0 - 55.5) + 151 = 154.15, so 154"
    )


def test_a_tie_for_highest_picks_the_first_site_id() -> None:
    assert public_payload(record(a=20.0, b=20.0))["city"]["site_id"] == A


def test_the_latest_payload_passes_its_own_schema() -> None:
    check_public(public_payload(record()), "latest")


@pytest.mark.parametrize(
    ("change", "why"),
    [
        (lambda p: p.update(raw_rows=[1, 2]), "an extra field"),
        (lambda p: p["forecasts"][0].update(site_id="40130019"), "a bad site id"),
        (lambda p: p["city"].update(color="red"), "a colour not from the table"),
        (lambda p: p.update(preliminary=False), "dropping the preliminary label"),
        (lambda p: p["forecasts"][0].update(n_hours=24), "a record-only field"),
        (lambda p: p["aqi_scale"][2].update(color="orange"), "a scale colour not from the table"),
        (lambda p: p["aqi_scale"].pop(), "a scale missing a category"),
    ],
)
def test_the_schema_refuses_anything_off_the_list(change: Any, why: str) -> None:
    payload = public_payload(record())
    change(payload)
    with pytest.raises(PublishRefusedError, match="schema"):
        check_public(payload, "latest")
    assert why


@pytest.mark.parametrize(
    "secret",
    [
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "-----BEGIN " + "PRIVATE KEY-----",
        "aws_secret_access_key",
    ],
)
def test_the_secret_scan_refuses_secret_shapes(secret: str) -> None:
    payload = public_payload(record())
    payload["forecasts"][0]["site_name"] = secret
    with pytest.raises(PublishRefusedError, match="secret"):
        check_public(payload, "latest")


def test_publish_refuses_before_writing_anything() -> None:
    bad = record() | {"method": "ensemble"}
    store = MemoryStore()
    with pytest.raises(PublishRefusedError, match="schema"):
        publish(store, bad)
    assert store.objects == {}


def test_history_is_every_record_newest_first() -> None:
    days = [record("2026-11-20", a=5.0, b=6.0), record("2026-11-21"), record("2026-11-19", a=9.0)]
    hist = history_payload(days)
    assert [d["forecast_date"] for d in hist["days"]] == ["2026-11-21", "2026-11-20", "2026-11-19"]
    assert hist["days"][0]["city"]["aqi"] == 102
    assert set(hist["days"][0]["forecasts"][0]) == {"site_id", "pm25_ug_m3", "aqi", "category"}
    check_public(hist, "history")


def test_history_is_rebuilt_from_the_private_records_and_never_rewritten_unchanged() -> None:
    private, public = MemoryStore(), MemoryStore()
    for r in (record("2026-11-20", a=5.0, b=6.0), record("2026-11-21")):
        private.put(record_key(date.fromisoformat(r["forecast_date"])), encode(r))
    private.put("records/notes.txt", b"not a record")
    assert publish_history(public, private) is True
    hist = json.loads(public.objects[HISTORY_KEY])
    assert [d["forecast_date"] for d in hist["days"]] == ["2026-11-21", "2026-11-20"]
    assert publish_history(public, private) is False


def test_latest_is_written_once_per_content() -> None:
    store = MemoryStore()
    assert publish(store, record()) is True
    assert publish(store, record()) is False
    check_public(json.loads(store.objects[LATEST_KEY]), "latest")
