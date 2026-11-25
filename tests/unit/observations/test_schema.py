"""The hourly schema's refusals (#99): every source's rows pass `validate_hourly` before use.

`available_at_utc` after `time_utc` is the row-level half of the leakage rule (D-019): a reading
can't be known before the hour it measures, so a row that says otherwise is refused, not fixed.
"""

from collections.abc import Callable

import pandas as pd
import pytest

from airwatch.observations.schema import concat_hourly, validate_hourly
from tests.unit.validation.helpers import frame


def _sites(*ids: str) -> pd.Series:
    return pd.Series(ids, dtype="string")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        pytest.param(lambda df: df.assign(note="x"), "unexpected columns", id="an extra column"),
        pytest.param(
            lambda df: df.astype({"poc": "int64"}), "poc: dtype int64", id="a wider poc dtype"
        ),
        pytest.param(
            lambda df: df.assign(site_id=_sites("04013001", "04013001")),
            "site_id must be 9 digits",
            id="an 8-digit site id",
        ),
        pytest.param(
            lambda df: df.assign(site_id=_sites("04013001X", "04013001X")),
            "site_id must be 9 digits",
            id="a letter in the site id",
        ),
        pytest.param(
            lambda df: df.assign(available_at_utc=df["time_utc"]),
            "available_at_utc must be after time_utc",
            id="available at the measured hour itself",
        ),
        pytest.param(
            lambda df: df.assign(available_at_utc=df["time_utc"] - pd.Timedelta(hours=1)),
            "available_at_utc must be after time_utc",
            id="available before the measured hour",
        ),
    ],
)
def test_a_row_off_the_schema_is_refused(
    change: Callable[[pd.DataFrame], pd.DataFrame], message: str
) -> None:
    good = frame([5.0, 6.0])
    validate_hourly(good)
    with pytest.raises(ValueError, match=message):
        validate_hourly(change(good))


def test_stacked_frames_get_a_fresh_index() -> None:
    """Killed mutmut survivors (#112): index-based masks must never meet a repeated label."""
    stacked = concat_hourly([frame([1.0, 2.0]), frame([3.0])])
    assert list(stacked.index) == [0, 1, 2]
