"""The feature rows (#21, T15; D-062): every feature against a hand-worked value."""

import math
from datetime import date, timedelta
from itertools import combinations

import numpy as np
import pandas as pd
import pytest

from airwatch.features.build import (
    FEATURE_COLUMNS,
    KEY_COLUMNS,
    WEATHER_SOURCES_AS_PUBLISHED,
    MixedSourcesError,
    build_features,
    known_at,
)
from airwatch.observations.schema import concat_hourly, empty_hourly
from airwatch.timeutil import issue_time_utc
from tests.unit.features.helpers import (
    ISSUE_AT,
    PHOENIX,
    SITE_A,
    SITE_B,
    SITES,
    TARGET,
    pm_day,
    pm_history,
    weather_day,
)

D = TARGET - timedelta(days=1)


def day(k: int) -> date:
    """D-k, where D is the issue day."""
    return D - timedelta(days=k)


def no_weather() -> pd.DataFrame:
    return weather_day(TARGET).iloc[0:0]


def row(
    pm: pd.DataFrame,
    weather: pd.DataFrame | None = None,
    *,
    site: str = SITE_A,
    target: date = TARGET,
) -> pd.Series:
    out = build_features(
        pm, no_weather() if weather is None else weather, [target], sites=SITES, tz=PHOENIX
    )
    picked = out[out["site_id"] == site]
    assert len(picked) == 1
    return picked.iloc[0]


def test_twenty_one_named_features_once_each() -> None:
    assert len(FEATURE_COLUMNS) == 21
    assert len(set(FEATURE_COLUMNS)) == 21
    assert not set(FEATURE_COLUMNS) & set(KEY_COLUMNS)


def test_one_row_per_site_and_target_day_even_with_no_data() -> None:
    targets = [TARGET, TARGET + timedelta(days=1)]
    out = build_features(empty_hourly(), no_weather(), targets, sites=SITES, tz=PHOENIX)
    assert list(out.columns) == [*KEY_COLUMNS, *FEATURE_COLUMNS]
    assert sorted(zip(out["site_id"], out["target_day"], strict=True)) == sorted(
        (s, t) for s in SITES for t in targets
    )
    assert set(out["issue_at_utc"]) == {issue_time_utc(t) for t in targets}
    assert out["pm_mean_d1"].isna().all()
    assert (out["pm_hours_d1"] == 0).all()


def test_daily_means_of_the_last_three_days() -> None:
    pm = concat_hourly([pm_day(day(1), 10.0), pm_day(day(2), 20.0), pm_day(day(3), 30.0)])
    r = row(pm)
    assert (r["pm_mean_d1"], r["pm_mean_d2"], r["pm_mean_d3"]) == (10.0, 20.0, 30.0)


def test_co_located_instruments_are_averaged_per_hour_first() -> None:
    pm = concat_hourly(
        [
            pm_day(day(1), 10.0, poc=1),
            pm_day(day(1), 20.0, poc=3, hours=12),
        ]
    )
    r = row(pm)
    assert r["pm_mean_d1"] == pytest.approx((12 * 15.0 + 12 * 10.0) / 24)
    assert r["pm_hours_d1"] == 24


@pytest.mark.parametrize(("hours", "valid"), [(17, False), (18, True)])
def test_a_day_needs_eighteen_hours(hours: int, valid: bool) -> None:
    r = row(pm_day(day(1), 5.0, hours=hours))
    assert r["pm_hours_d1"] == hours
    assert (not math.isnan(r["pm_mean_d1"])) is valid
    assert (not math.isnan(r["pm_max_d1"])) is valid
    if valid:
        assert r["pm_mean_d1"] == 5.0
        assert r["pm_max_d1"] == 5.0


def test_d1_maximum_is_the_highest_hour() -> None:
    values = [4.0] * 24
    values[19] = 61.5
    assert row(pm_day(day(1), values))["pm_max_d1"] == 61.5


