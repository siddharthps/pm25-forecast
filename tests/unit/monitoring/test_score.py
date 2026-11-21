"""Daily scoring (#17, T10; D-013, D-042): each recorded day against its settled AirNow actuals.

- Day T is scored on the morning of T+2 (owner's choice), from a fresh download of all of T's
  hours, so the score doesn't depend on when the run happens.
- A monitor needs 18 valid hours for an actual; without one it's left out and counted.
- Each score is written once (create-only) and then reused: scoring is idempotent per date.
- A dry run computes and writes nothing; a failing day doesn't stop the others.
"""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from airwatch.forecast.record import record_key
from airwatch.monitoring import score as sc
from airwatch.timeutil import issue_time_utc
from tests.unit.forecast.fakes import PHOENIX, SITES, MemoryStore, observed_day

CHICAGO = ZoneInfo("America/Chicago")
DAY = date(2026, 11, 21)
READY = datetime(2026, 11, 23, 6, tzinfo=CHICAGO).astimezone(UTC)
SETTLED = READY - timedelta(hours=20)
FORECAST = {SITES[0]: 9.0, SITES[1]: 7.5}


def _record(day: date = DAY, forecasts: dict[str, float] | None = None) -> dict[str, Any]:
    chosen = FORECAST if forecasts is None else forecasts
    return {
        "forecast_date": day.isoformat(),
        "city_tz": str(PHOENIX),
        "forecasts": [
            {"site_id": s, "forecast_ug_m3": v, "n_hours": 24} for s, v in sorted(chosen.items())
        ],
        "no_forecast": [],
    }


def _store(*days: date) -> MemoryStore:
    store = MemoryStore()
    for day in days:
        store.put(record_key(day), json.dumps(_record(day)).encode())
    return store


def _actuals(hours: dict[str, int] | None = None, day: date = DAY) -> pd.DataFrame:
    return observed_day(hours, day=day, available_at=SETTLED)


class Fetch:
    """A fetch_day serving one frame per day, counting calls; a day can be made to fail."""

    def __init__(self, frames: dict[date, pd.DataFrame], fail: set[date] | None = None) -> None:
        self.frames = frames
        self.fail = fail or set()
        self.asked: list[date] = []

    def __call__(self, day: date) -> tuple[pd.DataFrame, dict[str, int]]:
        self.asked.append(day)
        if day in self.fail:
            raise ConnectionError("AirNow unreachable")
        return self.frames[day].copy(), {}


def _score(store: MemoryStore, fetch: Fetch, *, now: datetime = READY, write: bool = True) -> Any:
    return sc.score_due(fetch_day=fetch, private=store, sites=SITES, now=lambda: now, write=write)


def _reference_means(df: pd.DataFrame) -> dict[str, float]:
    """A plain mean of the raw hours: one instrument per site, so no per-hour averaging."""
    return {str(k): float(v) for k, v in df.groupby("site_id")["value_ug_m3"].mean().items()}


def test_day_t_is_due_from_the_t_plus_2_morning_run() -> None:
    assert sc.due_days(READY)[0] == DAY
    assert sc.due_days(READY - timedelta(seconds=1))[0] == DAY - timedelta(days=1)
    assert sc.score_ready_at(DAY) == READY == issue_time_utc(DAY + timedelta(days=3))


def test_a_week_of_days_is_due_newest_first() -> None:
    due = sc.due_days(READY)
    assert due == [DAY - timedelta(days=i) for i in range(sc.LOOKBACK_DAYS)]


def test_the_score_is_forecast_minus_the_settled_actual() -> None:
    store, df = _store(DAY), _actuals()
    [outcome] = [o for o in _score(store, Fetch({DAY: df})) if o.day == DAY]
    assert outcome.status == "scored"
    stored = json.loads(store.get(sc.score_key(DAY)) or b"")
    assert stored == outcome.score
    means = _reference_means(df)
    monitors = {m["site_id"]: m for m in stored["monitors"]}
    for site, forecast in FORECAST.items():
        assert monitors[site]["actual_ug_m3"] == pytest.approx(means[site])
        assert monitors[site]["error_ug_m3"] == pytest.approx(forecast - means[site])
        assert monitors[site]["abs_error_ug_m3"] == pytest.approx(abs(forecast - means[site]))
        assert monitors[site]["n_hours"] == 24
    errors = [FORECAST[s] - means[s] for s in FORECAST]
    assert stored["city"]["n_scored"] == 2
    assert stored["city"]["mae_ug_m3"] == pytest.approx(sum(abs(e) for e in errors) / 2)
    assert stored["city"]["bias_ug_m3"] == pytest.approx(sum(errors) / 2)
    assert stored["forecast_date"] == DAY.isoformat()
    assert stored["actual_source"] == "airnow"
    assert stored["scored_at_utc"] == READY.isoformat()


