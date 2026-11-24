"""Gaps mutmut found in the forecast's own rules (#112): each test kills a surviving mutant.

- Dates come from the issue zone, never the process zone: Kiritimati (UTC+14) is a day ahead of
  Chicago at the issue time, so a dropped zone shows (POSIX only: WSL, CI and mutmut).
- A day's mean uses its local day's hours only: the next day's first hour is excluded.
- The record and the run's files are byte-stable: sorted keys, two-space indent, one newline.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from airwatch.forecast import record as rec
from airwatch.forecast.run import _encode, day_means, latest_target_day, plan_for
from airwatch.validation.checks import Window, run_checks
from tests.process_zone import CAN_MOVE_ZONE, SKIP_REASON, process_zone
from tests.unit.forecast.fakes import ISSUE_AT, PHOENIX, SITES, TARGET
from tests.unit.validation.helpers import concat, frame, varying

EAST = "Pacific/Kiritimati"
zone_moves = pytest.mark.skipif(not CAN_MOVE_ZONE, reason=SKIP_REASON)


@zone_moves
def test_the_latest_target_day_ignores_the_process_zone() -> None:
    """05:00 Chicago on 11-21 is 01:00 on 11-22 in Kiritimati: still before 11-21's issue."""
    now = datetime(2026, 11, 21, 11, tzinfo=UTC)
    with process_zone(EAST):
        assert latest_target_day(now) == date(2026, 11, 21)


@zone_moves
def test_the_plans_issue_date_is_chicagos() -> None:
    with process_zone(EAST):
        assert plan_for(TARGET).issue_date == date(2026, 11, 20)


@zone_moves
def test_the_records_issue_date_is_chicagos() -> None:
    result = run_checks(
        frame([]),
        window=Window(ISSUE_AT - timedelta(days=1), ISSUE_AT),
        tz=PHOENIX,
        sites=(),
        now=ISSUE_AT,
    )
    with process_zone(EAST):
        built = rec.build_record(
            target_day=TARGET,
            issue_at_utc=ISSUE_AT,
            observed_day=TARGET - timedelta(days=2),
            generated_at_utc=ISSUE_AT,
            city_tz=str(PHOENIX),
            forecasts=[],
            no_forecast=[],
            validation=result,
            inputs={},
        )
    assert built["issue_date"] == "2026-11-20"


def test_the_next_days_first_hour_never_joins_a_days_mean_or_its_hour_count() -> None:
    """The mean is guarded twice (the window, then the local-date groups), but the hours of a
    site without a valid day come from the window alone: 17, never 18 with the next day's."""
    day = date(2024, 3, 1)
    start = datetime(2024, 3, 1, 7, tzinfo=UTC)
    full, short = SITES
    in_day = concat(
        frame(varying(24), site=full, start=start, method="182"),
        frame(varying(17), site=short, start=start, method="182"),
    )
    next_hours = concat(
        frame([900.0], site=full, start=start + timedelta(hours=24), method="182"),
        frame([900.0], site=short, start=start + timedelta(hours=24), method="182"),
    )
    valid, missing = day_means(concat(in_day, next_hours), day, PHOENIX, SITES)
    assert list(valid) == [full]
    assert valid[full][0] == pytest.approx(sum(varying(24)) / 24)
    assert valid[full][1] == 24
    assert missing == {short: 17}


@pytest.mark.parametrize("encode", [_encode, rec.encode], ids=["run", "record"])
def test_files_are_written_byte_stable(encode: Any) -> None:
    assert encode({"b": 1, "a": [2]}) == b'{\n  "a": [\n    2\n  ],\n  "b": 1\n}\n'