@pytest.mark.parametrize(("valid_days", "expected"), [(3, None), (4, (1 + 2 + 3 + 7) / 4)])
def test_seven_day_mean_needs_four_valid_days(valid_days: int, expected: float | None) -> None:
    chosen = [1, 2, 3, 7][:valid_days]
    frames = [pm_day(day(k), float(k)) for k in chosen]
    frames += [pm_day(day(k), 99.0, hours=10) for k in range(1, 8) if k not in chosen]
    frames.append(pm_day(day(8), 500.0))
    r = row(concat_hourly(frames))
    if expected is None:
        assert math.isnan(r["pm_mean_7d"])
    else:
        assert r["pm_mean_7d"] == pytest.approx(expected)


def test_hours_of_the_issue_day_are_never_used() -> None:
    base = pm_day(day(1), 10.0, source="airnow")
    early = pm_day(D, 900.0, hours=4, source="airnow")
    assert (early["available_at_utc"] < pd.Timestamp(ISSUE_AT)).all()
    assert row(concat_hourly([base, early])).equals(row(base))


def test_airnow_published_at_the_issue_instant_is_not_known_yet() -> None:
    on_time = pm_day(day(1), 10.0, source="airnow")
    at_issue = on_time.assign(available_at_utc=pd.Timestamp(ISSUE_AT))
    assert row(on_time)["pm_mean_d1"] == 10.0
    assert math.isnan(row(at_issue)["pm_mean_d1"])


def test_aqs_counts_by_measurement_time_though_changed_months_later() -> None:
    late = pm_day(day(1), 10.0, available_at=ISSUE_AT + timedelta(days=150))
    assert row(late)["pm_mean_d1"] == 10.0


def _with(values: dict[str, list[float] | float], source: str = "era5") -> pd.Series:
    return row(pm_day(day(1), 10.0), weather_day(TARGET, values=values, source=source))


def test_temperature_mean_and_max_over_the_target_day() -> None:
    temps = [10.0] * 25
    temps[15] = 34.0
    temps[24] = 500.0
    r = _with({"temperature_2m": temps})
    assert r["temp_mean"] == pytest.approx((23 * 10.0 + 34.0) / 24)
    assert r["temp_max"] == 34.0


def test_sums_use_the_stamps_after_midnight_through_the_next_midnight() -> None:
    rain = [0.0] * 25
    rain[0] = 7.0
    rain[24] = 2.0
    rain[10] = 1.5
    sun = [100.0] * 25
    sun[0] = 9999.0
    r = _with({"precipitation": rain, "shortwave_radiation": sun})
    assert r["precip_total"] == pytest.approx(3.5)
    assert r["shortwave_mean"] == pytest.approx(100.0)


@pytest.mark.parametrize(
    ("direction", "u", "v"), [(0.0, 0.0, -10.0), (90.0, -10.0, 0.0), (270.0, 10.0, 0.0)]
)
def test_wind_parts_point_where_the_wind_blows_to(direction: float, u: float, v: float) -> None:
    r = _with({"wind_speed_10m": 10.0, "wind_direction_10m": direction})
    assert r["wind_speed_mean"] == pytest.approx(10.0)
    assert r["wind_u_mean"] == pytest.approx(u, abs=1e-9)
    assert r["wind_v_mean"] == pytest.approx(v, abs=1e-9)


@pytest.mark.parametrize(("raw", "clipped"), [(-1.0, 0.0), (101.0, 100.0), (55.0, 55.0)])
def test_cloud_cover_is_clipped_to_its_range(raw: float, clipped: float) -> None:
    assert _with({"cloud_cover": raw})["cloud_mean"] == clipped


def test_humidity_and_pressure_means() -> None:
    r = _with({"relative_humidity_2m": 33.0, "surface_pressure": 968.5})
    assert (r["rh_mean"], r["pressure_mean"]) == (33.0, 968.5)


