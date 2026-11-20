"""Validation checks (#12, T12a): each problem class catches a planted bad record.

Rules under test (D-021, D-031, D-032, D-033):

- **duplicates:** one row per (source, site, POC, hour); any repeat is a hard failure;
- **implausible values:** outside the instrument's AQS valid range -> excluded and counted (warn);
  an unverified method -> hard; negative but in range -> kept, counted for information;
  12+ identical hours in a row at one instrument -> flagged, kept (warn);
- **coverage gaps:** a site-month (local calendar) with < 75% of its hours usable -> warn;
  a training site with no rows at all -> warn;
- **AirNow IDs:** the reader's drop counts are reported for information.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from airwatch.validation.checks import (
    COVERAGE_MIN_SHARE,
    FLATLINE_MIN_HOURS,
    CoverageFrom,
    Severity,
    ValidationFailedError,
    ValidationResult,
    Window,
    run_checks,
)
from tests.unit.validation.helpers import SITE_A, SITE_B, START, concat, frame, varying

PHOENIX = ZoneInfo("America/Phoenix")
DAY = Window(START, START + timedelta(days=1))  # one Phoenix day, 24 hours


def check(
    df: pd.DataFrame,
    *,
    sites: tuple[str, ...] = (SITE_A,),
    window: Window = DAY,
    coverage_from: CoverageFrom = "window",
    ingest_drops: dict[str, int] | None = None,
) -> ValidationResult:
    return run_checks(
        df,
        window=window,
        tz=PHOENIX,
        sites=sites,
        coverage_from=coverage_from,
        ingest_drops=ingest_drops,
    )


# --- the agreed thresholds (D-033) ---------------------------------------------------------


def test_thresholds_are_the_agreed_ones() -> None:
    assert FLATLINE_MIN_HOURS == 12
    assert COVERAGE_MIN_SHARE == 0.75  # the SPEC's 18 of 24 hours, applied per month


def test_a_clean_day_passes_with_every_rule_reported_at_zero() -> None:
    result = check(frame(varying(24)))
    assert result.passed
    assert {f.rule for f in result.findings} == {
        "duplicate_hours",
        "unverified_method",
        "outside_valid_range",
        "negative_in_range",
        "flat_line",
        "coverage_gap",
        "site_missing",
    }
    assert all(f.count == 0 for f in result.findings)
    assert len(result.clean) == 24
    result.raise_if_failed()  # no error


# --- duplicates ----------------------------------------------------------------------------


def test_a_repeated_hour_is_a_hard_failure() -> None:
    df = frame(varying(24))
    result = check(concat(df, df.iloc[[5]]))
    f = result.finding("duplicate_hours")
    assert f.severity is Severity.HARD
    assert f.count == 1
    assert f.items == ({"site_id": SITE_A, "poc": 1, "time_utc": "2024-03-01T12:00:00+00:00"},)
    assert not result.passed


def test_a_repeated_hour_with_a_different_value_is_still_a_duplicate() -> None:
    df = frame(varying(24))
    twin = df.iloc[[5]].assign(value_ug_m3=99.0)
    assert check(concat(df, twin)).finding("duplicate_hours").count == 1


def test_co_located_instruments_at_the_same_hour_are_not_duplicates() -> None:
    df = concat(frame(varying(24), poc=1), frame(varying(24), poc=3))
    assert check(df).finding("duplicate_hours").count == 0


def test_the_same_hour_at_two_sites_is_not_a_duplicate() -> None:
    df = concat(frame(varying(24)), frame(varying(24), site=SITE_B))
    assert check(df, sites=(SITE_A, SITE_B)).finding("duplicate_hours").count == 0


def test_a_hard_failure_raises_naming_the_rule_but_no_values() -> None:
    df = frame(varying(24, base=123.456))
    result = check(concat(df, df.iloc[[0]]))
    with pytest.raises(ValidationFailedError, match="duplicate_hours: 1") as exc:
        result.raise_if_failed()
    assert "123.456" not in str(exc.value)


# --- implausible values --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "value", "excluded"),
    [
        ("170", 975.0, False),  # BAM max, inclusive
        ("170", 975.1, True),
        ("170", -10.0, False),  # BAM min, inclusive
        ("170", -10.1, True),
        ("181", 1167.0, False),  # the 2014 New Year's fireworks hour (TEOM, up to 5,000)
        ("181", 5000.1, True),
        ("638", -0.1, True),  # T640X min is 0
        ("638", 9999.0, False),
    ],
)
def test_values_outside_the_instruments_valid_range_are_excluded(
    method: str, value: float, excluded: bool
) -> None:
    vals = varying(24)
    vals[3] = value
    result = check(frame(vals, method=method))
    f = result.finding("outside_valid_range")
    assert f.severity is Severity.WARN
    assert f.count == int(excluded)
    assert f.excluded == int(excluded)
    assert len(result.clean) == 24 - int(excluded)
    assert result.passed  # one faulty hour never stops the day (D-033)


def test_a_missing_value_is_excluded_as_outside_the_range() -> None:
    vals = varying(24)
    vals[0] = float("nan")
    result = check(frame(vals))
    assert result.finding("outside_valid_range").count == 1
    assert len(result.clean) == 23


def test_an_unverified_method_is_a_hard_failure_and_excluded() -> None:
    result = check(frame(varying(24), method="999"))
    f = result.finding("unverified_method")
    assert f.severity is Severity.HARD
    assert f.count == 24
    assert f.items == ({"site_id": SITE_A, "poc": 1, "method_code": "999", "hours": 24},)
    assert result.clean.empty
    assert not result.passed


def test_airnow_rows_use_the_widest_verified_range() -> None:
    vals = varying(24)
    vals[1], vals[2] = 9000.0, 10_000.1  # no method on AirNow rows: -10 to 10,000 (D-033)
    result = check(frame(vals, method=None, poc=0, source="airnow"))
    assert result.finding("outside_valid_range").count == 1
    assert result.finding("unverified_method").count == 0


def test_negative_readings_inside_the_range_are_kept_and_counted() -> None:
    vals = varying(24)
    vals[4], vals[9] = -3.0, -0.5
    result = check(frame(vals))
    f = result.finding("negative_in_range")
    assert f.severity is Severity.INFO
    assert f.count == 2
    assert f.excluded == 0
    assert len(result.clean) == 24


def test_twelve_identical_hours_in_a_row_are_flagged_but_kept() -> None:
    vals = varying(24)
    vals[6:18] = [4.0] * 12
    result = check(frame(vals))
    f = result.finding("flat_line")
    assert f.severity is Severity.WARN
    assert f.count == 1
    assert f.items == (
        {"site_id": SITE_A, "poc": 1, "start_utc": "2024-03-01T13:00:00+00:00", "hours": 12},
    )
    assert f.excluded == 0
    assert len(result.clean) == 24


def test_eleven_identical_hours_are_not_a_flat_line() -> None:
    vals = varying(24)
    vals[6:17] = [4.0] * 11
    assert check(frame(vals)).finding("flat_line").count == 0


def test_a_gap_in_time_breaks_a_flat_line() -> None:
    first = frame([4.0] * 6)
    second = frame([4.0] * 6, start=START + timedelta(hours=7))  # hour 6 missing
    assert check(concat(first, second)).finding("flat_line").count == 0


def test_flat_lines_are_judged_per_instrument() -> None:
    df = concat(frame([4.0] * 12, poc=1), frame(varying(12), poc=3))
    f = check(df).finding("flat_line")
    assert [item["poc"] for item in f.items] == [1]


# --- coverage gaps -------------------------------------------------------------------------


@pytest.mark.parametrize(("hours", "gap"), [(24, False), (18, False), (17, True)])
def test_a_day_needs_three_quarters_of_its_hours(hours: int, gap: bool) -> None:
    f = check(frame(varying(hours))).finding("coverage_gap")
    assert f.severity is Severity.WARN
    assert f.count == int(gap)
    if gap:
        assert f.items == ({"site_id": SITE_A, "month": "2024-03", "hours": 17, "expected": 24},)


def test_excluded_hours_do_not_count_as_coverage() -> None:
    vals = varying(18)
    vals[0] = 2000.0  # out of range for the BAM: 17 usable hours left
    assert check(frame(vals)).finding("coverage_gap").count == 1


def test_co_located_instruments_count_each_hour_once() -> None:
    df = concat(frame(varying(9), poc=1), frame(varying(9), poc=3))  # 9 distinct hours
    assert check(df).finding("coverage_gap").count == 1


def test_a_site_with_no_rows_is_missing_not_a_gap() -> None:
    result = check(frame(varying(24)), sites=(SITE_A, SITE_B))
    assert result.finding("site_missing").items == ({"site_id": SITE_B},)
    assert result.finding("site_missing").severity is Severity.WARN
    assert result.finding("coverage_gap").count == 0
    assert result.passed


def test_months_are_local_calendar_months() -> None:
    # Local March 2024 in Phoenix is 744 hours, from 03-01 07:00 UTC to 04-01 07:00 UTC.
    march = Window(START, datetime(2024, 4, 1, 7, tzinfo=UTC))
    f = check(frame(varying(744)), window=march).finding("coverage_gap")
    assert f.count == 0


def test_each_month_is_judged_on_its_own() -> None:
    feb_start = datetime(2024, 2, 1, 7, tzinfo=UTC)
    window = Window(feb_start, datetime(2024, 4, 1, 7, tzinfo=UTC))
    feb = frame(varying(29 * 24), start=feb_start)
    march_half = frame(varying(15 * 24))
    f = check(concat(feb, march_half), window=window).finding("coverage_gap")
    assert f.items == ({"site_id": SITE_A, "month": "2024-03", "hours": 360, "expected": 744},)


def test_from_first_reading_ignores_months_before_a_monitor_existed() -> None:
    window = Window(datetime(2023, 1, 1, 7, tzinfo=UTC), datetime(2024, 4, 1, 7, tzinfo=UTC))
    df = frame(varying(744))  # the monitor starts in March 2024
    assert (
        check(df, window=window, coverage_from="first_reading").finding("coverage_gap").count == 0
    )
    assert check(df, window=window, coverage_from="window").finding("coverage_gap").count == 14


def test_from_first_reading_counts_from_that_hour() -> None:
    start = START + timedelta(days=20)  # mid-month start, full after that
    window = Window(START, datetime(2024, 4, 1, 7, tzinfo=UTC))
    df = frame(varying(11 * 24), start=start)
    assert (
        check(df, window=window, coverage_from="first_reading").finding("coverage_gap").count == 0
    )


def test_rows_outside_the_window_are_not_counted_as_coverage() -> None:
    df = frame(varying(24), start=START + timedelta(days=1))  # the next day
    assert check(df).finding("coverage_gap").count == 1


# --- AirNow IDs (from T5) ------------------------------------------------------------------


def test_airnow_drop_counts_are_reported_for_information() -> None:
    df = frame(varying(24), method=None, poc=0, source="airnow")
    result = check(df, ingest_drops={"not_an_aqs_site_id": 5, "unmatched_site": 3})
    assert result.finding("airnow_not_aqs_id").count == 5
    assert result.finding("airnow_unmatched_site").count == 3
    assert result.finding("airnow_unmatched_site").severity is Severity.INFO
    assert result.passed


def test_without_drop_counts_there_are_no_airnow_rules() -> None:
    with pytest.raises(KeyError):
        check(frame(varying(24))).finding("airnow_not_aqs_id")


# --- inputs ---------------------------------------------------------------------------------


def test_a_naive_window_is_refused() -> None:
    with pytest.raises(ValueError, match="time zone"):
        Window(datetime(2024, 3, 1), datetime(2024, 3, 2))  # noqa: DTZ001


def test_an_empty_window_is_refused() -> None:
    with pytest.raises(ValueError, match="before"):
        Window(START, START)


def test_a_frame_that_breaks_the_schema_is_refused() -> None:
    with pytest.raises(ValueError, match="missing columns"):
        check(frame(varying(24)).drop(columns=["poc"]))


def test_an_empty_frame_reports_every_site_missing() -> None:
    result = check(frame([]), sites=(SITE_A, SITE_B))
    assert result.finding("site_missing").count == 2
    assert result.clean.empty


def test_a_monitor_that_starts_after_the_window_is_not_judged() -> None:
    df = frame(varying(24), start=START + timedelta(days=3))
    assert check(df, coverage_from="first_reading").finding("coverage_gap").count == 0


def test_a_window_shorter_than_an_hour_expects_no_hours() -> None:
    short = Window(START, START + timedelta(minutes=30))
    assert check(frame([]), sites=(), window=short).finding("coverage_gap").count == 0
    assert check(frame(varying(1)), window=short).finding("coverage_gap").count == 0


# --- found by planted bugs (tests of the tests) --------------------------------------------


def test_an_excluded_negative_is_not_also_counted_as_in_range() -> None:
    vals = varying(24)
    vals[4] = -50.0  # below the BAM's -10: excluded, so not "negative in range"
    result = check(frame(vals))
    assert result.finding("outside_valid_range").count == 1
    assert result.finding("negative_in_range").count == 0


def test_a_flat_line_never_joins_two_instruments() -> None:
    first = frame([4.0] * 6, poc=1)
    second = frame([4.0] * 6, poc=3, start=START + timedelta(hours=6))  # continues in time
    assert check(concat(first, second)).finding("flat_line").count == 0


def test_readings_before_the_window_never_widen_it() -> None:
    window = Window(START, datetime(2024, 4, 1, 7, tzinfo=UTC))  # local March
    early = frame([5.0], start=datetime(2024, 2, 1, 7, tzinfo=UTC))  # one February hour
    df = concat(early, frame(varying(744)))
    assert (
        check(df, window=window, coverage_from="first_reading").finding("coverage_gap").count == 0
    )


def test_a_site_whose_rows_were_all_excluded_is_a_gap_not_missing() -> None:
    result = check(frame([2000.0] * 24))  # all out of range for the BAM
    assert result.finding("site_missing").count == 0
    assert result.finding("coverage_gap").items == (
        {"site_id": SITE_A, "month": "2024-03", "hours": 0, "expected": 24},
    )


def test_a_first_reading_late_on_the_last_local_day_counts_in_that_month() -> None:
    # 2024-04-01 03:00 UTC is 20:00 on 31 March in Phoenix: March has 4 hours left, 1 present.
    window = Window(START, datetime(2024, 5, 1, 7, tzinfo=UTC))
    late_march = frame([5.0], start=datetime(2024, 4, 1, 3, tzinfo=UTC))
    april = frame(varying(30 * 24), start=datetime(2024, 4, 1, 7, tzinfo=UTC))
    f = check(concat(late_march, april), window=window, coverage_from="first_reading").finding(
        "coverage_gap"
    )
    assert f.items == ({"site_id": SITE_A, "month": "2024-03", "hours": 1, "expected": 4},)
