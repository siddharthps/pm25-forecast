"""The Open-Meteo client (#19, T14; D-051), on real recorded responses and a fake transport.

Fixtures are real responses for South Phoenix (040134003): ERA5 and the GFS archive for
2024-06-15/16, the live GFS forecast for 2026-11-25/26, and the ncep_gfs013 metadata read
2026-11-24 about 03:30 UTC (its 18 UTC run of 2026-11-23, available 23:20:43 UTC).
"""

import copy
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pandas as pd
import pytest

from airwatch.errors import ReportableError
from airwatch.observations.metadata import FetchError
from airwatch.observations.sites import SITE_COORDS
from airwatch.weather.leads import MAX_PUBLISH_DELAY, archived_run_start
from airwatch.weather.openmeteo import (
    COLUMNS,
    GFS_META_URL,
    UNITS,
    URLS,
    VARIABLES,
    LiveRun,
    Query,
    Source,
    WeatherResponseError,
    fetch_hourly,
    fetch_live,
    parse_hourly,
    parse_live_run,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "openmeteo"
SITE = "040134003"
FETCHED = datetime(2026, 11, 24, 3, 30, tzinfo=UTC)
JUNE = (date(2024, 6, 15), date(2024, 6, 16))
NOVEMBER = (date(2026, 11, 25), date(2026, 11, 26))
RUN = LiveRun(
    started_utc=datetime(2026, 11, 23, 18, tzinfo=UTC),
    available_utc=datetime(2026, 11, 23, 23, 20, 43, tzinfo=UTC),
)


def load(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return payload


PAYLOADS = {
    Source.ERA5: load("era5_040134003_20240615.json"),
    Source.GFS_ARCHIVE: load("gfs_archive_040134003_20240615.json"),
    Source.GFS_LIVE: load("gfs_live_040134003_20261125.json"),
}
META = load("meta_ncep_gfs013.json")


def query(source: Source) -> Query:
    return Query.for_site(source, SITE, *(NOVEMBER if source is Source.GFS_LIVE else JUNE))


def parse(source: Source, payload: dict[str, Any] | None = None) -> pd.DataFrame:
    return parse_hourly(
        query(source),
        PAYLOADS[source] if payload is None else payload,
        fetched_utc=FETCHED,
        live_run=RUN if source is Source.GFS_LIVE else None,
    )


def test_the_eight_variables_and_their_units_are_d051s() -> None:
    assert UNITS == {
        "temperature_2m": "°C",
        "relative_humidity_2m": "%",
        "wind_speed_10m": "km/h",
        "wind_direction_10m": "°",
        "precipitation": "mm",
        "surface_pressure": "hPa",
        "cloud_cover": "%",
        "shortwave_radiation": "W/m²",
    }
    assert VARIABLES == (
        "temperature_2m",
        "relative_humidity_2m",
        "wind_speed_10m",
        "wind_direction_10m",
        "precipitation",
        "surface_pressure",
        "cloud_cover",
        "shortwave_radiation",
    ), "the column order"


def test_a_site_query_uses_the_sites_own_coordinates() -> None:
    q = query(Source.ERA5)
    assert (q.lat, q.lon) == SITE_COORDS[SITE] == (33.40314, -112.07526)


def test_era5_params() -> None:
    assert URLS[Source.ERA5] == "https://archive-api.open-meteo.com/v1/archive"
    assert query(Source.ERA5).params() == {
        "latitude": "33.40314",
        "longitude": "-112.07526",
        "hourly": ",".join(VARIABLES),
        "models": "era5",
        "start_date": "2024-06-15",
        "end_date": "2024-06-16",
        "timezone": "GMT",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "cell_selection": "land",
    }


def test_archive_params_ask_for_the_72_hour_offset_only() -> None:
    assert URLS[Source.GFS_ARCHIVE] == "https://previous-runs-api.open-meteo.com/v1/forecast"
    params = query(Source.GFS_ARCHIVE).params()
    assert params["hourly"] == ",".join(f"{v}_previous_day3" for v in VARIABLES)
    assert params["models"] == "gfs_global"


def test_live_params() -> None:
    assert URLS[Source.GFS_LIVE] == "https://api.open-meteo.com/v1/forecast"
    params = query(Source.GFS_LIVE).params()
    assert params["hourly"] == ",".join(VARIABLES)
    assert params["models"] == "gfs_global"
    assert (params["start_date"], params["end_date"]) == ("2026-11-25", "2026-11-26")


def test_a_query_refuses_an_end_before_the_start() -> None:
    with pytest.raises(ValueError, match="end before start"):
        Query.for_site(Source.ERA5, SITE, date(2024, 6, 16), date(2024, 6, 15))


@pytest.mark.parametrize("source", list(Source))
def test_parse_gives_one_row_per_utc_hour(source: Source) -> None:
    df = parse(source)
    q = query(source)
    assert tuple(df.columns) == COLUMNS
    assert df["valid_utc"].tolist() == q.hours()
    assert len(df) == 48
    assert str(df["valid_utc"].dt.tz) == "UTC"
    assert (df["site_id"] == SITE).all()
    assert (df["source"] == source.value).all()


@pytest.mark.parametrize("source", list(Source))
def test_values_are_the_responses_own(source: Source) -> None:
    df = parse(source)
    raw = PAYLOADS[source]["hourly"]
    suffix = "_previous_day3" if source is Source.GFS_ARCHIVE else ""
    for variable in VARIABLES:
        expected = [float("nan") if v is None else float(v) for v in raw[variable + suffix]]
        assert df[variable].tolist() == pytest.approx(expected, nan_ok=True), variable


def test_era5_is_available_when_fetched() -> None:
    df = parse(Source.ERA5)
    assert df["run_start_utc"].isna().all()
    assert (df["available_at_utc"] == FETCHED).all()


def test_archive_rows_carry_their_run_and_the_assumed_delay() -> None:
    df = parse(Source.GFS_ARCHIVE)
    rows = df[["valid_utc", "run_start_utc", "available_at_utc"]].itertuples(index=False)
    for valid, run, available in rows:
        assert run == archived_run_start(valid.to_pydatetime())
        assert available == run + MAX_PUBLISH_DELAY


def test_live_rows_carry_the_metadata_run() -> None:
    df = parse(Source.GFS_LIVE)
    assert (df["run_start_utc"] == RUN.started_utc).all()
    assert (df["available_at_utc"] == RUN.available_utc).all()


def test_parse_live_run_reads_the_metadata() -> None:
    assert parse_live_run(META) == RUN


@pytest.mark.parametrize(
    "meta",
    [{}, {"last_run_initialisation_time": None, "last_run_availability_time": 1}],
    ids=["absent", "null"],
)
def test_metadata_without_run_times_is_refused(meta: dict[str, Any]) -> None:
    with pytest.raises(WeatherResponseError, match=r"^missing_run_time:"):
        parse_live_run(meta)


def test_live_parse_needs_its_run() -> None:
    with pytest.raises(ValueError, match="live rows need the run"):
        parse_hourly(query(Source.GFS_LIVE), PAYLOADS[Source.GFS_LIVE], fetched_utc=FETCHED)


def test_a_naive_fetch_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="naive datetime rejected"):
        parse_hourly(
            query(Source.ERA5),
            PAYLOADS[Source.ERA5],
            fetched_utc=datetime(2026, 11, 24, 3, 30),  # noqa: DTZ001
        )


def broken(source: Source, change: Callable[[dict[str, Any]], object]) -> dict[str, Any]:
    payload = copy.deepcopy(PAYLOADS[source])
    change(payload)
    return payload


def _drop_hour(p: dict[str, Any]) -> None:
    for values in p["hourly"].values():
        del values[5]


def _shift_latitude(p: dict[str, Any]) -> None:
    p["latitude"] += 0.3


def _shift_longitude(p: dict[str, Any]) -> None:
    p["longitude"] += 0.3


def _drop_variable(p: dict[str, Any]) -> None:
    del p["hourly"]["cloud_cover"]


def _drop_times(p: dict[str, Any]) -> None:
    del p["hourly"]["time"]


def _change_unit(p: dict[str, Any]) -> None:
    p["hourly_units"]["temperature_2m"] = "°F"


def _local_zone(p: dict[str, Any]) -> None:
    p["utc_offset_seconds"] = -25200


def _other_days(p: dict[str, Any]) -> None:
    p["hourly"]["time"] = [t.replace("2024-06-", "2024-07-") for t in p["hourly"]["time"]]


def _error(p: dict[str, Any]) -> None:
    p.clear()
    p.update({"error": True, "reason": "Parameter 'hourly' is invalid 1234.5"})


def _short_column(p: dict[str, Any]) -> None:
    p["hourly"]["temperature_2m"].pop()


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (_error, "error_payload"),
        (_local_zone, "not_utc"),
        (_drop_variable, "missing_variable"),
        (_drop_times, "missing_variable"),
        (_change_unit, "unit"),
        (_short_column, "column_length"),
        (_drop_hour, "hours"),
        (_other_days, "hours"),
        (_shift_latitude, "grid_too_far"),
        (_shift_longitude, "grid_too_far"),
    ],
    ids=lambda x: x if isinstance(x, str) else x.__name__,
)
def test_a_bad_response_is_refused_by_rule(
    change: Callable[[dict[str, Any]], None], rule: str
) -> None:
    with pytest.raises(WeatherResponseError, match=rf"^{rule}:"):
        parse(Source.ERA5, broken(Source.ERA5, change))