def test_a_weather_mean_needs_eighteen_hours_and_a_total_every_hour() -> None:
    full = weather_day(TARGET)
    keep_18 = full.iloc[[*range(18), 24]]
    r = row(pm_day(day(1), 10.0), keep_18)
    assert r["temp_mean"] == 12.0
    assert math.isnan(r["precip_total"])
    r = row(pm_day(day(1), 10.0), full.iloc[[*range(17), 24]])
    assert math.isnan(r["temp_mean"])
    assert math.isnan(r["shortwave_mean"])


def test_forecast_weather_counts_only_if_published_before_issue() -> None:
    known = weather_day(TARGET, source="gfs_archive", values={"temperature_2m": 12.0})
    late = weather_day(
        TARGET,
        source="gfs_archive",
        values={"temperature_2m": 40.0},
        run_start=ISSUE_AT,
        available_at=ISSUE_AT,
    )
    assert _with({}, source="gfs_archive")["temp_mean"] == 12.0
    assert row(pm_day(day(1), 10.0), pd.concat([known, late]))["temp_mean"] == 12.0
    assert math.isnan(row(pm_day(day(1), 10.0), late)["temp_mean"])


def test_the_newest_known_run_wins_each_hour() -> None:
    older = weather_day(
        TARGET,
        source="gfs_live",
        values={"temperature_2m": 5.0},
        run_start=ISSUE_AT - timedelta(hours=18),
        available_at=ISSUE_AT - timedelta(hours=12),
    )
    newer = weather_day(
        TARGET,
        source="gfs_live",
        values={"temperature_2m": 9.0},
        run_start=ISSUE_AT - timedelta(hours=12),
        available_at=ISSUE_AT - timedelta(hours=6),
    )
    assert row(pm_day(day(1), 10.0), pd.concat([newer, older]))["temp_mean"] == 9.0


def test_era5_counts_though_fetched_after_issue() -> None:
    fetched_late = weather_day(TARGET, available_at=ISSUE_AT + timedelta(days=300))
    assert row(pm_day(day(1), 10.0), fetched_late)["temp_mean"] == 12.0


def test_weather_sources_named_as_published() -> None:
    assert frozenset({"gfs_archive", "gfs_live"}) == WEATHER_SOURCES_AS_PUBLISHED


@pytest.mark.parametrize(
    ("target", "fireworks", "weekday"),
    [
        (date(2026, 7, 4), 1, 5),
        (date(2026, 7, 5), 0, 6),
        (date(2027, 1, 1), 1, 4),
        (date(2026, 12, 31), 0, 3),
    ],
)
def test_calendar_of_the_target_day(target: date, fireworks: int, weekday: int) -> None:
    r = row(empty_hourly(), target=target)
    assert r["fireworks_day"] == fireworks
    assert r["day_of_week"] == weekday


def test_day_of_year_on_the_unit_circle() -> None:
    jan1 = row(empty_hourly(), target=date(2026, 1, 1))
    assert (jan1["doy_sin"], jan1["doy_cos"]) == (pytest.approx(0.0), pytest.approx(1.0))
    jul2 = row(empty_hourly(), target=date(2026, 7, 2))
    assert jul2["doy_cos"] == pytest.approx(math.cos(2 * math.pi * 182 / 365.25))
    assert jul2["doy_sin"] ** 2 + jul2["doy_cos"] ** 2 == pytest.approx(1.0)


def test_monitor_is_a_category_naming_the_site() -> None:
    out = build_features(empty_hourly(), no_weather(), [TARGET], sites=SITES, tz=PHOENIX)
    assert isinstance(out["monitor"].dtype, pd.CategoricalDtype)
    assert list(out["monitor"].astype(str)) == list(out["site_id"])


def test_training_and_serving_inputs_give_the_same_row() -> None:
    def level(site: str, d: date) -> float:
        return 3.0 + (d.toordinal() % 5) + (site == SITE_B)

    stand_in = row(pm_history(TARGET, level), weather_day(TARGET))
    live_pm = pm_history(TARGET, level, source="airnow")
    live = row(live_pm, weather_day(TARGET, source="gfs_live"))
    assert stand_in[list(FEATURE_COLUMNS)].equals(live[list(FEATURE_COLUMNS)])


