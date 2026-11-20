"""Hand-built hourly frames for the validation tests: clean by default, one planted fault each."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

import pandas as pd

from airwatch.observations.schema import HOURLY_COLUMNS, concat_hourly, validate_hourly

SITE_A = "040130019"
SITE_B = "040131003"
START = datetime(2024, 3, 1, 7, tzinfo=UTC)  # 00:00 in Phoenix (UTC-7, no DST)


def varying(n: int, base: float = 8.0) -> list[float]:
    """n hourly values that never repeat twice in a row (so no flat-line by accident)."""
    return [base + (i % 5) * 0.7 for i in range(n)]


def frame(  # noqa: PLR0913  (each argument is one column of the schema)
    values: Iterable[float],
    *,
    site: str = SITE_A,
    poc: int = 1,
    method: str | None = "170",
    source: str = "aqs",
    start: datetime = START,
    step_h: int = 1,
    available_at: datetime | None = None,
) -> pd.DataFrame:
    vals = list(values)
    times = [start + timedelta(hours=i * step_h) for i in range(len(vals))]
    df = pd.DataFrame(
        {
            "source": source,
            "site_id": site,
            "poc": poc,
            "method_code": method if method is not None else pd.NA,
            "time_utc": pd.to_datetime(times, utc=True),
            "value_ug_m3": vals,
            "qualifier": pd.NA,
            "available_at_utc": pd.Timestamp(available_at or start + timedelta(days=400)),
        },
        columns=list(HOURLY_COLUMNS),
    ).astype(HOURLY_COLUMNS)
    validate_hourly(df)
    return df


def concat(*frames: pd.DataFrame) -> pd.DataFrame:
    return concat_hourly(frames)
