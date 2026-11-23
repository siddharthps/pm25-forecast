"""AirNow hourly reader (#10, T5): recorded file, hand-built rows, fake transport.

Facts checked on a real file (HourlyAQObs_2026111901.dat, kept trimmed as the fixture):
`PM25` is the raw hourly value (it equals the HourlyData product's PM2.5 for all 10 training
sites), `ValidDate`/`ValidTime` are UTC, and `AQSID` is the AQS site ID.
"""

import csv
import io
import logging
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import pytest

from airwatch.observations.airnow import (
    fetch_hour,
    fetch_local_day,
    hourly_file_url,
    hours_for_local_day,
    keep_sites,
    parse_hourly_aqobs,
)
from airwatch.observations.metadata import FetchError
from airwatch.observations.schema import validate_hourly
from airwatch.observations.sites import TRAINING_SITES
from tests.unit.observations.airnow_fakes import PUBLISHED, day_transport, file_for_hour, text

PHOENIX = ZoneInfo("America/Phoenix")


def with_rows(edit: dict[str, dict[str, str]]) -> str:
    """The fixture with some rows' fields replaced (keyed by AQSID)."""
    rows = list(csv.DictReader(io.StringIO(text())))
    for r in rows:
        r.update(edit.get(r["AQSID"], {}))
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=list(rows[0]), quoting=csv.QUOTE_ALL)
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()


def test_recorded_file_parses_to_the_schema() -> None:
    df, dropped = parse_hourly_aqobs(text(), PUBLISHED)
    validate_hourly(df)
    assert len(df) == 14
    assert (df["source"] == "airnow").all()
    assert (df["time_utc"] == pd.Timestamp("2026-11-19 01:00", tz="UTC")).all()
    assert (df["available_at_utc"] == pd.Timestamp(PUBLISHED)).all()
    assert sum(dropped.values()) == 57 - 14


def test_values_match_the_recording() -> None:
    df, _ = parse_hourly_aqobs(text(), PUBLISHED)
    west_phoenix = df[df["site_id"] == "040130019"]
    assert west_phoenix["value_ug_m3"].tolist() == [10.5]


def test_rows_without_a_measured_value_are_dropped_and_counted() -> None:
    _, dropped = parse_hourly_aqobs(text(), PUBLISHED)
    assert dropped == {"no_pm25_value": 43}


def test_a_value_not_flagged_as_measured_is_dropped_and_counted() -> None:
    edited = with_rows({"040130019": {"PM25_Measured": "0"}})
    df, dropped = parse_hourly_aqobs(edited, PUBLISHED)
    assert "040130019" not in set(df["site_id"])
    assert dropped["not_measured"] == 1


@pytest.mark.parametrize("site_id", ["031AZE010001", "124000050314", "AB1234567"])
def test_monitors_without_an_aqs_site_id_are_dropped_and_counted(site_id: str) -> None:
    edited = with_rows({"040130019": {"AQSID": site_id}})
    df, dropped = parse_hourly_aqobs(edited, PUBLISHED)
    assert site_id not in set(df["site_id"])
    assert dropped["not_an_aqs_site_id"] == 1


def test_other_units_are_dropped_and_counted() -> None:
    edited = with_rows({"040130019": {"PM25_Unit": "PPB"}})
    df, dropped = parse_hourly_aqobs(edited, PUBLISHED)
    assert "040130019" not in set(df["site_id"])
    assert dropped["unit_not_ug_m3"] == 1


def test_parsing_uses_the_header_not_column_positions() -> None:
    rows = list(csv.reader(io.StringIO(text())))
    reordered = [list(reversed(r)) for r in rows]
    out = io.StringIO()
    csv.writer(out, quoting=csv.QUOTE_ALL).writerows(reordered)
    a, _ = parse_hourly_aqobs(text(), PUBLISHED)
    b, _ = parse_hourly_aqobs(out.getvalue(), PUBLISHED)
    pd.testing.assert_frame_equal(a, b)


def test_published_before_the_hour_is_refused() -> None:
    with pytest.raises(ValueError, match="before"):
        parse_hourly_aqobs(text(), datetime(2026, 11, 19, 0, 59, tzinfo=UTC))


