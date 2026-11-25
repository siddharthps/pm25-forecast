"""The managed-compute ledger (#15, T8; D-040): one entry per Prefect run, summed per month."""

import json
import uuid
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from airwatch.monitoring.compute import (
    MONTHLY_ALERT_MIN,
    MONTHLY_FREE_MIN,
    PREFIX,
    TEARDOWN_PAD_MIN,
    billed_minutes,
    entry_key,
    record_run,
)
from tests.unit.forecast.fakes import MemoryStore

START = datetime(2026, 11, 21, 12, tzinfo=UTC)
RUN = "0f8c2a5e-6a3b-4b9e-9a51-3d2f0c7e1b44"


def test_the_alert_line_is_60_percent_of_the_free_minutes() -> None:
    assert (MONTHLY_FREE_MIN, MONTHLY_ALERT_MIN) == (500, 300)


@pytest.mark.parametrize(
    ("elapsed", "minutes"),
    [
        pytest.param(timedelta(0), 0 + TEARDOWN_PAD_MIN, id="no time at all"),
        pytest.param(timedelta(seconds=1), 1 + TEARDOWN_PAD_MIN, id="a second rounds up"),
        pytest.param(timedelta(minutes=2), 2 + TEARDOWN_PAD_MIN, id="whole minutes stay"),
        pytest.param(timedelta(minutes=2, seconds=1), 3 + TEARDOWN_PAD_MIN, id="then round up"),
    ],
)
def test_minutes_round_up_from_the_scheduled_start_plus_teardown(
    elapsed: timedelta, minutes: int
) -> None:
    assert billed_minutes(START, START + elapsed) == minutes


def test_a_clock_behind_the_scheduled_start_counts_no_negative_time() -> None:
    assert billed_minutes(START, START - timedelta(minutes=5)) == TEARDOWN_PAD_MIN


def test_naive_times_are_refused() -> None:
    with pytest.raises(ValueError, match="naive"):
        billed_minutes(START.replace(tzinfo=None), START)


def test_entries_are_filed_by_utc_month() -> None:
    late_chicago = datetime(2026, 11, 30, 19, tzinfo=ZoneInfo("America/Chicago"))
    assert entry_key(RUN, late_chicago) == f"{PREFIX}month=2026-12/run={RUN}.json"


@pytest.mark.parametrize("bad", ["", "../records/x", "not a uuid", RUN.upper(), RUN + "/"])
def test_a_run_id_must_be_a_uuid(bad: str) -> None:
    with pytest.raises(ValueError, match="run id"):
        entry_key(bad, START)


def test_a_run_is_recorded_and_the_month_summed() -> None:
    store = MemoryStore()
    record_run(store, str(uuid.UUID(int=1)), START, START + timedelta(minutes=3))
    usage = record_run(store, RUN, START, START + timedelta(minutes=1))
    assert usage.minutes == 1 + TEARDOWN_PAD_MIN
    assert usage.month_total == (3 + TEARDOWN_PAD_MIN) + (1 + TEARDOWN_PAD_MIN)
    assert usage.over_alert is False
    entry = json.loads(store.get(entry_key(RUN, START + timedelta(minutes=1))) or b"{}")
    assert entry == {
        "run_id": RUN,
        "scheduled_start_utc": "2026-11-21T12:00:00+00:00",
        "finished_utc": "2026-11-21T12:01:00+00:00",
        "minutes": 1 + TEARDOWN_PAD_MIN,
    }


def test_other_months_are_not_counted() -> None:
    store = MemoryStore()
    october = datetime(2026, 10, 31, 23, tzinfo=UTC)
    record_run(store, str(uuid.UUID(int=1)), october, october + timedelta(minutes=10))
    assert record_run(store, RUN, START, START).month_total == TEARDOWN_PAD_MIN


def test_the_alert_flag_turns_on_above_the_line() -> None:
    store = MemoryStore()
    record_run(store, str(uuid.UUID(int=1)), START, START + timedelta(minutes=MONTHLY_ALERT_MIN))
    assert record_run(store, RUN, START, START).over_alert is True


@given(
    runs=st.lists(st.integers(0, 50), min_size=1, max_size=6),
    repeats=st.integers(1, 3),
)
def test_running_the_ledger_again_never_counts_a_run_twice(runs: list[int], repeats: int) -> None:
    store = MemoryStore()
    ids = [str(uuid.UUID(int=i + 1)) for i in range(len(runs))]
    for _ in range(repeats):
        for run_id, minutes in zip(ids, runs, strict=True):
            usage = record_run(store, run_id, START, START + timedelta(minutes=minutes))
    assert usage.month_total == sum(m + TEARDOWN_PAD_MIN for m in runs)
    assert len(store.list_keys(PREFIX)) == len(runs)


def test_a_retry_keeps_the_first_entrys_minutes() -> None:
    """Killed mutmut survivors (#112): a second filing of one run never replaces the first."""
    store = MemoryStore()
    first = record_run(store, RUN, START, START + timedelta(minutes=2))
    later = record_run(store, RUN, START, START + timedelta(minutes=9))
    assert later.minutes == first.minutes == 2 + TEARDOWN_PAD_MIN
    assert later.month_total == first.minutes


def test_a_lost_race_with_nothing_readable_keeps_its_own_minutes() -> None:
    class Refusing(MemoryStore):
        def create_if_absent(self, _key: str, _data: bytes) -> bool:
            return False

    usage = record_run(Refusing(), RUN, START, START + timedelta(minutes=4))
    assert usage.minutes == 4 + TEARDOWN_PAD_MIN


def test_exactly_the_alert_line_is_not_over_it() -> None:
    store = MemoryStore()
    usage = record_run(
        store, RUN, START, START + timedelta(minutes=MONTHLY_ALERT_MIN - TEARDOWN_PAD_MIN)
    )
    assert (usage.month_total, usage.over_alert) == (MONTHLY_ALERT_MIN, False)


def test_the_ledger_file_is_indented_json() -> None:
    store = MemoryStore()
    record_run(store, RUN, START, START + timedelta(minutes=1))
    raw = store.get(entry_key(RUN, START + timedelta(minutes=1)))
    assert raw is not None
    assert raw.startswith(b'{\n  "run_id": ') and raw.endswith(b"\n}\n")


class _NoOffset(tzinfo):
    """A zone whose offset is None: as unusable as no zone at all."""

    def utcoffset(self, _dt: datetime | None) -> None:
        return None

    def dst(self, _dt: datetime | None) -> None:
        return None

    def tzname(self, _dt: datetime | None) -> str:
        return "none"


def test_a_zone_without_an_offset_is_refused() -> None:
    with pytest.raises(ValueError, match="naive"):
        record_run(MemoryStore(), RUN, START.replace(tzinfo=_NoOffset()), START)
