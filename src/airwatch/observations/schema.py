"""The hourly observation schema shared by AQS and AirNow (#10, T5).

One row per instrument-hour. Every timestamp is timezone-aware UTC; every row carries
`available_at_utc`, the earliest moment the value could have been known (SPEC § Code Style).
Validation here is structural only and blocks on any violation. Values are never judged here:
raw data is kept as received, and readings outside a crude range are only counted (D-031). The
data-quality rules, with sourced bounds, come in T12.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

__all__ = [
    "CRUDE_RANGE_UG_M3",
    "HOURLY_COLUMNS",
    "concat_hourly",
    "count_outside_crude_range",
    "empty_hourly",
    "validate_hourly",
]

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

# A crude, *unsourced* range used only to count readings worth a look (D-031). It is not a
# validity rule: real hours exceed it (1,167 at midnight on New Year's 2014 in Phoenix, from
# fireworks). T12 replaces it with sourced bounds and decides how such hours are treated.
CRUDE_RANGE_UG_M3 = (-10.0, 1000.0)


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
    if (df["available_at_utc"] <= df["time_utc"]).any():
        raise ValueError("available_at_utc must be after time_utc")


def empty_hourly() -> pd.DataFrame:
    """A frame with the hourly schema and no rows."""
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in HOURLY_COLUMNS.items()})


def concat_hourly(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    """Stack hourly frames, skipping empty ones (pandas warns on those); never fewer columns."""
    parts = [f for f in frames if len(f)]
    if not parts:
        return empty_hourly()
    return pd.concat(parts, ignore_index=True).astype(HOURLY_COLUMNS)


def count_outside_crude_range(df: pd.DataFrame) -> int:
    """How many readings fall outside CRUDE_RANGE_UG_M3. Counted and reported; never dropped."""
    lo, hi = CRUDE_RANGE_UG_M3
    return int(((df["value_ug_m3"] < lo) | (df["value_ug_m3"] > hi)).sum())
