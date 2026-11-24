"""Validation checks, T12b (#20; D-054): each new rule catches a planted bad record.

- **wrong entity:** a row from a site that isn't listed -> hard, excluded;
- **dates:** an hour that hasn't ended at run time -> hard, excluded;
- **units:** AirNow rows dropped for a unit other than µg/m³ -> warn;
- **key reuse:** each change of method at one instrument -> counted (info);
- **AirNow ranges:** each AirNow hour is judged against its own site's instrument
  (`AIRNOW_METHOD`); a site with no listed instrument is unverified -> hard.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from airwatch.observations.schema import POC_NOT_GIVEN
from airwatch.observations.sites import AIRNOW_METHOD, TRAINING_SITES, VERIFIED_METHODS
from airwatch.validation.checks import Severity, ValidationResult, Window, run_checks
from tests.unit.validation.helpers import SITE_A, SITE_B, START, concat, frame, varying

PHOENIX = ZoneInfo("America/Phoenix")
DAY = Window(START, START + timedelta(days=1))
LATER = START + timedelta(days=30)
JLG = "040139997"
CASA_GRANDE = "040210001"
UNLISTED = "040139998"


def check(
    df: pd.DataFrame,
    *,
    sites: tuple[str, ...] = (SITE_A,),
    now: datetime = LATER,
    ingest_drops: dict[str, int] | None = None,
) -> ValidationResult:
    return run_checks(df, window=DAY, tz=PHOENIX, sites=sites, now=now, ingest_drops=ingest_drops)


def airnow(values: list[float], site: str = SITE_A) -> pd.DataFrame:
    return frame(values, site=site, method=None, poc=POC_NOT_GIVEN, source="airnow")


def test_a_row_from_an_unlisted_site_is_a_hard_failure_and_excluded() -> None:
    result = check(concat(frame(varying(24)), frame(varying(3), site=UNLISTED)))
    f = result.finding("site_not_listed")
    assert (f.problem_class, f.severity) == ("wrong entity", Severity.HARD)
    assert (f.count, f.excluded) == (3, 3)
    assert f.items == ({"site_id": UNLISTED, "hours": 3},)
    assert set(result.clean["site_id"]) == {SITE_A}
    assert not result.passed


def test_an_unlisted_site_gets_no_coverage_finding() -> None:
    result = check(concat(frame(varying(24)), frame(varying(3), site=UNLISTED)))
    assert result.finding("coverage_gap").count == 0


def test_an_hour_that_has_not_ended_at_run_time_is_a_hard_failure() -> None:
    now = START + timedelta(hours=10, minutes=30)
    result = check(frame(varying(24)), now=now)
    f = result.finding("future_hour")
    assert (f.problem_class, f.severity) == ("dates", Severity.HARD)
    assert (f.count, f.excluded) == (14, 14)
    assert f.items == ({"site_id": SITE_A, "poc": 1, "hours": 14},)
    assert len(result.clean) == 10
    assert not result.passed


def test_an_hour_ending_exactly_at_run_time_is_not_in_the_future() -> None:
    result = check(frame(varying(24)), now=START + timedelta(hours=24))
    assert result.finding("future_hour").count == 0
    assert result.passed


def test_a_naive_run_time_is_refused() -> None:
    with pytest.raises(ValueError, match="time zone"):
        check(frame(varying(24)), now=datetime(2024, 4, 1))  # noqa: DTZ001


def test_airnow_unit_drops_are_their_own_warning() -> None:
    result = check(airnow(varying(24)), ingest_drops={"unit_not_ug_m3": 4, "file_missing": 1})
    f = result.finding("unit_mismatch")
    assert (f.problem_class, f.severity, f.count) == ("units", Severity.WARN, 4)
    assert result.finding("airnow_rows_dropped").items == ({"reason": "file_missing", "rows": 1},)
    assert result.passed


def test_without_drop_counts_there_is_no_unit_rule() -> None:
    with pytest.raises(KeyError):
        check(frame(varying(24))).finding("unit_mismatch")


def test_each_method_change_at_one_instrument_is_counted() -> None:
    first = frame(varying(5), method="181", poc=3)
    second = frame(varying(5), method="182", poc=3, start=START + timedelta(hours=5))
    back = frame(varying(5), method="181", poc=3, start=START + timedelta(hours=10))
    f = check(concat(back, first, second)).finding("method_changed")
    assert (f.problem_class, f.severity) == ("key reuse", Severity.INFO)
    assert f.count == 2
    assert f.items == (
        {
            "site_id": SITE_A,
            "poc": 3,
            "time_utc": "2024-03-01T12:00:00+00:00",
            "from": "181",
            "to": "182",
        },
        {
            "site_id": SITE_A,
            "poc": 3,
            "time_utc": "2024-03-01T17:00:00+00:00",
            "from": "182",
            "to": "181",
        },
    )


def test_method_changes_are_judged_per_instrument() -> None:
    df = concat(frame(varying(5), method="181", poc=1), frame(varying(5), method="182", poc=3))
    assert check(df).finding("method_changed").count == 0


def test_every_training_site_has_a_verified_airnow_instrument() -> None:
    assert set(AIRNOW_METHOD) == set(TRAINING_SITES)
    assert set(AIRNOW_METHOD.values()) <= set(VERIFIED_METHODS)


@pytest.mark.parametrize(
    ("site", "value", "excluded"),
    [
        pytest.param(SITE_A, 5000.0, False, id="TEOM max, inclusive"),
        pytest.param(SITE_A, 5000.1, True, id="over the TEOM max, under the widest"),
        pytest.param(SITE_A, -10.0, False, id="TEOM min"),
        pytest.param(JLG, -0.1, True, id="T640X min is 0"),
        pytest.param(JLG, 9999.0, False, id="T640X up to 10,000"),
        pytest.param(CASA_GRANDE, 975.1, True, id="BAM max is 975"),
        pytest.param(CASA_GRANDE, -10.0, False, id="BAM min"),
    ],
)
def test_airnow_hours_use_their_own_sites_instrument_range(
    site: str, value: float, excluded: bool
) -> None:
    vals = varying(24)
    vals[3] = value
    result = check(airnow(vals, site=site), sites=(site,))
    assert result.finding("outside_valid_range").count == int(excluded)
    assert result.finding("unverified_method").count == 0
    assert len(result.clean) == 24 - int(excluded)


def test_an_airnow_site_with_no_listed_instrument_is_unverified() -> None:
    result = check(airnow(varying(24), site=UNLISTED), sites=(UNLISTED,))
    f = result.finding("unverified_method")
    assert f.count == 24
    assert f.items == (
        {"site_id": UNLISTED, "poc": POC_NOT_GIVEN, "method_code": "none", "hours": 24},
    )
    assert not result.passed


def test_exclusions_never_count_a_row_twice() -> None:
    """An unlisted site's future hour with an unknown method is excluded once, by the first rule."""
    df = concat(frame(varying(24)), frame([2000.0] * 2, site=UNLISTED, method="999"))
    result = check(df, now=START + timedelta(hours=1))
    assert result.finding("site_not_listed").excluded == 2
    assert result.finding("unverified_method").excluded == 0
    assert result.finding("outside_valid_range").excluded == 0
    assert result.finding("future_hour").excluded == 23
    assert sum(f.excluded for f in result.findings) + len(result.clean) == len(df)


def test_a_run_time_far_in_the_future_changes_nothing_on_a_clean_day() -> None:
    result = check(frame(varying(24)), now=datetime(2100, 1, 1, tzinfo=UTC))
    assert result.passed
    assert len(result.clean) == 24
    assert {f.rule for f in result.findings if f.count} == set()


def test_site_b_rows_are_checked_with_site_b_listed() -> None:
    result = check(
        concat(frame(varying(24)), frame(varying(24), site=SITE_B)), sites=(SITE_A, SITE_B)
    )
    assert result.finding("site_not_listed").count == 0
    assert len(result.clean) == 48
