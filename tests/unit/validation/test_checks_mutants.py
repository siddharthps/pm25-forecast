"""Gaps mutmut found in the validation checks (#112): each test kills surviving mutants.

- Every rule reports its documented class and severity, at zero too.
- Boundaries: exactly 12 identical hours; readings of exactly 0; a one-hour window; a monitor
  closing today; a site exactly 1.0 km off; an offset rounded to two places.
- Comparisons run within one source, site and instrument, and every site is judged.
- The city's zone, never the process zone, names months and "today" (POSIX only: WSL, CI).
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from airwatch.observations.schema import POC_NOT_GIVEN
from airwatch.observations.sites import SITE_COORDS
from airwatch.validation import checks as ch
from airwatch.validation.checks import Severity, ValidationResult, Window, run_checks
from airwatch.validation.reference import MAX_SITE_OFFSET_KM, Monitor, Reference
from tests.process_zone import CAN_MOVE_ZONE, SKIP_REASON, process_zone
from tests.unit.validation.helpers import SITE_A, SITE_B, START, concat, frame, varying

PHOENIX = ZoneInfo("America/Phoenix")
DAY = Window(START, START + timedelta(days=1))
NOW = datetime(2030, 1, 1, tzinfo=UTC)
CBSA = "38060"
zone_moves = pytest.mark.skipif(not CAN_MOVE_ZONE, reason=SKIP_REASON)


def check(  # noqa: PLR0913  (each argument is one part of the run context)
    df: pd.DataFrame,
    *,
    sites: tuple[str, ...] = (SITE_A,),
    window: Window = DAY,
    now: datetime = NOW,
    reference: Reference | None = None,
    drops: dict[str, int] | None = None,
    coverage_from: ch.CoverageFrom = "window",
) -> ValidationResult:
    return run_checks(
        df,
        window=window,
        tz=PHOENIX,
        sites=sites,
        now=now,
        reference=reference,
        ingest_drops=drops,
        coverage_from=coverage_from,
    )


def monitor(site: str = SITE_A, poc: int = 1, **kw: Any) -> Monitor:
    lat, lon = kw.pop("coords", SITE_COORDS[site])
    return Monitor(
        site,
        poc,
        kw.pop("opened", date(2010, 1, 1)),
        kw.pop("closed", None),
        lat,
        lon,
        kw.pop("cbsa", CBSA),
        kw.pop("method", "182"),
    )


def ref(*monitors: Monitor, airnow: dict[str, Any] | None = None) -> Reference:
    coords = (
        airnow if airnow is not None else {m.site_id: (SITE_COORDS[m.site_id],) for m in monitors}
    )
    return Reference(tuple(monitors), coords, CBSA)


EXPECTED = {
    "site_not_listed": ("wrong entity", Severity.HARD),
    "future_hour": ("dates", Severity.HARD),
    "duplicate_hours": ("duplicates", Severity.HARD),
    "unverified_method": ("implausible values", Severity.HARD),
    "outside_valid_range": ("implausible values", Severity.WARN),
    "negative_in_range": ("implausible values", Severity.INFO),
    "flat_line": ("implausible values", Severity.WARN),
    "method_changed": ("key reuse", Severity.INFO),
    "coverage_gap": ("coverage gaps", Severity.WARN),
    "site_missing": ("coverage gaps", Severity.WARN),
    "site_outside_city": ("wrong entity", Severity.HARD),
    "site_moved": ("key reuse", Severity.WARN),
    "airnow_method_stale": ("key reuse", Severity.WARN),
    "outside_active_period": ("dates", Severity.WARN),
    "airnow_not_aqs_id": ("AirNow IDs", Severity.INFO),
    "airnow_unmatched_site": ("AirNow IDs", Severity.INFO),
    "airnow_rows_dropped": ("AirNow IDs", Severity.INFO),
    "unit_mismatch": ("units", Severity.WARN),
}


@pytest.mark.parametrize("faulty", [False, True], ids=["clean", "every rule firing"])
def test_every_rule_reports_its_class_and_severity(faulty: bool) -> None:
    df = frame(varying(24), method="182")
    if faulty:
        bad = frame([4.0] * 12, method="999", poc=2)
        df = concat(df, df.iloc[[0]], bad, frame([1.0], site="040139998"))
    result = check(df, reference=ref(monitor()), drops={"unit_not_ug_m3": 1})
    got = {f.rule: (f.problem_class, f.severity) for f in result.findings}
    assert got == EXPECTED
    with pytest.raises(KeyError, match="no_such_rule"):
        result.finding("no_such_rule")


def test_a_short_frame_reports_no_flat_line() -> None:
    f = check(frame([4.0] * 3)).finding("flat_line")
    assert (f.problem_class, f.severity, f.count, f.items) == (
        "implausible values",
        Severity.WARN,
        0,
        (),
    )


def test_exactly_twelve_identical_hours_alone_are_a_flat_line() -> None:
    assert check(frame([4.0] * 12)).finding("flat_line").count == 1


def test_flat_lines_are_found_at_every_site_instrument_and_source() -> None:
    df = concat(
        frame([4.0] * 12, site=SITE_A, poc=1),
        frame([4.0] * 12, site=SITE_A, poc=3),
        frame([4.0] * 12, site=SITE_B, poc=1),
        frame([4.0] * 12, site=SITE_A, method=None, poc=POC_NOT_GIVEN, source="airnow"),
    )
    assert check(df, sites=(SITE_A, SITE_B)).finding("flat_line").count == 4


@pytest.mark.parametrize(("value", "counted"), [(0.0, False), (0.5, False), (-0.1, True)])
def test_only_readings_below_zero_count_as_negative(value: float, counted: bool) -> None:
    vals = varying(24)
    vals[3] = value
    assert check(frame(vals)).finding("negative_in_range").count == int(counted)


def test_an_aqs_row_without_a_method_is_unverified_even_at_a_listed_site() -> None:
    result = check(frame(varying(24), method=None))
    assert result.finding("unverified_method").count == 24


def test_a_duplicate_with_another_value_is_listed() -> None:
    df = frame(varying(24))
    f = check(concat(df, df.iloc[[5]].assign(value_ug_m3=99.0))).finding("duplicate_hours")
    assert f.items == ({"site_id": SITE_A, "poc": 1, "time_utc": "2024-03-01T12:00:00+00:00"},)


def test_method_changes_are_listed_per_site_and_instrument() -> None:
    later = START + timedelta(hours=5)
    df = concat(
        frame(varying(5), site=SITE_A, poc=3, method="181"),
        frame(varying(1), site=SITE_A, poc=3, method="182", start=later),
        frame(varying(5), site=SITE_B, poc=1, method=None),
        frame(varying(5), site=SITE_B, poc=1, method="170", start=later),
    )
    items = check(df, sites=(SITE_A, SITE_B)).finding("method_changed").items
    at = "2024-03-01T12:00:00+00:00"
    assert items == (
        {"site_id": SITE_A, "poc": 3, "time_utc": at, "from": "181", "to": "182"},
        {"site_id": SITE_B, "poc": 1, "time_utc": at, "from": "none", "to": "170"},
    )


def test_a_site_reopened_on_one_poc_is_active_in_both_periods() -> None:
    reopened = ref(
        monitor(opened=date(2024, 1, 1)),
        monitor(opened=date(2010, 1, 1), closed=date(2012, 12, 31)),
    )
    result = check(frame(varying(24), method="182"), reference=reopened)
    assert result.finding("outside_active_period").count == 0


def test_a_monitor_closing_today_is_still_current() -> None:
    today = NOW.astimezone(PHOENIX).date()
    result = check(frame(varying(24), method="182"), reference=ref(monitor(closed=today)))
    assert result.finding("airnow_method_stale").count == 0


def test_our_own_coordinates_count_in_the_moved_check() -> None:
    lat, lon = SITE_COORDS[SITE_A]
    elsewhere = (lat + 1.2 / 111.19, lon)
    result = check(
        frame(varying(24), method="182"),
        reference=ref(monitor(coords=elsewhere), airnow={SITE_A: (elsewhere,)}),
    )
    assert result.finding("site_moved").count == 1


def test_exactly_the_tolerance_is_not_moved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ch, "distance_km", lambda _a, _b: MAX_SITE_OFFSET_KM)
    result = check(frame(varying(24), method="182"), reference=ref(monitor()))
    assert result.finding("site_moved").count == 0


def test_a_lone_point_has_moved_nowhere(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ch, "SITE_COORDS", {})
    result = check(frame(varying(24), method="182"), reference=ref(monitor(), airnow={}))
    assert result.finding("site_moved").count == 0


def test_the_offset_is_rounded_to_two_places() -> None:
    lat, lon = SITE_COORDS[SITE_A]
    shifted = (lat + 1.234 / 111.19, lon)
    result = check(frame(varying(24), method="182"), reference=ref(monitor(coords=shifted)))
    [item] = result.finding("site_moved").items
    assert item == {"site_id": SITE_A, "km": 1.23}


def test_a_site_starting_after_the_window_never_stops_the_next_sites_check() -> None:
    late_a = frame(varying(24), site=SITE_A, start=START + timedelta(days=3))
    short_b = frame(varying(10), site=SITE_B)
    f = check(concat(late_a, short_b), sites=(SITE_A, SITE_B), coverage_from="first_reading")
    assert f.finding("coverage_gap").items == (
        {"site_id": SITE_B, "month": "2024-03", "hours": 10, "expected": 24},
    )


def test_a_one_hour_window_with_no_reading_is_a_gap() -> None:
    hour = Window(START, START + timedelta(hours=1))
    df = frame(varying(3), start=START + timedelta(hours=2))
    assert check(df, window=hour).finding("coverage_gap").items == (
        {"site_id": SITE_A, "month": "2024-03", "hours": 0, "expected": 1},
    )


def test_missing_drop_counts_are_zero() -> None:
    df = frame(varying(24), method=None, poc=POC_NOT_GIVEN, source="airnow")
    result = check(df, drops={})
    for rule in (
        "airnow_not_aqs_id",
        "airnow_unmatched_site",
        "airnow_rows_dropped",
        "unit_mismatch",
    ):
        assert result.finding(rule).count == 0, rule


EAST = "Pacific/Kiritimati"
WEST = "Pacific/Pago_Pago"
"""UTC-11, west of Phoenix: a local month's first hour is still the month before there (#140)."""


