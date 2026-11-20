"""The daily Prefect flow: a thin wrapper around `airwatch.forecast.job.daily_job` (D-011, D-040).

No logic lives here (SPEC § Structure). The flow reads the settings, takes its run ID and
scheduled start from Prefect, and passes them on. It defaults to a dry run: only the deployment's
06:00 Chicago schedule passes `publish=True` (`prefect.yaml`), so a manual run never publishes
unless asked. No retries: a failed day is the watchdog's to handle (T9).
"""

from datetime import date

from prefect import flow
from prefect.runtime import flow_run

from airwatch.config import get_settings
from airwatch.forecast.job import daily_job

__all__ = ["daily_forecast"]


@flow(name="daily-forecast", retries=0)
def daily_forecast(publish: bool = False, target_day: date | None = None) -> str:
    """Forecast the next day (a dry run unless `publish`) and file this run's compute minutes."""
    outcome = daily_job(
        get_settings(),
        run_id=str(flow_run.id),
        scheduled_start=flow_run.scheduled_start_time,
        publish=publish,
        target_day=target_day,
    )
    return outcome.run.status
