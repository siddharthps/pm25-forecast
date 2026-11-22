"""The one logging setup (#52): UTC timestamps with the zone shown, and quiet third-party loggers.

A line reads `2026-11-22T12:01:40.540Z message`. The time comes from the record's UTC instant,
never the process's local zone: a cloud runner's zone isn't this PC's (SPEC § Code Style).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TextIO, override

FORMAT = "%(asctime)s %(message)s"
QUIET = ("botocore", "boto3", "urllib3")


class UtcFormatter(logging.Formatter):
    @override
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        utc = datetime.fromtimestamp(record.created, UTC)
        return f"{utc:%Y-%m-%dT%H:%M:%S}.{utc.microsecond // 1000:03d}Z"


class _Handler(logging.StreamHandler[TextIO]):
    """The handler `configure` owns, so a second call can find and replace it."""


def formatter() -> logging.Formatter:
    return UtcFormatter(FORMAT)


def configure(level: int = logging.INFO, stream: TextIO | None = None) -> None:
    """Send `airwatch`'s lines (and everything else at `level`) to `stream`, stderr by default.

    Calling it again replaces its own handler, so lines are never doubled.
    """
    root = logging.getLogger()
    for old in [h for h in root.handlers if isinstance(h, _Handler)]:
        root.removeHandler(old)
    handler = _Handler(stream)
    handler.setFormatter(formatter())
    root.addHandler(handler)
    root.setLevel(level)
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.ERROR)