def test_a_point_just_inside_the_limit_is_kept() -> None:
    payload = broken(Source.ERA5, lambda p: p.update(latitude=33.40314 + 0.2499))
    assert len(parse(Source.ERA5, payload)) == 48


def test_the_archive_columns_are_checked_by_their_suffixed_names() -> None:
    payload = broken(Source.GFS_ARCHIVE, lambda p: p["hourly"].pop("precipitation_previous_day3"))
    with pytest.raises(WeatherResponseError, match=r"^missing_variable: precipitation_previous"):
        parse(Source.GFS_ARCHIVE, payload)


def test_a_refusal_is_reportable_and_never_quotes_the_response() -> None:
    with pytest.raises(WeatherResponseError) as caught:
        parse(Source.ERA5, broken(Source.ERA5, _error))
    assert isinstance(caught.value, ReportableError)
    assert "1234.5" not in str(caught.value)
    assert "invalid" not in str(caught.value)


def test_a_live_run_published_after_the_fetch_is_refused() -> None:
    future = LiveRun(started_utc=FETCHED, available_utc=FETCHED + timedelta(minutes=1))
    with pytest.raises(WeatherResponseError, match=r"^run_from_the_future:"):
        parse_hourly(
            query(Source.GFS_LIVE),
            PAYLOADS[Source.GFS_LIVE],
            fetched_utc=FETCHED,
            live_run=future,
        )


