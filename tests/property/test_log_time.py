"""A log line's time is the UTC instant, whatever the local zone and its DST (#52).

The reference is built from the UTC calendar fields directly, not by the formatter's own route.
"""

import logging
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from airwatch import logutil

ZONES = [ZoneInfo(z) for z in ("America/Chicago", "America/Phoenix", "Asia/Kolkata", "UTC")]
LO = datetime(2009, 1, 1)  # noqa: DTZ001
HI = datetime(2030, 12, 31)  # noqa: DTZ001
instants = st.datetimes(min_value=LO, max_value=HI, timezones=st.just(UTC)).map(
    lambda dt: dt.replace(microsecond=dt.microsecond // 1000 * 1000)
)


def _reference(utc: datetime) -> str:
    return (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}T"
        f"{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}.{utc.microsecond // 1000:03d}Z"
    )


@given(utc=instants, zone=st.sampled_from(ZONES))
@example(utc=datetime(2026, 11, 1, 6, 59, 59, 999_000, tzinfo=UTC), zone=ZONES[0])
@example(utc=datetime(2026, 11, 1, 7, 0, tzinfo=UTC), zone=ZONES[0])
@example(utc=datetime(2026, 3, 8, 8, 0, tzinfo=UTC), zone=ZONES[0])
def test_the_line_shows_the_utc_instant_in_any_local_zone(utc: datetime, zone: ZoneInfo) -> None:
    def local_clock(t: float | None) -> time.struct_time:
        return datetime.fromtimestamp(time.time() if t is None else t, zone).timetuple()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(logging.Formatter, "converter", staticmethod(local_clock))
        record = logging.LogRecord("airwatch.x", logging.INFO, __file__, 1, "m", None, None)
        record.created = utc.timestamp()
        assert logutil.formatter().format(record) == f"{_reference(utc)} m"
