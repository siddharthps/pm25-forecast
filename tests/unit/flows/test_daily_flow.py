"""The Prefect flow is a thin wrapper: it passes its inputs to the job and nothing else."""

import logging
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from airwatch.flows import daily

RUN = "0f8c2a5e-6a3b-4b9e-9a51-3d2f0c7e1b44"
SCHEDULED = datetime(2026, 11, 21, 12, tzinfo=UTC)


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def job(settings: Any, **kwargs: Any) -> Any:
        seen.append({"settings": settings, **kwargs})
        return SimpleNamespace(run=SimpleNamespace(status="recorded"))

    monkeypatch.setattr(daily, "daily_job", job)
    monkeypatch.setattr(daily, "flow_run", SimpleNamespace(id=RUN, scheduled_start_time=SCHEDULED))
    monkeypatch.setattr(daily, "get_settings", lambda: "settings")
    return seen


def test_the_flow_is_named_for_the_deployment() -> None:
    assert daily.daily_forecast.name == "daily-forecast"


def test_a_run_is_a_dry_run_unless_told_to_publish(calls: list[dict[str, Any]]) -> None:
    assert daily.daily_forecast.fn() == "recorded"
    assert calls == [
        {
            "settings": "settings",
            "run_id": RUN,
            "scheduled_start": SCHEDULED,
            "publish": False,
            "target_day": None,
        }
    ]


def test_publish_and_target_day_pass_straight_through(calls: list[dict[str, Any]]) -> None:
    daily.daily_forecast.fn(publish=True, target_day=date(2026, 11, 22))
    assert (calls[0]["publish"], calls[0]["target_day"]) == (True, date(2026, 11, 22))


def test_the_flow_has_no_retries_of_its_own() -> None:
    """Retries are the watchdog's job (D-011); a retry here would spend minutes on a bad day."""
    assert daily.daily_forecast.retries in (0, None)


@pytest.mark.usefixtures("calls")
def test_our_info_logs_reach_prefect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prefect attaches its handler to `airwatch` but sets no level, so INFO was dropped (#68)."""
    logger = logging.getLogger("airwatch")
    monkeypatch.setattr(logger, "level", logging.NOTSET)
    daily.daily_forecast.fn()
    assert logger.level == logging.INFO