def test_no_two_features_are_equal_or_rescaled() -> None:
    rng = np.random.default_rng(20261125)
    targets = [date(2025, 1, 1) + timedelta(days=i) for i in range(0, 365, 7)]
    first = targets[0] - timedelta(days=9)
    days = [first + timedelta(days=i) for i in range((targets[-1] - first).days + 1)]
    pm = concat_hourly(
        [
            pm_day(d, list(rng.gamma(2.0, 5.0, 24)), site=s, hours=int(rng.integers(15, 25)))
            for s in SITES
            for d in days
        ]
    )
    weather = pd.concat(
        [
            weather_day(
                t,
                site=s,
                values={
                    v: list(rng.uniform(0, 100, 25))
                    for v in (
                        "temperature_2m",
                        "relative_humidity_2m",
                        "wind_speed_10m",
                        "precipitation",
                        "surface_pressure",
                        "cloud_cover",
                        "shortwave_radiation",
                    )
                }
                | {"wind_direction_10m": list(rng.uniform(0, 360, 25))},
            )
            for s in SITES
            for t in targets
        ]
    )
    out = build_features(pm, weather, targets, sites=SITES, tz=PHOENIX)
    numeric = out[[c for c in FEATURE_COLUMNS if c != "monitor"]].astype(float)
    for a, b in combinations(numeric.columns, 2):
        both = numeric[[a, b]].dropna()
        assert len(both) > 20, (a, b)
        assert not both[a].equals(both[b]), (a, b)
        if both[a].std() > 0 and both[b].std() > 0:
            assert abs(np.corrcoef(both[a], both[b])[0, 1]) < 1 - 1e-9, (a, b)


def test_an_input_mixing_sources_is_refused() -> None:
    mixed_pm = concat_hourly([pm_day(day(1), 10.0), pm_day(day(2), 10.0, source="airnow")])
    with pytest.raises(MixedSourcesError, match=r"^PM2\.5: 2 sources"):
        row(mixed_pm)
    mixed_weather = pd.concat([weather_day(TARGET), weather_day(TARGET, source="gfs_live")])
    with pytest.raises(MixedSourcesError, match=r"^weather: 2 sources"):
        row(pm_day(day(1), 10.0), mixed_weather)


def test_known_at_refuses_naive_times() -> None:
    naive = pm_day(day(1), 10.0)
    naive["available_at_utc"] = naive["available_at_utc"].dt.tz_localize(None)
    with pytest.raises(ValueError, match=r"^available_at_utc must be timezone-aware UTC$"):
        known_at(naive, ISSUE_AT, frozenset({"aqs"}))


def test_the_first_hour_of_d7_counts() -> None:
    frames = [pm_day(day(k), 8.0) for k in range(1, 4)]
    frames.append(pm_day(day(7), 20.0, hours=18))
    assert row(concat_hourly(frames))["pm_mean_7d"] == pytest.approx((3 * 8.0 + 20.0) / 4)


@pytest.mark.parametrize(("hours", "valid"), [(17, False), (18, True)])
def test_the_temperature_maximum_needs_eighteen_hours(hours: int, valid: bool) -> None:
    temps = [10.0] * 25
    temps[0] = 30.0
    weather = weather_day(TARGET, values={"temperature_2m": temps}).iloc[[*range(hours), 24]]
    r = row(pm_day(day(1), 10.0), weather)
    assert (r["temp_max"] == 30.0) if valid else math.isnan(r["temp_max"])


def test_no_target_days_still_gives_every_column_and_monitor() -> None:
    out = build_features(empty_hourly(), no_weather(), [], sites=SITES, tz=PHOENIX)
    assert len(out) == 0
    assert list(out.columns) == [*KEY_COLUMNS, *FEATURE_COLUMNS]
    assert list(out["monitor"].cat.categories) == sorted(SITES)
