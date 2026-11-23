"""City data check (#9, T4): the frozen D-006 rules, on recorded and hand-built data.

Every test maps to a line of D-006's frozen criteria or clarifications. Hand-built rows use the
field names seen in a real AQS response (tests/fixtures/aqs, Charlotte, not a candidate).
"""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from airwatch.observations.metadata import (
    BAD_AIR_UG_M3,
    CityScore,
    choose_city,
    good_years,
    parse_airnow_active_pm25,
    score_city,
    site_days,
    strip_values,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "aqs" / "charlotte_daily_20230615.json"


def row(  # noqa: PLR0913  (mirrors the AQS row's fields)
    *,
    site: str = "0001",
    county: str = "031",
    state: str = "17",
    day: date = date(2020, 1, 1),
    poc: int = 1,
    hours: int = 24,
    mean: float = 10.0,
    code: str = "1",
    event: str = "No Events",
    param: str = "88101",
) -> dict[str, Any]:
    return {
        "state_code": state,
        "county_code": county,
        "site_number": site,
        "parameter_code": param,
        "poc": poc,
        "date_local": day.isoformat(),
        "sample_duration_code": code,
        "sample_duration": "1 HOUR" if code == "1" else "24-HR BLK AVG",
        "observation_count": hours,
        "arithmetic_mean": mean,
        "event_type": event,
    }


def year_of_rows(
    year: int, *, site: str = "0001", valid_days: int | None = None
) -> list[dict[str, Any]]:
    """A full calendar year for one site; the first `valid_days` days have 24 hours."""
    first = date(year, 1, 1)
    n = (date(year + 1, 1, 1) - first).days
    valid = n if valid_days is None else valid_days
    return [
        row(site=site, day=first + timedelta(days=i), hours=24 if i < valid else 10)
        for i in range(n)
    ]


def test_recorded_response_keeps_only_hourly_instruments() -> None:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    days = site_days(rows, keep_values=True)
    hourly = [r for r in rows if r["sample_duration_code"] == "1"]
    sites = {f"{r['state_code']}{r['county_code']}{r['site_number']}" for r in hourly}
    assert {k[0] for k in days} == sites
    assert all(len(k[0]) == 9 for k in days)
    assert all(v.valid for v in days.values())


def test_derived_block_average_rows_are_never_counted() -> None:
    days = site_days([row(code="X", hours=1)], keep_values=True)
    assert days == {}


def test_other_parameters_are_ignored() -> None:
    assert site_days([row(param="88502")], keep_values=True) == {}


@pytest.mark.parametrize(("hours", "valid"), [(17, False), (18, True), (24, True)])
def test_valid_day_needs_18_hours(hours: int, valid: bool) -> None:
    (day,) = site_days([row(hours=hours)], keep_values=True).values()
    assert day.valid is valid


def test_co_located_instruments_are_one_monitor() -> None:
    rows = [row(poc=1, hours=10, mean=20.0), row(poc=3, hours=20, mean=40.0)]
    days = site_days(rows, keep_values=True)
    assert len(days) == 1
    (day,) = days.values()
    assert day.valid
    assert day.mean == pytest.approx(30.0)


@pytest.mark.parametrize("excluded", ["Events Excluded", "Concurred Events Excluded"])
def test_an_event_day_keeps_its_included_row_once(excluded: str) -> None:
    rows = [
        row(event="Events Included", mean=80.0),
        row(event=excluded, mean=12.0),
    ]
    (day,) = site_days(rows, keep_values=True).values()
    assert day.mean == pytest.approx(80.0)


def test_an_unknown_event_type_stops_the_check() -> None:
    with pytest.raises(ValueError, match="event_type"):
        site_days([row(event="Something New")], keep_values=True)


def test_a_duplicate_instrument_day_stops_the_check() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        site_days([row(), row()], keep_values=True)


def test_a_malformed_site_id_stops_the_check() -> None:
    with pytest.raises(ValueError, match="unexpected AQS site id"):
        site_days([row(site="00A1")], keep_values=True)


def test_values_can_be_dropped_on_read() -> None:
    (day,) = site_days([row(mean=99.0)], keep_values=False).values()
    assert day.mean is None


def test_good_year_is_75_percent_of_days_including_leap_years() -> None:
    """2020 has 366 days, so 75% is 274.5; 2021 has 365, so 75% is 273.75."""
    good = good_years(site_days(year_of_rows(2020, valid_days=275), keep_values=True))
    assert good == {"170310001": {2020}}
    assert good_years(site_days(year_of_rows(2020, valid_days=274), keep_values=True)) == {}
    assert good_years(site_days(year_of_rows(2021, valid_days=274), keep_values=True)) == {
        "170310001": {2021}
    }
    assert good_years(site_days(year_of_rows(2021, valid_days=273), keep_values=True)) == {}


AIRNOW = "\n".join(
    [
        "StationID|AQSID|FullAQSID|Parameter|MonitorType|SiteCode|SiteName|Status|AgencyID",
        "x|170310001|840170310001|PM2.5|Permanent|0001|A|Active|IL1",
        "x|170310002|840170310002|PM2.5|Permanent|0002|B|Inactive|IL1",
        "x|170310003|840170310003|OZONE|Permanent|0003|C|Active|IL1",
    ]
)


def test_airnow_match_is_active_pm25_rows_only() -> None:
    assert parse_airnow_active_pm25(AIRNOW) == {"170310001"}


def test_airnow_parsing_uses_the_header_not_column_positions() -> None:
    lines = AIRNOW.splitlines()
    swapped = ["|".join(reversed(line.split("|"))) for line in lines]
    assert parse_airnow_active_pm25("\n".join(swapped)) == {"170310001"}


def history(site: str, years: range, *, mean: float = 10.0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for y in years:
        for r in year_of_rows(y, site=site):
            r["arithmetic_mean"] = mean
            rows.append(r)
    return rows


def city(  # noqa: PLR0913  (one knob per frozen rule)
    n_monitors: int,
    *,
    years: range = range(2017, 2025),
    bad_days_per_site: int = 30,
    test_monitors: int | None = None,
    weather_ok: bool = True,
    active: set[str] | None = None,
) -> CityScore:
    sites = [f"{i:04d}" for i in range(1, n_monitors + 1)]
    hist: list[dict[str, Any]] = []
    for s in sites:
        rows = history(s, years)
        for r in rows[:bad_days_per_site]:
            r["arithmetic_mean"] = 50.0
        hist += rows
    test: list[dict[str, Any]] = []
    for s in sites[: n_monitors if test_monitors is None else test_monitors]:
        test += strip_values(year_of_rows(2025, site=s))
    ids = {f"17031{s}" for s in sites} if active is None else active
    return score_city(
        "Test City",
        history_rows=hist,
        test_rows=test,
        airnow_active=ids,
        weather_ok=weather_ok,
    )


def test_a_city_with_everything_passes() -> None:
    score = city(5)
    assert score.passes, score.reasons
    assert len(score.qualifying) == 5
    assert score.test_year_monitors == 5


def test_fewer_than_five_qualifying_monitors_fails() -> None:
    score = city(4)
    assert not score.passes
    assert "4 qualifying monitors (< 5)" in score.reasons


def test_qualifying_needs_eight_good_years() -> None:
    score = city(5, years=range(2018, 2025))
    assert not score.passes
    assert score.qualifying == ()
    assert "0 qualifying monitors (< 5)" in score.reasons


def test_qualifying_needs_2024_to_be_a_good_year() -> None:
    score = city(5, years=range(2015, 2024))
    assert not score.passes
    assert score.qualifying == ()
    assert "0 qualifying monitors (< 5)" in score.reasons


def test_qualifying_needs_an_active_airnow_listing() -> None:
    score = city(5, active={"170310001", "170310002", "170310003", "170310004"})
    assert not score.passes
    assert "170310005" not in score.qualifying
    assert "4 qualifying monitors (< 5)" in score.reasons


def test_bad_air_share_must_reach_half_a_percent() -> None:
    assert BAD_AIR_UG_M3 == 35.0
    at = city(5, bad_days_per_site=0)
    assert at.bad_air_share == 0.0
    assert not city(5, bad_days_per_site=10).passes, (
        "8 years of about 365 days per site: 0.5% needs about 15 bad days per site"
    )
    assert city(5, bad_days_per_site=20).passes


def test_exactly_35_is_not_a_bad_air_day() -> None:
    sites = [f"{i:04d}" for i in range(1, 6)]
    hist = [r for s in sites for r in history(s, range(2017, 2025), mean=35.0)]
    score = score_city(
        "Edge",
        history_rows=hist,
        test_rows=strip_values([r for s in sites for r in year_of_rows(2025, site=s)]),
        airnow_active={f"17031{s}" for s in sites},
        weather_ok=True,
    )
    assert score.bad_air_share == 0.0


def test_test_year_needs_five_monitors_with_a_good_2025() -> None:
    score = city(5, test_monitors=4)
    assert not score.passes
    assert score.reasons == ("4 monitors with a good 2025 (< 5)",)


def test_weather_coverage_is_required() -> None:
    score = city(5, weather_ok=False)
    assert not score.passes
    assert score.reasons == ("no weather coverage",)


SITES5 = [f"{i:04d}" for i in range(1, 6)]
ACTIVE5 = {f"17031{s}" for s in SITES5}


def _passing_history() -> list[dict[str, Any]]:
    hist: list[dict[str, Any]] = []
    for s in SITES5:
        rows = history(s, range(2017, 2025))
        for r in rows[:30]:
            r["arithmetic_mean"] = 50.0
        hist += rows
    return hist


HIST5 = _passing_history()
BASELINE5 = city(5)


@settings(max_examples=20, deadline=None)
@given(values=st.lists(st.floats(min_value=0, max_value=500), min_size=366, max_size=366))
def test_2025_pm_values_never_change_the_result(values: list[float]) -> None:
    test = []
    for s in SITES5:
        for r, v in zip(year_of_rows(2025, site=s), values, strict=False):
            r["arithmetic_mean"] = v
            test.append(r)
    other = score_city(
        "Test City",
        history_rows=HIST5,
        test_rows=strip_values(test),
        airnow_active=ACTIVE5,
        weather_ok=True,
    )
    assert other == BASELINE5


def test_strip_values_removes_every_pm_value_field() -> None:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    stripped = strip_values(rows)
    value_fields = {"arithmetic_mean", "first_max_value", "first_max_hour", "aqi"}
    assert all(not (value_fields & r.keys()) for r in stripped)
    assert all("observation_count" in r for r in stripped)
    assert "arithmetic_mean" in rows[0]


def test_scoring_refuses_2025_rows_that_still_carry_values() -> None:
    with pytest.raises(ValueError, match="2025"):
        score_city(
            "X",
            history_rows=HIST5,
            test_rows=year_of_rows(2025),
            airnow_active=ACTIVE5,
            weather_ok=True,
        )


def test_rows_outside_2009_2024_are_not_history() -> None:
    sites = [f"{i:04d}" for i in range(1, 6)]
    hist = [r for s in sites for r in history(s, range(2017, 2025))]
    extra = [r for s in sites for r in history(s, range(2008, 2009), mean=80.0)]
    a = score_city(
        "A",
        history_rows=hist,
        test_rows=[],
        airnow_active={f"17031{s}" for s in sites},
        weather_ok=True,
    )
    b = score_city(
        "A",
        history_rows=hist + extra,
        test_rows=[],
        airnow_active={f"17031{s}" for s in sites},
        weather_ok=True,
    )
    assert a == b


def scored(name: str, *, passes: bool, monitors: int, share: float) -> CityScore:
    return CityScore(
        name=name,
        qualifying=tuple(f"{i:09d}" for i in range(monitors)),
        bad_air_share=share,
        test_year_monitors=monitors,
        weather_ok=True,
        passes=passes,
        reasons=() if passes else ("failed",),
    )


def test_chicago_wins_whenever_it_passes() -> None:
    scores = [
        scored("Chicago", passes=True, monitors=5, share=0.01),
        scored("Los Angeles", passes=True, monitors=30, share=0.05),
    ]
    assert choose_city(scores) == "Chicago"


def test_otherwise_most_monitors_then_bad_air_share() -> None:
    scores = [
        scored("Chicago", passes=False, monitors=3, share=0.0),
        scored("Phoenix", passes=True, monitors=8, share=0.02),
        scored("Salt Lake City", passes=True, monitors=8, share=0.03),
        scored("Los Angeles", passes=True, monitors=7, share=0.10),
    ]
    assert choose_city(scores) == "Salt Lake City"


def test_no_passing_city_means_no_choice() -> None:
    assert choose_city([scored("Chicago", passes=False, monitors=1, share=0.0)]) is None
