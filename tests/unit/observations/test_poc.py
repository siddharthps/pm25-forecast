"""AirNow rows carry an explicit "not given" POC that no real instrument can have (#57, D-047).

AQS names each instrument at a site by its POC, a one- or two-digit number (0 to 99). AirNow
doesn't give one. `POC_NOT_GIVEN` (-1) sits outside that range, so code that groups, joins or
deduplicates by `(site_id, poc)` can never take it for a real instrument.
"""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from airwatch.observations.airnow import parse_hourly_aqobs
from airwatch.observations.schema import POC_NOT_GIVEN, validate_hourly
from tests.unit.validation.helpers import frame

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "airnow" / "HourlyAQObs_2026111901.dat"
PUBLISHED = datetime(2026, 11, 19, 4, 21, 33, tzinfo=UTC)


def test_the_marker_is_outside_every_real_poc() -> None:
    assert POC_NOT_GIVEN not in range(100)


def test_airnow_rows_carry_the_not_given_marker() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    df, _ = parse_hourly_aqobs(text, PUBLISHED)
    assert len(df) > 0
    assert (df["poc"] == POC_NOT_GIVEN).all()


@pytest.mark.parametrize(
    ("source", "poc"),
    [
        pytest.param("airnow", 0, id="AirNow claiming instrument 0"),
        pytest.param("airnow", 3, id="AirNow claiming a real instrument"),
        pytest.param("aqs", POC_NOT_GIVEN, id="AQS without an instrument"),
        pytest.param("aqs", 100, id="AQS past two digits"),
    ],
)
def test_the_schema_refuses_a_poc_off_its_source(source: str, poc: int) -> None:
    airnow = source == "airnow"
    df = frame(
        [5.0], poc=POC_NOT_GIVEN if airnow else 1, source=source, method=None if airnow else "170"
    )
    df = df.assign(poc=pd.Series([poc], dtype="int16"))
    with pytest.raises(ValueError, match="poc"):
        validate_hourly(df)


@pytest.mark.parametrize("poc", [0, 3, 99])
def test_the_schema_accepts_any_real_aqs_poc(poc: int) -> None:
    validate_hourly(frame([5.0], poc=poc))
