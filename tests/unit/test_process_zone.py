"""The process-zone helper itself (#88): it moves the zone, puts it back, and is the only way in.

Asia/Kolkata (UTC+5:30) is neither this PC's zone nor UTC, so a helper that did nothing, or set
`TZ` without `tzset`, can't pass by accident.
"""

import os
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.process_zone import process_zone

TESTS = Path(__file__).resolve().parents[1]
NOON_UTC = 43_200


def _local_wall_clock(t: float) -> datetime:
    return datetime.fromtimestamp(t)  # noqa: DTZ006


def test_inside_it_the_process_reads_the_target_zone() -> None:
    with process_zone("Asia/Kolkata"):
        expected = datetime.fromtimestamp(NOON_UTC, ZoneInfo("Asia/Kolkata")).replace(tzinfo=None)
        assert _local_wall_clock(NOON_UTC) == expected
        assert expected.hour == 17 and expected.minute == 30


def test_afterwards_the_zone_and_tz_are_restored_even_when_the_body_raises() -> None:
    """The outer block makes TZ set; the inner one must restore it; the outer, the original."""
    original = (os.environ.get("TZ"), time.localtime(NOON_UTC)[:6])
    with process_zone("America/Phoenix"):
        phoenix = (os.environ.get("TZ"), time.localtime(NOON_UTC)[:6])
        with pytest.raises(RuntimeError), process_zone("Asia/Kolkata"):
            raise RuntimeError("the body failed")
        assert (os.environ.get("TZ"), time.localtime(NOON_UTC)[:6]) == phoenix
        assert phoenix[1][3] == 5, "12:00 UTC is 05:00 in Phoenix"
    assert (os.environ.get("TZ"), time.localtime(NOON_UTC)[:6]) == original


def test_no_other_test_moves_the_process_zone_itself() -> None:
    files = sorted(TESTS.rglob("*.py"))
    assert len(files) > 20, "discovery broke: nothing to guard"
    call = re.compile(r"\.tzset\b|[\"']tzset[\"']")
    own = {TESTS / "process_zone.py", Path(__file__).resolve()}
    found = [
        p.relative_to(TESTS).as_posix()
        for p in files
        if p not in own and call.search(p.read_text(encoding="utf-8"))
    ]
    assert not found, f"use tests.process_zone.process_zone instead: {found}"
