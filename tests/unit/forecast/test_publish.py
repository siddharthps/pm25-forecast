"""The public view of a record (#13, T6): derived, rounded for display, labelled preliminary."""

from airwatch.forecast.publish import public_payload

RECORD = {
    "forecast_date": "2026-11-21",
    "issued_at_utc": "2026-11-20T12:00:00+00:00",
    "method": "persistence",
    "forecasts": [{"site_id": "040130019", "forecast_ug_m3": 8.4567, "n_hours": 24}],
    "no_forecast": [{"site_id": "040131003", "n_hours": 12}],
    "inputs": {"rows": 36},
}


def test_the_public_payload_is_derived_rounded_and_preliminary() -> None:
    assert public_payload(RECORD) == {
        "version": 1,
        "forecast_date": "2026-11-21",
        "issued_at_utc": "2026-11-20T12:00:00+00:00",
        "method": "persistence",
        "preliminary": True,  # AirNow inputs (D-025)
        "forecasts": [{"site_id": "040130019", "pm25_ug_m3": 8.5}],
        "no_forecast": ["040131003"],
    }
