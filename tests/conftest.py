"""Shared test setup.

Hypothesis runs derandomized, so the core suite is repeatable: the same examples every run, on
every machine. Run `pytest --hypothesis-profile=explore` locally to search with fresh random
examples; save any shrunk failure in tests/regressions/ as an ordinary test.

The Prefect flow module comes through the `daily` fixture, not a top-level import: every worker
collects every file, and importing Prefect costs each about 2 s (#83, test_suite_speed.py).
"""

import importlib
from types import ModuleType

import pytest
from hypothesis import settings

settings.register_profile("default", derandomize=True, print_blob=True)
settings.register_profile("explore", max_examples=2_000, print_blob=True)
settings.load_profile("default")


@pytest.fixture(scope="session")
def daily() -> ModuleType:
    return importlib.import_module("airwatch.flows.daily")