def test_naive_published_time_is_refused() -> None:
    with pytest.raises(ValueError, match="naive"):
        parse_hourly_aqobs(text(), datetime(2026, 11, 19, 4, 21))  # noqa: DTZ001


def test_all_training_sites_are_in_the_recording() -> None:
    df, _ = parse_hourly_aqobs(text(), PUBLISHED)
    kept, unmatched = keep_sites(df, TRAINING_SITES)
    assert set(kept["site_id"]) == set(TRAINING_SITES)
    assert unmatched == len(df) - len(kept)


def test_unmatched_monitors_are_excluded() -> None:
    df, _ = parse_hourly_aqobs(text(), PUBLISHED)
    kept, unmatched = keep_sites(df, ("040130019",))
    assert set(kept["site_id"]) == {"040130019"}
    assert unmatched == len(df) - 1


def test_a_phoenix_day_is_24_files_from_07_utc() -> None:
    hours = hours_for_local_day(date(2026, 11, 18), PHOENIX)
    assert len(hours) == 24
    assert hours[0] == datetime(2026, 11, 18, 7, tzinfo=UTC)
    assert hours[-1] == datetime(2026, 11, 19, 6, tzinfo=UTC)


def test_a_dst_day_has_23_or_25_files() -> None:
    chicago = ZoneInfo("America/Chicago")
    assert len(hours_for_local_day(date(2026, 3, 8), chicago)) == 23
    assert len(hours_for_local_day(date(2026, 11, 1), chicago)) == 25


def test_file_url_follows_airnow_layout() -> None:
    url = hourly_file_url(datetime(2026, 11, 19, 1, tzinfo=UTC))
    assert url == "https://files.airnowtech.org/airnow/2026/20261119/HourlyAQObs_2026111901.dat"


def test_file_url_refuses_a_naive_hour() -> None:
    with pytest.raises(ValueError, match="naive"):
        hourly_file_url(datetime(2026, 11, 19, 1))  # noqa: DTZ001


def test_fetching_logs_no_url_query(caplog: pytest.LogCaptureFixture) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=text(), headers={"Last-Modified": "Thu, 19 Nov 2026 04:21:33 GMT"}
        )

    with caplog.at_level(logging.DEBUG), httpx.Client(transport=httpx.MockTransport(handler)) as c:
        body, published = fetch_hour(c, datetime(2026, 11, 19, 1, tzinfo=UTC))
    assert published == PUBLISHED
    assert body == text()
    assert "files.airnowtech.org" not in caplog.text


def test_a_file_without_a_publication_time_is_refused() -> None:
    """Last-Modified is when the hour became known; the issue-time cut can't do without it."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=text())

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as c,
        pytest.raises(RuntimeError, match="no Last-Modified header"),
    ):
        fetch_hour(c, datetime(2026, 11, 19, 1, tzinfo=UTC))


def test_a_local_day_is_fetched_hour_by_hour_for_the_training_sites() -> None:
    with httpx.Client(transport=day_transport()) as c:
        df, drops = fetch_local_day(c, date(2026, 11, 18), PHOENIX, TRAINING_SITES)
    validate_hourly(df)
    assert len(df) == 24 * len(TRAINING_SITES)
    assert df["time_utc"].min() == pd.Timestamp("2026-11-18 07:00", tz=UTC)
    assert df["time_utc"].max() == pd.Timestamp("2026-11-19 06:00", tz=UTC)
    assert not df.duplicated(["site_id", "time_utc"]).any()
    one_file, one_drops = parse_hourly_aqobs(
        file_for_hour(datetime(2026, 11, 18, 7, tzinfo=UTC)), PUBLISHED
    )
    assert drops["unmatched_site"] == 24 * (len(one_file) - len(TRAINING_SITES))
    for reason, n in one_drops.items():
        assert drops[reason] == 24 * n


def test_a_missing_hourly_file_is_counted_not_fatal() -> None:
    with httpx.Client(transport=day_transport(missing=frozenset({10, 11}))) as c:
        df, drops = fetch_local_day(c, date(2026, 11, 18), PHOENIX, TRAINING_SITES)
    assert drops["file_missing"] == 2
    assert df["time_utc"].nunique() == 22


def test_any_other_fetch_failure_stops_the_day() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c, pytest.raises(FetchError):
        fetch_local_day(c, date(2026, 11, 18), PHOENIX, TRAINING_SITES)
