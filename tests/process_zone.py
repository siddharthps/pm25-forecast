"""Run a test with the whole process in another time zone (#88): `TZ` plus `time.tzset`.

This PC and WSL run on America/Chicago, the issue zone, so a datetime that silently drops its
zone passes here and fails on a UTC cloud runner. Moving the process zone makes such a bug fail
locally too. `time.tzset` is POSIX only, so on Windows every test that uses this skips with
`SKIP_REASON`; they run in WSL and CI.
"""

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest

SKIP_REASON = "time.tzset is POSIX only (runs in WSL and CI)"
CAN_MOVE_ZONE = hasattr(time, "tzset")
"""For a test that must skip as a whole, such as a Hypothesis test (a skip inside one fails it)."""


@contextmanager
def process_zone(name: str) -> Iterator[None]:
    """The process's local zone is `name` inside the block; afterwards, what it was before."""
    tzset: Callable[[], None] | None = getattr(time, "tzset", None)
    if tzset is None:
        pytest.skip(SKIP_REASON)
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
