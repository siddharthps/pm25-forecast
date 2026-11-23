"""The durable record's once-only write (#13, T6; D-034)."""

import json
from datetime import date

import pytest

from airwatch.forecast.record import (
    RecordUnreadableError,
    encode,
    record_key,
    report_key,
    write_once,
)
from tests.unit.forecast.fakes import MemoryStore

RECORD = {"forecast_date": "2026-11-21", "forecasts": []}


def test_keys_are_named_after_the_target_day() -> None:
    assert record_key(date(2026, 11, 21)) == "records/forecast_date=2026-11-21/forecast.json"
    assert report_key(date(2026, 11, 21)) == (
        "reports/validation/forecast_date=2026-11-21/validation.json"
    )


def test_the_first_write_creates_the_record() -> None:
    store = MemoryStore()
    assert write_once(store, RECORD) == (True, RECORD)
    assert json.loads(store.objects[record_key(date(2026, 11, 21))]) == RECORD


def test_an_existing_record_wins_and_is_returned() -> None:
    store = MemoryStore()
    theirs = RECORD | {"forecasts": [{"site_id": "040130019"}]}
    store.put(record_key(date(2026, 11, 21)), encode(theirs))
    assert write_once(store, RECORD) == (False, theirs)


class RefusesButEmpty(MemoryStore):
    def create_if_absent(self, key: str, data: bytes) -> bool:  # noqa: ARG002
        return False


def test_a_refused_write_with_nothing_to_read_fails_loudly() -> None:
    with pytest.raises(RecordUnreadableError, match="not readable"):
        write_once(RefusesButEmpty(), RECORD)