def client_for(
    routes: dict[str, list[dict[str, Any]]],
) -> tuple[httpx.Client, list[httpx.Request]]:
    """A fake Open-Meteo: each URL plays its JSON bodies in order, then answers 404."""
    seen: list[httpx.Request] = []
    queues = {url: list(bodies) for url, bodies in routes.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url.copy_with(query=None))
        if not queues.get(url):
            return httpx.Response(404)
        return httpx.Response(200, json=queues[url].pop(0))

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def _url(request: httpx.Request) -> str:
    return str(request.url.copy_with(query=None))


def test_fetch_hourly_sends_the_query_and_stamps_the_clock() -> None:
    client, seen = client_for({URLS[Source.ERA5]: [PAYLOADS[Source.ERA5]]})
    df = fetch_hourly(client, query(Source.ERA5), now=lambda: FETCHED, backoff_s=0)
    assert [_url(r) for r in seen] == [URLS[Source.ERA5]]
    assert dict(parse_qsl(seen[0].url.query.decode())) == query(Source.ERA5).params()
    assert (df["available_at_utc"] == FETCHED).all()


def test_fetch_hourly_refuses_the_live_source() -> None:
    client, seen = client_for({})
    with pytest.raises(ValueError, match="use fetch_live"):
        fetch_hourly(client, query(Source.GFS_LIVE), now=lambda: FETCHED)
    assert seen == []


def test_fetch_hourly_passes_on_a_failed_request() -> None:
    client, _ = client_for({})
    with pytest.raises(FetchError, match="404"):
        fetch_hourly(client, query(Source.ERA5), now=lambda: FETCHED, backoff_s=0)


def test_fetch_live_reads_the_run_before_and_after_the_data() -> None:
    client, seen = client_for(
        {GFS_META_URL: [META, META], URLS[Source.GFS_LIVE]: [PAYLOADS[Source.GFS_LIVE]]}
    )
    df = fetch_live(client, query(Source.GFS_LIVE), now=lambda: FETCHED, backoff_s=0)
    assert [_url(r) for r in seen] == [GFS_META_URL, URLS[Source.GFS_LIVE], GFS_META_URL]
    assert dict(parse_qsl(seen[1].url.query.decode())) == query(Source.GFS_LIVE).params()
    assert (df["run_start_utc"] == RUN.started_utc).all()


def test_fetch_live_refuses_a_run_that_changed_mid_fetch() -> None:
    newer = dict(META, last_run_initialisation_time=META["last_run_initialisation_time"] + 21600)
    client, _ = client_for(
        {GFS_META_URL: [META, newer], URLS[Source.GFS_LIVE]: [PAYLOADS[Source.GFS_LIVE]]}
    )
    with pytest.raises(WeatherResponseError, match=r"^run_changed:"):
        fetch_live(client, query(Source.GFS_LIVE), now=lambda: FETCHED, backoff_s=0)


def test_fetch_live_refuses_another_source() -> None:
    client, seen = client_for({})
    with pytest.raises(ValueError, match="takes a GFS_LIVE query"):
        fetch_live(client, query(Source.ERA5), now=lambda: FETCHED)
    assert seen == []
