"""The CAMS client and daily means (#19, T14; D-052), on recorded responses and a fake transport.

Fixtures are real responses for South Phoenix (040134003), recorded 2026-11-24 about 11:50 UTC:
the stitched history for 2026-11-20/21 and the single run started 2026-11-20 00 UTC (168 hourly
stamps, the run's 121 hours from its start filled). Their structure, stamps and grid point are as
received; **the `pm2_5` values are synthetic** (5 + 0.5 x the hour's index within its day), as
whether CAMS values may be shown publicly is still open (#78). The checks read structure only.
"""

import copy
import json
import math
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import pytest

from airwatch.errors import ReportableError
from airwatch.observations.metadata import FetchError
from airwatch.observations.sites import SITE_COORDS
from airwatch.weather.cams import (
    COLUMNS,
    HISTORY_START,
    PUBLISH_DELAY,
    UNIT,
    URLS,
    CamsQuery,
    CamsSource,
    daily_means,
    fetch,
    issued_run_start,
    parse,
)
from airwatch.weather.openmeteo import WeatherResponseError

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "openmeteo"
SITE = "040134003"
PHOENIX = ZoneInfo("America/Phoenix")
RUN = datetime(2026, 11, 20, tzinfo=UTC)


def load(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return payload


HISTORY = load("cams_history_040134003_20261120.json")
SINGLE_RUN = load("cams_run_040134003_2026112000.json")
QUERIES = {
    CamsSource.HISTORY: CamsQuery.history(SITE, date(2026, 11, 20), date(2026, 11, 21)),
    CamsSource.RUN: CamsQuery.run_at(SITE, RUN),
}
PAYLOADS = {CamsSource.HISTORY: HISTORY, CamsSource.RUN: SINGLE_RUN}


def rows(source: CamsSource, payload: dict[str, Any] | None = None) -> pd.DataFrame:
    return parse(QUERIES[source], PAYLOADS[source] if payload is None else payload)


def changed(source: CamsSource, edit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    payload = copy.deepcopy(PAYLOADS[source])
    edit(payload)
    return payload


def test_the_unit_is_the_one_the_api_spells_with_a_greek_mu() -> None:
    assert UNIT == "μg/m³"
    assert HISTORY["hourly_units"]["pm2_5"] == UNIT


def test_the_history_query_asks_cams_global_for_utc_days_at_the_monitor() -> None:
    lat, lon = SITE_COORDS[SITE]
    assert QUERIES[CamsSource.HISTORY].params() == {
        "latitude": repr(lat),
        "longitude": repr(lon),
        "hourly": "pm2_5",
        "domains": "cams_global",
        "start_date": "2026-11-20",
        "end_date": "2026-11-21",
        "timezone": "GMT",
        "cell_selection": "land",
    }


def test_the_run_query_names_its_run_and_no_dates() -> None:
    params = QUERIES[CamsSource.RUN].params()
    assert params["models"] == "cams_global"
    assert params["run"] == "2026-11-20T00:00"
    assert not {"start_date", "end_date", "domains"} & set(params)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"start": date(2026, 11, 21), "end": date(2026, 11, 20)}, "end before start"),
        ({"start": date(2026, 11, 20), "end": None}, "a history query needs its days"),
        ({"run": datetime(2026, 11, 20, 6, tzinfo=UTC)}, "not a CAMS start"),
        ({"run": datetime(2026, 11, 20)}, "naive datetime rejected"),  # noqa: DTZ001
    ],
    ids=["end_before_start", "no_end", "off_cycle_run", "naive_run"],
)
def test_a_malformed_query_is_refused(kwargs: dict[str, Any], message: str) -> None:
    source = CamsSource.RUN if "run" in kwargs else CamsSource.HISTORY
    with pytest.raises(ValueError, match=message):
        CamsQuery(source, SITE, 33.4, -112.1, **kwargs)


def test_history_rows_name_the_run_each_hour_was_stitched_from() -> None:
    df = rows(CamsSource.HISTORY)
    assert list(df.columns) == list(COLUMNS)
    assert len(df) == 48
    assert (df["source"] == "cams_history").all()
    by_hour = df.set_index("valid_utc")["run_start_utc"]
    assert by_hour[pd.Timestamp("2026-11-20 11:00", tz="UTC")] == pd.Timestamp(RUN)
    assert by_hour[pd.Timestamp("2026-11-20 12:00", tz="UTC")] == pd.Timestamp(
        RUN + timedelta(hours=12)
    )
    assert (df["available_at_utc"] == df["run_start_utc"] + PUBLISH_DELAY).all()


def test_run_rows_carry_the_run_and_leave_hours_past_its_end_missing() -> None:
    df = rows(CamsSource.RUN)
    assert len(df) == 168
    assert (df["run_start_utc"] == pd.Timestamp(RUN)).all()
    assert (df["available_at_utc"] == pd.Timestamp(RUN + PUBLISH_DELAY)).all()
    filled = df.dropna(subset=["pm2_5"])["valid_utc"]
    assert (filled.min(), filled.max()) == (
        pd.Timestamp(RUN),
        pd.Timestamp(RUN + timedelta(hours=120)),
    )


def _set(path: tuple[str, ...], value: Any) -> Callable[[dict[str, Any]], None]:
    def edit(payload: dict[str, Any]) -> None:
        target = payload
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return edit


