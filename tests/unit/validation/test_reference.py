"""Validation against reference data, T12b (#20; D-054): AQS's monitor records and AirNow's
site list. Each rule catches a planted bad record; without a reference none of them runs.

- **wrong entity:** a listed site that AQS places outside the city's CBSA, or doesn't list at
  all -> hard;
- **key reuse:** a site whose AQS, AirNow and our own coordinates differ by more than 1 km ->
  warn; AQS's current instrument differs from `AIRNOW_METHOD` -> warn;
- **dates:** an AQS hour outside its instrument's open period -> warn, excluded.
"""

from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pandas as pd
import pytest

from airwatch.observations.schema import POC_NOT_GIVEN
from airwatch.observations.sites import SITE_COORDS
from airwatch.validation.checks import Severity, ValidationResult, Window, run_checks
from airwatch.validation.reference import (
    AIRNOW_SITES_URL,
    MAX_SITE_OFFSET_KM,
    Monitor,
    Reference,
    distance_km,
    fetch_reference,
    parse_airnow_sites,
    parse_monitors,
)
from tests.unit.validation.helpers import SITE_A, SITE_B, START, concat, frame, varying

PHOENIX = ZoneInfo("America/Phoenix")
DAY = Window(START, START + timedelta(days=1))
LATER = START + timedelta(days=30)
CBSA = "38060"


def monitor(  # noqa: PLR0913  (each argument is one field of the record)
    site: str = SITE_A,
    poc: int = 1,
    *,
    opened: date = date(2010, 1, 1),
    closed: date | None = None,
    coords: tuple[float, float] | None = None,
    cbsa: str | None = CBSA,
    method: str | None = "182",
) -> Monitor:
    lat, lon = coords or SITE_COORDS[site]
    return Monitor(site, poc, opened, closed, lat, lon, cbsa, method)


def reference(*monitors: Monitor, airnow: dict[str, Any] | None = None) -> Reference:
    coords = (
        airnow if airnow is not None else {m.site_id: (SITE_COORDS[m.site_id],) for m in monitors}
    )
    return Reference(monitors=tuple(monitors), airnow_coords=coords, city_cbsa=CBSA)


def check(
    df: pd.DataFrame, ref: Reference | None, *, sites: tuple[str, ...] = (SITE_A,)
) -> ValidationResult:
    return run_checks(df, window=DAY, tz=PHOENIX, sites=sites, now=LATER, reference=ref)


def test_the_site_tolerance_is_one_kilometre() -> None:
    assert MAX_SITE_OFFSET_KM == 1.0


def test_distance_is_great_circle_kilometres() -> None:
    assert distance_km((33.0, -112.0), (33.0, -112.0)) == 0.0
    assert distance_km((33.0, -112.0), (34.0, -112.0)) == pytest.approx(111.19, abs=0.01)


def test_a_clean_site_passes_every_reference_rule_at_zero() -> None:
    result = check(frame(varying(24), method="182"), reference(monitor()))
    for rule in ("site_outside_city", "site_moved", "airnow_method_stale", "outside_active_period"):
        assert result.finding(rule).count == 0, rule
    assert result.passed


def test_without_a_reference_the_reference_rules_do_not_run() -> None:
    result = check(frame(varying(24)), None)
    for rule in ("site_outside_city", "site_moved", "airnow_method_stale", "outside_active_period"):
        with pytest.raises(KeyError):
            result.finding(rule)


def test_a_site_outside_the_city_cbsa_is_a_hard_failure() -> None:
    result = check(frame(varying(24), method="182"), reference(monitor(cbsa="31080")))
    f = result.finding("site_outside_city")
    assert (f.problem_class, f.severity, f.count) == ("wrong entity", Severity.HARD, 1)
    assert f.items == ({"site_id": SITE_A, "reason": "cbsa 31080"},)
    assert not result.passed


def test_a_site_aqs_does_not_list_is_a_hard_failure() -> None:
    result = check(frame(varying(24), method="182"), reference(monitor(SITE_B)))
    assert result.finding("site_outside_city").items == (
        {"site_id": SITE_A, "reason": "no_aqs_record"},
    )


def test_a_monitor_with_no_cbsa_is_outside_the_city() -> None:
    result = check(frame(varying(24), method="182"), reference(monitor(cbsa=None)))
    assert result.finding("site_outside_city").items == (
        {"site_id": SITE_A, "reason": "cbsa none"},
    )


