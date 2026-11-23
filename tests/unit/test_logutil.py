"""One logging setup: UTC timestamps with the zone shown, quiet third-party loggers (#52).

A cloud runner's local zone isn't this PC's, so a local wall-clock time in a log line would mean
a different moment there (SPEC § Code Style: UTC with its zone, everywhere).
"""

import io
import logging
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from airwatch import logutil
from tests.project_files import walk

ROOT = Path(__file__).resolve().parents[2]
CHICAGO = ZoneInfo("America/Chicago")


def _chicago_clock(t: float | None) -> time.struct_time:
    return datetime.fromtimestamp(time.time() if t is None else t, CHICAGO).timetuple()


@pytest.fixture
def root_logger() -> Iterator[logging.Logger]:
    root = logging.getLogger()
    saved = (root.level, root.handlers[:])
    quiet = {name: logging.getLogger(name).level for name in logutil.QUIET}
    yield root
    root.handlers[:] = saved[1]
    root.setLevel(saved[0])
    for name, level in quiet.items():
        logging.getLogger(name).setLevel(level)


def _line_at(created: float) -> str:
    record = logging.LogRecord("airwatch.x", logging.INFO, __file__, 1, "hello", None, None)
    record.created = created
    return logutil.formatter().format(record)


def test_a_line_shows_utc_with_a_z_while_local_time_is_chicago(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logging.Formatter, "converter", staticmethod(_chicago_clock))
    created = datetime(2026, 11, 22, 12, 1, 40, 540_000, tzinfo=UTC).timestamp()
    assert _line_at(created) == "2026-11-22T12:01:40.540Z hello"


@pytest.mark.parametrize(
    ("utc", "expected"),
    [
        pytest.param(
            datetime(2026, 11, 1, 6, 30, tzinfo=UTC), "2026-11-01T06:30:00.000Z", id="01:30 CDT"
        ),
        pytest.param(
            datetime(2026, 11, 1, 7, 30, tzinfo=UTC), "2026-11-01T07:30:00.000Z", id="01:30 CST"
        ),
        pytest.param(
            datetime(2026, 3, 8, 8, 30, tzinfo=UTC), "2026-03-08T08:30:00.000Z", id="spring gap"
        ),
    ],
)
def test_a_dst_change_in_the_local_zone_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, utc: datetime, expected: str
) -> None:
    monkeypatch.setattr(logging.Formatter, "converter", staticmethod(_chicago_clock))
    assert _line_at(utc.timestamp()) == f"{expected} hello"


def test_a_real_process_zone_change_changes_nothing() -> None:
    tzset = getattr(time, "tzset", None)
    if tzset is None:
        pytest.skip("time.tzset is POSIX only (runs in CI)")
    before = os.environ.get("TZ")
    os.environ["TZ"] = "America/Chicago"
    tzset()
    try:
        assert time.localtime(0).tm_hour == 18
        created = datetime(2026, 11, 1, 6, 30, tzinfo=UTC).timestamp()
        assert _line_at(created) == "2026-11-01T06:30:00.000Z hello"
    finally:
        if before is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = before
        tzset()


def test_configure_logs_through_the_utc_formatter_and_quiets_the_noisy(
    root_logger: logging.Logger,
) -> None:
    stream = io.StringIO()
    logutil.configure(stream=stream)
    logging.getLogger("airwatch.test").info("one line")
    assert stream.getvalue().endswith("Z one line\n")
    assert root_logger.level == logging.INFO
    for name in ("botocore", "boto3", "urllib3"):
        assert logging.getLogger(name).level == logging.ERROR


def test_configure_twice_leaves_one_handler(root_logger: logging.Logger) -> None:
    logutil.configure(stream=io.StringIO())
    logutil.configure(stream=io.StringIO())
    ours = [h for h in root_logger.handlers if isinstance(h.formatter, logutil.UtcFormatter)]
    assert len(ours) == 1


def test_no_other_logging_setup_is_left() -> None:
    files = [
        p
        for p in walk(ROOT, {"site_build", "node_modules", "infra"})
        if p.suffix == ".py" and p.parts[len(ROOT.parts)] in {"src", "scripts"}
    ]
    assert len(files) > 20, "discovery broke: nothing to guard"
    found = [
        p.relative_to(ROOT).as_posix()
        for p in files
        if p.name != "logutil.py"
        and any(s in p.read_text(encoding="utf-8") for s in ("basicConfig", "logging.Formatter"))
    ]
    assert not found, f"use airwatch.logutil.configure() instead: {found}"
