"""The forecast's failure line names the error's type, never a stray value (#56).

Errors are reported by type (the owner's rules). A message from someone else's code can quote a
cell, a bucket key or a URL. Only our own `ReportableError`s, whose messages we wrote from dates,
paths, rule names and counts, are printed in full.
"""

import inspect
from datetime import date

import pytest

from airwatch.errors import ReportableError
from airwatch.forecast import run
from airwatch.forecast.publish import PublishRefusedError
from airwatch.forecast.record import RecordUnreadableError
from airwatch.forecast.run import NoForecastError, TooEarlyError, failure_line
from airwatch.storage import WriteConflictError
from airwatch.validation.checks import ValidationFailedError

TARGET = date(2026, 11, 23)
DISTINCTIVE_VALUE = "987.6-not-for-logs"


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(
            ValueError(f"could not convert {DISTINCTIVE_VALUE}"), id="a pandas-style error"
        ),
        pytest.param(KeyError(DISTINCTIVE_VALUE), id="a missing key"),
        pytest.param(OSError(f"https://example.test/?token={DISTINCTIVE_VALUE}"), id="a URL"),
        pytest.param(RuntimeError(DISTINCTIVE_VALUE), id="a bare RuntimeError"),
    ],
)
def test_a_foreign_error_is_reported_by_type_only(exc: Exception) -> None:
    line = failure_line(TARGET, exc)
    assert DISTINCTIVE_VALUE not in line
    assert "2026-11-23" in line
    assert type(exc).__name__ in line


@pytest.mark.parametrize(
    "cls",
    [
        TooEarlyError,
        NoForecastError,
        ValidationFailedError,
        PublishRefusedError,
        RecordUnreadableError,
        WriteConflictError,
    ],
)
def test_our_own_errors_keep_their_message(cls: type[ReportableError]) -> None:
    assert issubclass(cls, ReportableError)
    assert issubclass(cls, RuntimeError)
    line = failure_line(TARGET, cls("hard validation failure (duplicate: 2)"))
    assert cls.__name__ in line
    assert "hard validation failure (duplicate: 2)" in line


def test_main_logs_through_the_failure_line() -> None:
    lines = [ln.strip() for ln in inspect.getsource(run.main).splitlines()]
    uses = [ln for ln in lines if "exc" in ln.replace("except", "")]
    assert uses == ["except Exception as exc:", "log.error(failure_line(target, exc))"]