@pytest.mark.parametrize(("north_km", "moved"), [(0.9, False), (1.2, True)])
def test_aqs_coordinates_away_from_ours_mean_the_site_moved(north_km: float, moved: bool) -> None:
    lat, lon = SITE_COORDS[SITE_A]
    shifted = (lat + north_km / 111.19, lon)
    result = check(frame(varying(24), method="182"), reference(monitor(coords=shifted)))
    f = result.finding("site_moved")
    assert (f.problem_class, f.severity, f.count) == ("key reuse", Severity.WARN, int(moved))
    if moved:
        assert f.items == ({"site_id": SITE_A, "km": 1.2},)
    assert result.passed


def test_airnow_coordinates_away_from_aqs_mean_the_site_moved() -> None:
    lat, lon = SITE_COORDS[SITE_A]
    airnow = {SITE_A: (SITE_COORDS[SITE_A], (lat, lon + 0.02))}
    result = check(frame(varying(24), method="182"), reference(monitor(), airnow=airnow))
    assert result.finding("site_moved").count == 1


def test_two_aqs_monitors_apart_mean_the_site_moved() -> None:
    lat, lon = SITE_COORDS[SITE_A]
    ref = reference(monitor(poc=1), monitor(poc=3, coords=(lat - 0.02, lon)))
    assert check(frame(varying(24), method="182"), ref).finding("site_moved").count == 1


def test_a_site_missing_from_airnows_list_is_judged_on_the_rest() -> None:
    result = check(frame(varying(24), method="182"), reference(monitor(), airnow={}))
    assert result.finding("site_moved").count == 0


def test_aqs_current_instrument_differing_from_the_list_is_stale() -> None:
    result = check(frame(varying(24), method="170"), reference(monitor(method="170")))
    f = result.finding("airnow_method_stale")
    assert (f.problem_class, f.severity, f.count) == ("key reuse", Severity.WARN, 1)
    assert f.items == ({"site_id": SITE_A, "listed": "182", "aqs": "170"},)
    assert result.passed


def test_closed_monitors_and_filter_methods_do_not_count_as_current() -> None:
    ref = reference(
        monitor(poc=1, method="170", closed=date(2014, 12, 31)),
        monitor(poc=2, method="145"),
        monitor(poc=3, method="182"),
    )
    assert (
        check(frame(varying(24), method="182", poc=3), ref).finding("airnow_method_stale").count
        == 0
    )


def test_a_monitor_closing_after_the_run_is_still_current() -> None:
    ref = reference(monitor(method="182", closed=date(2030, 1, 1)))
    assert check(frame(varying(24), method="182"), ref).finding("airnow_method_stale").count == 0


def test_two_current_instruments_are_stale_until_the_list_says_which() -> None:
    ref = reference(monitor(poc=1, method="170"), monitor(poc=3, method="182"))
    f = check(frame(varying(24), method="182", poc=3), ref).finding("airnow_method_stale")
    assert f.items == ({"site_id": SITE_A, "listed": "182", "aqs": "170,182"},)


def test_an_aqs_hour_before_its_monitor_opened_is_excluded() -> None:
    opened = date(2024, 3, 1)
    early = frame(varying(3), method="182", start=START - timedelta(hours=3))
    df = concat(early, frame(varying(24), method="182"))
    result = check(df, reference(monitor(opened=opened)))
    f = result.finding("outside_active_period")
    assert (f.problem_class, f.severity) == ("dates", Severity.WARN)
    assert (f.count, f.excluded) == (3, 3)
    assert f.items == ({"site_id": SITE_A, "poc": 1, "hours": 3},)
    assert len(result.clean) == 24
    assert result.passed


def test_an_aqs_hour_on_its_close_day_counts_and_the_next_day_does_not() -> None:
    """START is 00:00 on 1 March in Phoenix: the close day runs to 2 March 07:00 UTC."""
    df = frame(varying(48), method="182")
    result = check(df, reference(monitor(closed=date(2024, 3, 1))))
    assert result.finding("outside_active_period").count == 24


def test_an_aqs_hour_from_a_poc_aqs_does_not_list_is_excluded() -> None:
    result = check(frame(varying(24), method="182", poc=5), reference(monitor(poc=1)))
    assert result.finding("outside_active_period").items == (
        {"site_id": SITE_A, "poc": 5, "hours": 24},
    )