def _drop_hour(payload: dict[str, Any]) -> None:
    del payload["hourly"]["time"][5]
    del payload["hourly"]["pm2_5"][5]


def _shorten_values(payload: dict[str, Any]) -> None:
    payload["hourly"]["pm2_5"].pop()


def _drop_variable(payload: dict[str, Any]) -> None:
    del payload["hourly"]["pm2_5"]


@pytest.mark.parametrize(
    ("source", "edit", "rule"),
    [
        (CamsSource.HISTORY, _set(("error",), True), "error_payload"),
        (CamsSource.HISTORY, _set(("utc_offset_seconds",), 3600), "not_utc"),
        (CamsSource.HISTORY, _drop_variable, "missing_variable"),
        (CamsSource.HISTORY, _set(("hourly_units", "pm2_5"), "µg/m³"), "unit"),
        (CamsSource.HISTORY, _shorten_values, "column_length"),
        (CamsSource.HISTORY, _drop_hour, "hours"),
        (CamsSource.HISTORY, _set(("latitude",), 34.0), "grid_too_far"),
        (CamsSource.RUN, _drop_hour, "hours"),
    ],
    ids=[
        "error",
        "not_utc",
        "missing_variable",
        "micro_sign_unit",
        "column_length",
        "history_hour_missing",
        "grid_too_far",
        "run_hour_missing",
    ],
)
def test_a_response_is_refused_by_its_named_rule(
    source: CamsSource, edit: Callable[[dict[str, Any]], None], rule: str
) -> None:
    payload = changed(source, edit)
    with pytest.raises(WeatherResponseError, match=rf"^{rule}:"):
        rows(source, payload)


def test_run_stamps_must_start_at_the_run_days_midnight() -> None:
    payload = copy.deepcopy(SINGLE_RUN)
    payload["hourly"]["time"] = [
        (datetime.fromisoformat(t) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        for t in payload["hourly"]["time"]
    ]
    with pytest.raises(WeatherResponseError, match=r"^hours:"):
        rows(CamsSource.RUN, payload)


def test_a_value_stamped_before_the_run_started_is_refused() -> None:
    query = CamsQuery.run_at(SITE, RUN + timedelta(hours=12))
    with pytest.raises(WeatherResponseError, match=r"^before_run_start:"):
        parse(query, SINGLE_RUN)


def test_refusals_are_reportable_and_hold_no_value() -> None:
    payload = changed(CamsSource.HISTORY, _set(("latitude",), 34.0))
    with pytest.raises(ReportableError) as info:
        rows(CamsSource.HISTORY, payload)
    assert "34" not in str(info.value)


def test_a_history_before_its_first_day_is_refused() -> None:
    with pytest.raises(ValueError, match="before the CAMS history starts"):
        CamsQuery.history(SITE, HISTORY_START - timedelta(days=1), HISTORY_START)


def test_the_daily_mean_is_over_the_24_stamps_of_the_local_day() -> None:
    means = daily_means(rows(CamsSource.HISTORY), [date(2026, 11, 20)], PHOENIX)
    assert means.to_dict("records") == [
        {"site_id": SITE, "day": date(2026, 11, 20), "hours": 24, "cams_mean": 10.75}
    ]


def test_a_day_missing_any_hour_has_no_mean_and_says_how_many_it_had() -> None:
    df = rows(CamsSource.HISTORY)
    df.loc[df["valid_utc"] == pd.Timestamp("2026-11-20 08:00", tz="UTC"), "pm2_5"] = math.nan
    means = daily_means(df, [date(2026, 11, 20), date(2026, 11, 21)], PHOENIX)
    assert means["hours"].tolist() == [23, 17]
    assert means["cams_mean"].isna().all()


def test_daily_means_keep_each_site_apart() -> None:
    one = rows(CamsSource.HISTORY)
    other = one.assign(site_id="040139997", pm2_5=one["pm2_5"] + 100)
    means = daily_means(pd.concat([other, one]), [date(2026, 11, 20)], PHOENIX)
    assert means.set_index("site_id")["cams_mean"].to_dict() == {
        "040134003": 10.75,
        "040139997": 110.75,
    }


def test_the_issued_run_for_a_target_day_reaches_it() -> None:
    target = date(2026, 11, 21)
    assert issued_run_start(target) == RUN
    means = daily_means(rows(CamsSource.RUN), [target], PHOENIX)
    assert means["hours"].tolist() == [24]


def client_for(
    queues: dict[str, list[dict[str, Any]]],
) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url.copy_with(query=None))
        if not queues.get(url):
            return httpx.Response(404)
        return httpx.Response(200, json=queues[url].pop(0))

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


@pytest.mark.parametrize("source", list(CamsSource), ids=lambda s: s.value)
def test_fetch_sends_the_query_to_its_api(source: CamsSource) -> None:
    client, seen = client_for({URLS[source]: [PAYLOADS[source]]})
    df = fetch(client, QUERIES[source], backoff_s=0)
    assert [str(r.url.copy_with(query=None)) for r in seen] == [URLS[source]]
    assert dict(parse_qsl(seen[0].url.query.decode())) == QUERIES[source].params()
    assert len(df) == len(PAYLOADS[source]["hourly"]["time"])


def test_fetch_passes_on_a_failed_request() -> None:
    client, _ = client_for({})
    with pytest.raises(FetchError, match="404"):
        fetch(client, QUERIES[CamsSource.HISTORY], backoff_s=0)
