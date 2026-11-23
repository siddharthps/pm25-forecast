"""Time rules that the first mutation run showed were untested (#42).

- `issue_time_utc` with its zone dropped survived, because this PC and WSL run on Chicago time:
  the naive 06:00 was read in the process's zone, which happened to be the issue zone. The cloud
  runner's zone is UTC. These tests move the process to other zones (POSIX only, so WSL and CI).
- `_require_aware` with `or` turned into `and` survived: a tzinfo whose offset is None counts as
  naive in Python, and must be refused like any naive datetime.
"""

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import override
from zoneinfo import ZoneInfo

import pytest

from airwatch.timeutil import ensure_utc, issue_time_utc, to_local


@contextmanager
def process_zone(name: str) -> Iterator[None]:
    tzset: Callable[[], None] | None = getattr(time, "tzset", None)
    if tzset is None:
        pytest.skip("time.tzset is POSIX only (runs in WSL and CI)")
    before = os.environ.get("TZ")
    os.environ["TZ"] = name
    tzset()
    try:
        yield
    finally:
        if before is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = before
        tzset()


@pytest.mark.parametrize("zone", ["UTC", "Asia/Kolkata", "America/Phoenix"])
@pytest.mark.parametrize(
    ("target", "expected"),
    [
        pytest.param(date(2025, 1, 16), datetime(2025, 1, 15, 12, tzinfo=UTC), id="CST"),
        pytest.param(date(2025, 7, 5), datetime(2025, 7, 4, 11, tzinfo=UTC), id="CDT"),
    ],
)
def test_the_issue_time_ignores_the_process_zone(
    zone: str, target: date, expected: datetime
) -> None:
    with process_zone(zone):
        local_noon = datetime.fromtimestamp(43_200)  # noqa: DTZ006
        assert local_noon.hour == datetime.fromtimestamp(43_200, ZoneInfo(zone)).hour
        assert issue_time_utc(target) == expected


class NoOffset(tzinfo):
    @override
    def utcoffset(self, dt: datetime | None) -> timedelta | None:
        return None

    @override
    def dst(self, dt: datetime | None) -> timedelta | None:
        return None

    @override
    def tzname(self, dt: datetime | None) -> str | None:
        return None


@pytest.mark.parametrize("convert", [ensure_utc, lambda dt: to_local(dt, ZoneInfo("UTC"))])
def test_a_zone_without_an_offset_counts_as_naive(convert: Callable[[datetime], datetime]) -> None:
    with pytest.raises(ValueError, match="naive"):
        convert(datetime(2026, 11, 22, 12, tzinfo=NoOffset()))