@zone_moves
def test_months_are_named_in_the_city_zone() -> None:
    """00:00 Phoenix on 1 March is 20:00 on 29 February in Pago Pago: March stays March.

    A zone east of Phoenix can't catch this: there the same instant is still 1 March (#140).
    """
    feb = frame(varying(5), start=datetime(2024, 2, 29, 23, tzinfo=PHOENIX).astimezone(UTC))
    window = Window(datetime(2024, 2, 1, 7, tzinfo=UTC), START + timedelta(days=1))
    with process_zone(WEST):
        months = {i["month"] for i in check(feb, window=window).finding("coverage_gap").items}
    assert months == {"2024-02", "2024-03"}


@zone_moves
def test_the_first_month_is_the_city_zones() -> None:
    """23:00 Phoenix on 29 February is 20:00 on 1 March in Kiritimati: February's hour is judged."""
    window = Window(datetime(2024, 2, 29, 23, tzinfo=PHOENIX).astimezone(UTC), DAY.end)
    with process_zone(EAST):
        gaps = check(frame(varying(24)), window=window).finding("coverage_gap").items
    assert gaps == ({"site_id": SITE_A, "month": "2024-02", "hours": 0, "expected": 1},)


@zone_moves
def test_today_is_the_city_zones() -> None:
    """23:00 Phoenix on 11-24 is 20:00 on 11-25 in Kiritimati: a monitor closed 11-24 is open."""
    now = datetime(2026, 11, 24, 23, tzinfo=PHOENIX)
    df = frame(varying(24), method="182")
    with process_zone(EAST):
        result = check(df, now=now, reference=ref(monitor(closed=date(2026, 11, 24))))
    assert result.finding("airnow_method_stale").count == 0
