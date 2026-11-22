"""Fail a test run that takes longer than `SUITE_BUDGET_S` seconds (#83, D-046).

CI sets 75 s on the core suite. Unset, nothing is timed. A value that isn't a positive finite
number is a usage error, so a typo can't switch the check off. Timing starts before collection,
so a slow import counts too. Under xdist only the controller judges; workers don't.
"""

import math
import os
import time

import pytest

ENV = "SUITE_BUDGET_S"
_BUDGET = pytest.StashKey[float | None]()
_START = pytest.StashKey[float]()
_OVER = pytest.StashKey[float]()


def _parse(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        budget = float(raw)
    except ValueError:
        budget = math.nan
    if not (math.isfinite(budget) and budget > 0):
        raise pytest.UsageError(f"{ENV} must be a positive number of seconds, got {raw!r}")
    return budget


def pytest_configure(config: pytest.Config) -> None:
    config.stash[_BUDGET] = _parse(os.environ.get(ENV))


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[_START] = time.monotonic()


def pytest_sessionfinish(session: pytest.Session) -> None:
    budget = session.config.stash[_BUDGET]
    if budget is None or hasattr(session.config, "workerinput"):
        return
    elapsed = time.monotonic() - session.config.stash[_START]
    if elapsed > budget:
        session.config.stash[_OVER] = elapsed
        if session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    elapsed = config.stash.get(_OVER, None)
    if elapsed is not None:
        budget = config.stash[_BUDGET]
        terminalreporter.write_line(
            f"FAILED: the run took {elapsed:.1f} s, over its budget of {budget:g} s ({ENV}, D-046)",
            red=True,
        )
