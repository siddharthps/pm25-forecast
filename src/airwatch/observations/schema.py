"""The hourly observation schema shared by AQS and AirNow (#10, T5).

One row per instrument-hour. Every timestamp is timezone-aware UTC; every row carries
`available_at_utc`, the earliest moment the value could have been known (SPEC § Code Style).
Validation here is structural only and blocks on any violation. Values are never judged here:
raw data is kept as received, and readings outside a crude range are only counted (D-031). The
data-quality rules, with sourced bounds, are in `airwatch.validation` (D-033).

`poc` names the instrument at a site. AQS gives a one- or two-digit number; AirNow gives none,
so its rows carry `POC_NOT_GIVEN`, which no real instrument can have (D-047).
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

__all__ = [
    "CRUDE_RANGE_UG_M3",
    "HOURLY_COLUMNS",
    "POC_NOT_GIVEN",
    "concat_hourly",
    "count_outside_crude_range",
    "empty_hourly",
    "validate_hourly",
]

HOURLY_COLUMNS: dict[str, str] = {
    "source": "string",
    "site_id": "string",
    "poc": "int16",
    "method_code": "string",
    "time_utc": "datetime64[us, UTC]",
    "value_ug_m3": "float64",
    "qualifier": "string",
    "available_at_utc": "datetime64[us, UTC]",
}

CRUDE_RANGE_UG_M3 = (-10.0, 1000.0)
POC_NOT_GIVEN = -1
AQS_POCS = range(100)


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
    airnow = df["source"] == "airnow"
    if (df.loc[airnow, "poc"] != POC_NOT_GIVEN).any():
        raise ValueError(f"poc: AirNow rows must carry POC_NOT_GIVEN ({POC_NOT_GIVEN})")
    if not df.loc[~airnow, "poc"].between(AQS_POCS.start, AQS_POCS.stop - 1).all():
        raise ValueError("poc: AQS instruments are numbered 0 to 99")


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