def test_airnow_hours_are_not_judged_on_monitor_dates() -> None:
    df = frame(varying(24), method=None, poc=POC_NOT_GIVEN, source="airnow")
    result = check(df, reference(monitor(opened=date(2030, 1, 1))))
    assert result.finding("outside_active_period").count == 0


def test_reference_rules_never_judge_an_unlisted_site() -> None:
    ref = reference(monitor(cbsa="31080"), monitor(SITE_B))
    result = check(frame(varying(24), method="182", site=SITE_B), ref, sites=(SITE_B,))
    assert result.finding("site_outside_city").count == 0


AQS_ROW = {
    "state_code": "04",
    "county_code": "013",
    "site_number": "0019",
    "parameter_code": "88101",
    "poc": 3,
    "open_date": "2010-05-01",
    "close_date": None,
    "latitude": 33.48378,
    "longitude": -112.14256,
    "cbsa_code": "38060",
    "last_method_code": "182",
}


def test_aqs_monitor_rows_parse() -> None:
    other = {**AQS_ROW, "parameter_code": "88502"}
    closed = {**AQS_ROW, "poc": 1, "close_date": "2014-12-31", "last_method_code": "145"}
    assert parse_monitors([AQS_ROW, other, closed]) == (
        Monitor("040130019", 3, date(2010, 5, 1), None, 33.48378, -112.14256, "38060", "182"),
        Monitor(
            "040130019",
            1,
            date(2010, 5, 1),
            date(2014, 12, 31),
            33.48378,
            -112.14256,
            "38060",
            "145",
        ),
    )


def test_an_aqs_monitor_row_without_coordinates_is_refused() -> None:
    with pytest.raises(ValueError, match="latitude"):
        parse_monitors([{**AQS_ROW, "latitude": None}])


AIRNOW_TEXT = (
    "StationID|AQSID|FullAQSID|Parameter|MonitorType|SiteCode|SiteName|Status|AgencyID|"
    "AgencyName|EPARegion|Latitude|Longitude|Elevation|GMTOffset|CountryFIPS|CBSA_ID|"
    "CBSA_Name|StateAQSCode|StateAbbreviation|CountyAQSCode|CountyName\n"
    "040130019|040130019|840040130019|PM2.5|Permanent|0019|West Phoenix|Active|AZ1|M|R9|"
    "33.483799|-112.142601||-7.00|US|38060|Phoenix|04|AZ|013|Maricopa\n"
    "040130019|040130019|840040130019|OZONE|Permanent|0019|West Phoenix|Active|AZ1|M|R9|"
    "40.0|-100.0||-7.00|US|38060|Phoenix|04|AZ|013|Maricopa\n"
    "CC0010102|000010102|124CC0010102|PM2.5|Permanent|0102|Elsewhere|Active|X|X|X|"
    "50.0|-100.0||-6.00|CA||||||\n"
)


def test_airnow_site_rows_parse_pm25_only() -> None:
    assert parse_airnow_sites(AIRNOW_TEXT) == {
        "040130019": ((33.483799, -112.142601),),
        "000010102": ((50.0, -100.0),),
    }


def test_fetch_reference_reads_aqs_per_site_and_the_airnow_list() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.host == "aqs.epa.gov":
            assert request.url.params["param"] == "88101"
            assert request.url.params["site"] == "0019"
            return httpx.Response(200, json={"Header": [{"status": "Success"}], "Data": [AQS_ROW]})
        assert str(request.url) == AIRNOW_SITES_URL
        return httpx.Response(200, text=AIRNOW_TEXT)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        ref = fetch_reference(
            client, {"email": "e", "key": "k"}, (SITE_A,), city_cbsa=CBSA, backoff_s=0
        )
    assert seen == ["/data/api/monitors/bySite", "/airnow/today/Monitoring_Site_Locations_V2.dat"]
    assert ref.city_cbsa == CBSA
    assert [m.site_id for m in ref.monitors] == [SITE_A]
    assert ref.airnow_coords[SITE_A] == ((33.483799, -112.142601),)


def test_fetch_reference_refuses_an_aqs_error_status() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"Header": [{"status": "Failed"}], "Data": []})

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(RuntimeError, match="monitors"),
    ):
        fetch_reference(client, {}, (SITE_A,), city_cbsa=CBSA, backoff_s=0)
