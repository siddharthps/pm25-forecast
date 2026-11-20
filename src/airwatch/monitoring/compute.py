"""The managed-compute ledger: each Prefect run's minutes, summed per month (#15, T8; D-040).

Prefect bills managed compute from container start-up to teardown, rounded up to a whole minute,
and offers no documented API for the total. So each run estimates its own minutes, from its
scheduled start (which comes before start-up and the pip installs) to the moment it writes this
entry, plus `TEARDOWN_PAD_MIN`. It files that estimate once, under its own run ID, so a retry or a
second write never counts twice. The estimate is checked against Prefect's usage page by hand.

Entries live in the private bucket under `reports/compute/month=YYYY-MM/` (UTC months). The
month's total is the sum of that month's entries. The alert line is 60% of the free plan's 500
minutes (SPEC success criterion 7). The email for it comes with the watchdog's SNS topic (T9).
"""

import json
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from airwatch.forecast.record import Store

__all__ = [
    "MONTHLY_ALERT_MIN",
    "MONTHLY_FREE_MIN",
    "PREFIX",
    "TEARDOWN_PAD_MIN",
    "Usage",
    "billed_minutes",
    "entry_key",
    "record_run",
]

PREFIX = "reports/compute/"
MONTHLY_FREE_MIN = 500
MONTHLY_ALERT_MIN = 300
TEARDOWN_PAD_MIN = 1


@dataclass(frozen=True)
class Usage:
    minutes: int
    month_total: int
    over_alert: bool


def _aware(t: datetime) -> datetime:
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("naive datetime: compute times must carry a zone")
    return t.astimezone(UTC)


def billed_minutes(scheduled_start: datetime, now: datetime) -> int:
    """Minutes from the scheduled start to now, rounded up, plus the teardown pad."""
    seconds = max(0.0, (_aware(now) - _aware(scheduled_start)).total_seconds())
    return math.ceil(seconds / 60) + TEARDOWN_PAD_MIN


def _month_prefix(at: datetime) -> str:
    return f"{PREFIX}month={_aware(at):%Y-%m}/"


def entry_key(run_id: str, at: datetime) -> str:
    """Where a run's entry lives: its UTC month, then its Prefect run ID (a UUID)."""
    try:
        canonical = str(uuid.UUID(run_id))
    except ValueError as exc:
        raise ValueError("run id must be a UUID") from exc
    if canonical != run_id:
        raise ValueError("run id must be a lower-case UUID")
    return f"{_month_prefix(at)}run={run_id}.json"


def record_run(store: Store, run_id: str, scheduled_start: datetime, now: datetime) -> Usage:
    """File this run's minutes once, then return them with the month's total."""
    minutes = billed_minutes(scheduled_start, now)
    entry = {
        "run_id": run_id,
        "scheduled_start_utc": _aware(scheduled_start).isoformat(),
        "finished_utc": _aware(now).isoformat(),
        "minutes": minutes,
    }
    key = entry_key(run_id, now)
    if not store.create_if_absent(key, (json.dumps(entry, indent=2) + "\n").encode("utf-8")):
        stored = store.get(key)
        minutes = json.loads(stored)["minutes"] if stored is not None else minutes
    total = 0
    for other in store.list_keys(_month_prefix(now)):
        raw = store.get(other)
        if raw is not None:
            total += int(json.loads(raw)["minutes"])
    return Usage(minutes=minutes, month_total=total, over_alert=total > MONTHLY_ALERT_MIN)
