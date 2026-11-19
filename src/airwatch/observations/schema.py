"""The hourly observation schema shared by AQS and AirNow (#10, T5).

One row per instrument-hour. Every timestamp is timezone-aware UTC; every row carries
`available_at_utc`, the earliest moment the value could have been known (SPEC § Code Style).
The skeleton's validation is crude on purpose (schema and a plausible range); the full
data-quality checks come in T12.
"""

from __future__ import annotations

import pandas as pd

__all__ = ["HOURLY_COLUMNS", "PLAUSIBLE_UG_M3", "validate_hourly"]

# column -> pandas dtype (as a string, compared with str(dtype))
HOURLY_COLUMNS: dict[str, str] = {
    "source": "string",  # "aqs" or "airnow"
    "site_id": "string",  # 9-digit AQS site ID (state + county + site)
    "poc": "int16",  # instrument number at the site (AirNow: 0 when not given)
    "method_code": "string",
    "time_utc": "datetime64[us, UTC]",  # start of the hour
    "value_ug_m3": "float64",
    "qualifier": "string",
    "available_at_utc": "datetime64[us, UTC]",
}

# Crude skeleton bounds. Continuous monitors can read slightly below zero; the highest hourly
# PM2.5 values in US wildfire smoke are in the hundreds. Outside this, a row is an error.
PLAUSIBLE_UG_M3 = (-10.0, 1000.0)


def validate_hourly(df: pd.DataFrame) -> None:
    """Raise ValueError unless `df` matches the hourly schema exactly."""
    missing = [c for c in HOURLY_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    extra = [c for c in df.columns if c not in HOURLY_COLUMNS]
    if extra:
        raise ValueError(f"unexpected columns: {extra}")
    for col, dtype in HOURLY_COLUMNS.items():
        if str(df[col].dtype) != dtype:
            raise ValueError(f"{col}: dtype {df[col].dtype}, expected {dtype}")
    if not df["site_id"].str.fullmatch(r"\d{9}").all():
        raise ValueError("site_id must be 9 digits")
    lo, hi = PLAUSIBLE_UG_M3
    bad = df[(df["value_ug_m3"] < lo) | (df["value_ug_m3"] > hi)]
    if len(bad):
        raise ValueError(f"{len(bad)} value(s) outside the plausible range {PLAUSIBLE_UG_M3}")
    if (df["available_at_utc"] <= df["time_utc"]).any():
        raise ValueError("available_at_utc must be after time_utc")
