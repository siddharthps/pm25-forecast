"""AQS hourly client and daily means (#10, T5): recorded fixture, hand-built rows, fake transport.

Rules under test (SPEC § Key definitions; D-006/D-030; OQ-8):

- hourly PM2.5 (88101, 1-hour duration) only, in µg/m³;
- timestamps built from AQS's UTC fields, never its local-standard-time fields;
- `available_at_utc` = the end of the day AQS last changed the record, never before the hour;
- a daily mean averages co-located instruments (POCs) per hour first, then needs ≥ 18 hours of
  the city's local day.
"""

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from airwatch.observations.aqs import daily_means, fetch_site_year, parse_sample_rows
from airwatch.observations.schema import (
    HOURLY_COLUMNS,
    count_outside_crude_range,
    validate_hourly,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "aqs"
PHOENIX = ZoneInfo("America/Phoenix")


def recorded() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = json.loads(
        (FIXTURES / "charlotte_sample_20230615.json").read_text(encoding="utf-8")
    )
    return rows


def hour(  # noqa: PLR0913  (mirrors the AQS row)
    when_utc: datetime,
    *,
    value: float | None = 10.0,
    poc: int = 1,
    site: str = "0019",
    code: str = "1",
    units: str = "Micrograms/cubic meter (LC)",
    changed: str = "2025-03-01",  # after every default measurement below
    param: str = "88101",
) -> dict[str, Any]:
    return {
        "state_code": "04",
        "county_code": "013",
        "site_number": site,
        "parameter_code": param,
        "poc": poc,
        "date_gmt": when_utc.date().isoformat(),
        "time_gmt": when_utc.strftime("%H:%M"),
        "date_local": "ignored",
        "time_local": "ignored",
        "sample_duration_code": code,
        "sample_measurement": value,
        "units_of_measure": units,
        "method_code": "170",
        "method_type": "FEM",
        "qualifier": None,
        "date_of_last_change": changed,
    }


def phoenix_day(day: date, hours: int, **kw: Any) -> list[dict[str, Any]]:
    """`hours` hourly rows from local midnight of `day` in Phoenix (UTC-7 all year)."""
    start = datetime(day.year, day.month, day.day, tzinfo=PHOENIX).astimezone(UTC)
    return [hour(start + timedelta(hours=h), **kw) for h in range(hours)]


# --- parsing --------------------------------------------------------------------------------


def test_recorded_rows_parse_to_the_schema() -> None:
    df = parse_sample_rows(recorded())
    validate_hourly(df)
    assert list(df.columns) == list(HOURLY_COLUMNS)
    assert len(df) == 24
    first = df.iloc[0]
    r = recorded()[0]
    assert first["site_id"] == f"{r['state_code']}{r['county_code']}{r['site_number']}"
    assert len(first["site_id"]) == 9
    assert first["poc"] == 3
    assert first["method_code"] == "209"
    assert first["qualifier"] == "IF - Fire - Canadian."


def test_timestamps_come_from_the_utc_fields() -> None:
    # AQS time_local is local *standard* time (no DST): 00:00 local was 05:00 UTC in Charlotte in
    # June, when the civil clock was UTC-4. Only the GMT fields are used.
    df = parse_sample_rows(recorded())
    assert df["time_utc"].iloc[0] == pd.Timestamp("2023-06-15 05:00", tz="UTC")
    assert str(df["time_utc"].dt.tz) == "UTC"


def test_available_at_is_the_end_of_the_last_change_day() -> None:
    df = parse_sample_rows(recorded())  # date_of_last_change 2023-07-18
    assert (df["available_at_utc"] == pd.Timestamp("2023-07-19 00:00", tz="UTC")).all()


def test_only_hourly_pm25_rows_are_kept() -> None:
    t = datetime(2024, 1, 1, 12, tzinfo=UTC)
    rows = [hour(t), hour(t, code="X"), hour(t, param="88502")]
    assert len(parse_sample_rows(rows)) == 1


def test_missing_measurements_are_dropped() -> None:
    t = datetime(2024, 1, 1, 12, tzinfo=UTC)
    assert len(parse_sample_rows([hour(t, value=None), hour(t + timedelta(hours=1))])) == 1


def test_unexpected_units_stop_parsing() -> None:
    with pytest.raises(ValueError, match="units"):
        parse_sample_rows([hour(datetime(2024, 1, 1, tzinfo=UTC), units="ppb")])


@given(
    offset_h=st.integers(min_value=0, max_value=24 * 365 * 3),
    lag_days=st.integers(min_value=0, max_value=400),
)
def test_data_is_never_available_before_it_was_measured(offset_h: int, lag_days: int) -> None:
    when = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(hours=offset_h)
    changed = (when + timedelta(days=lag_days)).date().isoformat()
    df = parse_sample_rows([hour(when, changed=changed)])
    assert (df["available_at_utc"] > df["time_utc"]).all()


def test_a_change_date_before_the_measurement_stops_parsing() -> None:
    with pytest.raises(ValueError, match="before"):
        parse_sample_rows([hour(datetime(2024, 5, 2, 12, tzinfo=UTC), changed="2024-05-01")])


# --- schema ---------------------------------------------------------------------------------


def test_schema_rejects_naive_timestamps() -> None:
    df = parse_sample_rows([hour(datetime(2024, 1, 1, tzinfo=UTC))])
    df["time_utc"] = df["time_utc"].dt.tz_localize(None)
    with pytest.raises(ValueError, match="time_utc"):
        validate_hourly(df)


def test_schema_rejects_missing_columns() -> None:
    df = parse_sample_rows([hour(datetime(2024, 1, 1, tzinfo=UTC))]).drop(columns=["poc"])
    with pytest.raises(ValueError, match="poc"):
        validate_hourly(df)


@pytest.mark.parametrize("value", [-10.1, 1167.0, 5000.0])
def test_out_of_range_values_are_kept_and_counted_not_rejected(value: float) -> None:
    # D-031: raw data is stored as received. A reading outside the crude range (for example
    # 1,167 at midnight on New Year's 2014 in Phoenix: fireworks) is counted, never dropped or
    # blocked here. T12 decides its treatment with a sourced bound.
    t = datetime(2024, 1, 1, tzinfo=UTC)
    df = parse_sample_rows([hour(t, value=value), hour(t + timedelta(hours=1), value=8.0)])
    validate_hourly(df)
    assert len(df) == 2
    assert count_outside_crude_range(df) == 1


def test_values_inside_the_crude_range_are_not_counted() -> None:
    t = datetime(2024, 1, 1, tzinfo=UTC)
    df = parse_sample_rows([hour(t, value=-10.0), hour(t + timedelta(hours=1), value=1000.0)])
    assert count_outside_crude_range(df) == 0


# --- daily means ----------------------------------------------------------------------------

DAY = date(2024, 7, 4)


def test_daily_mean_over_a_full_local_day() -> None:
    rows = phoenix_day(DAY, 24, value=12.0)
    out = daily_means(parse_sample_rows(rows), PHOENIX)
    assert len(out) == 1
    assert out.iloc[0]["date_local"] == DAY
    assert out.iloc[0]["mean_ug_m3"] == pytest.approx(12.0)
    assert out.iloc[0]["n_hours"] == 24


@pytest.mark.parametrize(("hours", "kept"), [(17, 0), (18, 1)])
def test_daily_mean_needs_18_hours(hours: int, kept: int) -> None:
    assert len(daily_means(parse_sample_rows(phoenix_day(DAY, hours)), PHOENIX)) == kept


def test_co_located_instruments_are_averaged_per_hour_first() -> None:
    # POC 1 reports 24 hours at 10; POC 3 reports only the first 12 hours, at 30. Averaging per
    # hour first gives 12 hours at 20 and 12 at 10: a mean of 15 (not 16.67 from pooling rows).
    rows = phoenix_day(DAY, 24, value=10.0, poc=1) + phoenix_day(DAY, 12, value=30.0, poc=3)
    out = daily_means(parse_sample_rows(rows), PHOENIX)
    assert out.iloc[0]["mean_ug_m3"] == pytest.approx(15.0)
    assert out.iloc[0]["n_hours"] == 24


def test_local_day_follows_the_city_zone_not_utc() -> None:
    # 23:00 local on July 4 in Phoenix is 06:00 UTC on July 5: it belongs to July 4.
    rows = phoenix_day(DAY, 24)
    out = daily_means(parse_sample_rows(rows), PHOENIX)
    assert list(out["date_local"]) == [DAY]


def test_daily_available_at_is_the_latest_contributing_hour() -> None:
    rows = [
        *phoenix_day(DAY, 23, changed="2024-08-01"),
        hour(datetime(2024, 7, 5, 6, tzinfo=UTC), changed="2024-09-01"),  # 23:00 local on July 4
    ]
    out = daily_means(parse_sample_rows(rows), PHOENIX)
    assert out.iloc[0]["available_at_utc"] == pd.Timestamp("2024-09-02", tz="UTC")


# --- fetching (fake transport) ----------------------------------------------------------------

AUTH = {"email": "someone@example.invalid", "key": "key-value-7e1f"}


def test_fetch_asks_for_one_site_and_one_whole_year(caplog: pytest.LogCaptureFixture) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"Header": [{"status": "Success"}], "Data": recorded()})

    with caplog.at_level(logging.DEBUG), httpx.Client(transport=httpx.MockTransport(handler)) as c:
        rows = fetch_site_year(c, AUTH, "040130019", 2021)
    assert len(rows) == 24
    q = dict(seen[0].url.params)
    assert seen[0].url.path.endswith("/sampleData/bySite")
    assert (q["state"], q["county"], q["site"]) == ("04", "013", "0019")
    assert (q["bdate"], q["edate"], q["param"]) == ("20210101", "20211231", "88101")
    for secret in AUTH.values():
        assert secret not in caplog.text


def test_fetch_treats_no_data_as_empty() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Header": [{"status": "No data matched your selection"}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert fetch_site_year(c, AUTH, "040130019", 2009) == []


def test_fetch_failure_names_no_secret() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Header": [{"status": "Failed", "error": ["bad key"]}]})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as c,
        pytest.raises(RuntimeError) as e,
    ):
        fetch_site_year(c, AUTH, "040130019", 2009)
    for secret in AUTH.values():
        assert secret not in str(e.value)