def test_a_monitor_under_18_hours_is_left_out_and_counted() -> None:
    store = _store(DAY)
    df = _actuals({SITES[1]: 17})
    [outcome] = [o for o in _score(store, Fetch({DAY: df})) if o.day == DAY]
    assert [m["site_id"] for m in outcome.score["monitors"]] == [SITES[0]]
    assert outcome.score["no_actual"] == [{"site_id": SITES[1], "n_hours": 17}]
    assert outcome.score["city"]["n_scored"] == 1
    means = _reference_means(df)
    assert outcome.score["city"]["mae_ug_m3"] == pytest.approx(
        abs(FORECAST[SITES[0]] - means[SITES[0]])
    )


def test_18_hours_is_enough() -> None:
    store = _store(DAY)
    [outcome] = [o for o in _score(store, Fetch({DAY: _actuals({SITES[1]: 18})})) if o.day == DAY]
    assert outcome.score["city"]["n_scored"] == 2
    assert outcome.score["no_actual"] == []


def test_no_valid_actual_at_all_is_still_a_final_score() -> None:
    store = _store(DAY)
    df = _actuals({SITES[0]: 5, SITES[1]: 0})
    [outcome] = [o for o in _score(store, Fetch({DAY: df})) if o.day == DAY]
    assert outcome.status == "scored"
    assert outcome.score["city"] == {"n_scored": 0, "mae_ug_m3": None, "bias_ug_m3": None}
    assert {m["site_id"] for m in outcome.score["no_actual"]} == set(SITES)


def test_only_monitors_that_were_forecast_are_scored() -> None:
    store = MemoryStore()
    store.put(record_key(DAY), json.dumps(_record(forecasts={SITES[0]: 9.0})).encode())
    [outcome] = [o for o in _score(store, Fetch({DAY: _actuals()})) if o.day == DAY]
    assert [m["site_id"] for m in outcome.score["monitors"]] == [SITES[0]]
    assert outcome.score["no_actual"] == []


def test_a_day_without_a_record_has_nothing_to_score_and_fetches_nothing() -> None:
    fetch = Fetch({})
    outcomes = _score(MemoryStore(), fetch)
    assert {o.status for o in outcomes} == {"no_record"}
    assert fetch.asked == []


def test_a_scored_day_is_reused_never_refetched_or_rewritten() -> None:
    store = _store(DAY)
    _score(store, Fetch({DAY: _actuals()}))
    first = store.get(sc.score_key(DAY))
    fetch = Fetch({DAY: _actuals({SITES[0]: 20})})
    [again] = [o for o in _score(store, fetch, now=READY + timedelta(days=1)) if o.day == DAY]
    assert again.status == "already_scored"
    assert DAY not in fetch.asked
    assert store.get(sc.score_key(DAY)) == first


def test_a_racing_writers_score_wins() -> None:
    class Racing(MemoryStore):
        def create_if_absent(self, key: str, data: bytes) -> bool:
            if key.startswith(sc.SCORE_PREFIX):
                self.objects[key] = json.dumps({"winner": True}).encode()
                return False
            return super().create_if_absent(key, data)

    store = Racing()
    store.put(record_key(DAY), json.dumps(_record()).encode())
    [outcome] = [o for o in _score(store, Fetch({DAY: _actuals()})) if o.day == DAY]
    assert outcome.status == "already_scored"
    assert outcome.score == {"winner": True}


def test_a_dry_run_computes_and_writes_nothing() -> None:
    store = _store(DAY)
    before = dict(store.objects)
    [outcome] = [o for o in _score(store, Fetch({DAY: _actuals()}), write=False) if o.day == DAY]
    assert outcome.status == "dry_run"
    assert outcome.score["city"]["n_scored"] == 2
    assert store.objects == before


def test_one_failing_day_does_not_stop_the_others_and_fails_at_the_end() -> None:
    earlier = DAY - timedelta(days=1)
    store = _store(DAY, earlier)
    fetch = Fetch({earlier: _actuals(day=earlier)}, fail={DAY})
    with pytest.raises(sc.ScoringError, match=DAY.isoformat()) as caught:
        _score(store, fetch)
    assert store.get(sc.score_key(earlier)) is not None
    assert store.get(sc.score_key(DAY)) is None
    assert "ConnectionError" in str(caught.value)


def test_a_failed_validation_leaves_the_day_unscored_for_a_later_run() -> None:
    store = _store(DAY)
    df = _actuals()
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    with pytest.raises(sc.ScoringError, match=DAY.isoformat()):
        _score(store, Fetch({DAY: df}))
    assert store.get(sc.score_key(DAY)) is None


def test_a_day_not_yet_settled_is_refused() -> None:
    with pytest.raises(sc.NotSettledError):
        sc.score_day(
            DAY,
            fetch_day=Fetch({DAY: _actuals()}),
            private=_store(DAY),
            sites=SITES,
            now=READY - timedelta(minutes=1),
            write=True,
        )


def test_scoring_twice_writes_the_same_bytes() -> None:
    a, b = _store(DAY), _store(DAY)
    _score(a, Fetch({DAY: _actuals()}))
    _score(b, Fetch({DAY: _actuals()}))
    assert a.get(sc.score_key(DAY)) == b.get(sc.score_key(DAY))


def test_scores_live_under_reports_where_the_pipeline_may_write() -> None:
    assert sc.score_key(DAY) == "reports/scores/forecast_date=2026-11-21/score.json"
