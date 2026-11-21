"""The watchdog Lambda: the backup trigger for the daily forecast (#16, T9; D-011, D-041).

EventBridge Scheduler calls it twice a day, after the 06:00 Chicago issue time (D-019):

- **08:00, `retry`:** if the target day's record is missing, start the Prefect deployment through
  the Prefect API, publishing, with an idempotency key so a repeated call starts one run, then
  email that the scheduled run was missed. Then add up the month's compute ledger and email once
  a month, the first time it passes the alert line.
- **09:00, `verify`:** if the record is still missing, email. Nothing is started.
- **A drill** (`"drill": true`, the owner's test invoke): its own idempotency key, so it
  never uses up a real day's, and DRILL in every email. A drill retry must target a day
  whose issue time hasn't come, so the run it starts refuses as too early and can't publish.

"Done" is the S3 record (D-011), never Prefect's run state. Any error emails its type and is
re-raised, so the Lambda's error alarm fires too: the watchdog fails closed. The Prefect key is
read from SSM at call time and never logged or emailed.

The zip ships this file alone as `handler.py`, with boto3 and tzdata from
`requirements/watchdog.txt` (`airwatch.watchdog.build`). So it imports only the standard library
and boto3. Its record key, ledger rules and target day are tested against the forecast's own.
"""

import json
import logging
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import ClientError

__all__ = [
    "ALERT_MINUTES",
    "ALERT_PREFIX",
    "FREE_MINUTES",
    "LEDGER_PREFIX",
    "Clients",
    "Config",
    "WatchdogError",
    "configure_logging",
    "handle",
    "lambda_handler",
    "record_key",
    "target_day",
]

ISSUE_TZ = ZoneInfo("America/Chicago")
ISSUE_TIME = time(6)
LEDGER_PREFIX = "reports/compute/"
ALERT_PREFIX = "reports/compute-alerts/"
ALERT_MINUTES = 300
FREE_MINUTES = 500
HTTP_TIMEOUT_S = 20
HTTP_CREATED = 201
HTTP_EXISTING = 200
SUBJECT = "[pm25-forecast]"
SDK_LOGGERS = ("boto3", "botocore", "s3transfer", "urllib3")
MAX_SHOWN = 60

log = logging.getLogger(__name__)

Post = Callable[[str, bytes, Mapping[str, str]], tuple[int, bytes]]


class WatchdogError(RuntimeError):
    """A problem the watchdog found itself. Raised after its email, so the error alarm fires too."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.emailed = False


@dataclass(frozen=True)
class Config:
    data_bucket: str
    topic_arn: str
    prefect_key_parameter: str
    prefect_api_url: str
    deployment_id: str

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Config":
        """Read the Lambda's environment; a missing setting raises KeyError."""
        api = env["PREFECT_API_URL"].rstrip("/")
        if not api.startswith("https://"):
            raise ValueError("PREFECT_API_URL must be https")
        return cls(
            data_bucket=env["DATA_BUCKET"],
            topic_arn=env["ALERT_TOPIC_ARN"],
            prefect_key_parameter=env["PREFECT_KEY_PARAMETER"],
            prefect_api_url=api,
            deployment_id=env["PREFECT_DEPLOYMENT_ID"],
        )


@dataclass(frozen=True)
class Clients:
    """The outside world: boto3 clients (or moto's) and the Prefect POST (or a fake)."""

    s3: Any
    ssm: Any
    sns: Any
    post: Post


def target_day(at: datetime) -> date:
    """The day forecast by the latest issue at or before `at`: Chicago's date of `at`, plus one."""
    local = at.astimezone(ISSUE_TZ)
    if local.time() < ISSUE_TIME:
        raise WatchdogError(f"{at.isoformat()} is before the 06:00 Chicago issue time")
    return local.date() + timedelta(days=1)


def record_key(day: date) -> str:
    """The forecast's record for `day` (D-034; tested equal to airwatch.forecast.record)."""
    return f"records/forecast_date={day.isoformat()}/forecast.json"


def _scheduled_time(event: Mapping[str, Any]) -> datetime:
    raw = event.get("scheduled_time")
    got = repr(raw)[:MAX_SHOWN]
    if not isinstance(raw, str) or not raw.endswith("Z"):
        raise WatchdogError(
            f"the event needs scheduled_time as UTC, e.g. 2026-11-21T14:00:00Z; got {got}"
        )
    try:
        return datetime.fromisoformat(raw).astimezone(UTC)
    except ValueError as exc:
        raise WatchdogError(f"scheduled_time isn't an ISO time; got {got}") from exc


def _exists(s3: Any, bucket: str, key: str) -> bool:
    found = s3.list_objects_v2(Bucket=bucket, Prefix=key, MaxKeys=1).get("Contents", [])
    return any(o["Key"] == key for o in found)


def _month_minutes(s3: Any, bucket: str, at: datetime) -> int:
    prefix = f"{LEDGER_PREFIX}month={at:%Y-%m}/"
    total = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            total += int(json.loads(body)["minutes"])
    return total


def _created_once(s3: Any, bucket: str, key: str, body: bytes) -> bool:
    """Create `key` only if absent (S3 conditional write, D-034); False if it already exists."""
    try:
        s3.put_object(Bucket=bucket, Key=key, Body=body, IfNoneMatch="*")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"PreconditionFailed", "412"}:
            return False
        raise
    return True


def _email(sns: Any, topic: str, subject: str, message: str, *, drill: bool = False) -> None:
    label = f"{SUBJECT} DRILL" if drill else SUBJECT
    sns.publish(TopicArn=topic, Subject=f"{label} {subject}"[:100], Message=message)


def _start_run(config: Config, ssm: Any, post: Post, day: date, *, drill: bool) -> tuple[str, str]:
    """Start one publishing run for `day`; returns ("started" | "already started", run name)."""
    try:
        key = ssm.get_parameter(Name=config.prefect_key_parameter, WithDecryption=True)
        token = key["Parameter"]["Value"]
    except Exception as exc:
        raise WatchdogError(f"couldn't read the Prefect key: {_kind(exc)}") from None
    body = {
        "parameters": {"publish": True, "target_day": day.isoformat()},
        "idempotency_key": f"watchdog-{'drill-' if drill else ''}{day.isoformat()}",
        "tags": ["watchdog", "drill"] if drill else ["watchdog"],
    }
    url = f"{config.prefect_api_url}/deployments/{config.deployment_id}/create_flow_run"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        status, reply = post(url, json.dumps(body).encode("utf-8"), headers)
    except Exception as exc:
        raise WatchdogError(f"Prefect didn't answer: {type(exc).__name__}") from None
    if status not in {HTTP_CREATED, HTTP_EXISTING}:
        raise WatchdogError(f"Prefect refused the run: HTTP {status}")
    name = str(json.loads(reply).get("name", "?"))
    return ("already started" if status == HTTP_EXISTING else "started"), name


def _kind(exc: Exception) -> str:
    """An error's kind without its text (which can hold URLs or values): AWS code, else type."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if code:
            return str(code)
    return type(exc).__name__


def _retry(config: Config, aws: Clients, at: datetime, *, drill: bool) -> dict[str, Any]:
    day = target_day(at)
    result: dict[str, Any] = {"mode": "retry", "target_day": day.isoformat()}
    if _exists(aws.s3, config.data_bucket, record_key(day)):
        result["record"] = "present"
    else:
        result["record"] = "missing"
        try:
            outcome, name = _start_run(config, aws.ssm, aws.post, day, drill=drill)
        except WatchdogError as exc:
            _email(
                aws.sns,
                config.topic_arn,
                f"forecast for {day} missing, retry FAILED",
                f"No record for {day} at 08:00 Chicago, and the watchdog couldn't start a "
                f"retry: {exc}. Check Prefect Cloud and the forecast logs.",
                drill=drill,
            )
            exc.emailed = True
            raise
        result["retry"] = outcome
        _email(
            aws.sns,
            config.topic_arn,
            f"forecast for {day} missed, retry {outcome}",
            f"No record for {day} at 08:00 Chicago: the 06:00 run didn't finish. The watchdog's "
            f"retry run is {outcome} ({name}). The 09:00 check emails if it's still missing.",
            drill=drill,
        )
    result["month_minutes"] = _minutes_check(config, aws, at)
    return result


def _minutes_check(config: Config, aws: Clients, at: datetime) -> int:
    total = _month_minutes(aws.s3, config.data_bucket, at)
    if total > ALERT_MINUTES:
        marker = f"{ALERT_PREFIX}month={at:%Y-%m}/over-{ALERT_MINUTES}.json"
        note = {"month_minutes": total, "noted_utc": at.isoformat()}
        if _created_once(aws.s3, config.data_bucket, marker, json.dumps(note).encode("utf-8")):
            _email(
                aws.sns,
                config.topic_arn,
                f"Prefect minutes over {ALERT_MINUTES}",
                f"This month's Prefect managed runs total about {total} of the free "
                f"{FREE_MINUTES} minutes (alert line {ALERT_MINUTES}). Ledger: "
                f"{LEDGER_PREFIX}month={at:%Y-%m}/. This email is sent once a month.",
            )
    return total


def _verify(config: Config, aws: Clients, at: datetime, *, drill: bool) -> dict[str, Any]:
    day = target_day(at)
    present = _exists(aws.s3, config.data_bucket, record_key(day))
    if not present:
        _email(
            aws.sns,
            config.topic_arn,
            f"forecast for {day} still missing",
            f"No record for {day} at 09:00 Chicago, after the 08:00 retry. The page still "
            "shows the previous forecast. Check Prefect Cloud and the forecast logs.",
            drill=drill,
        )
    record = "present" if present else "missing"
    return {"mode": "verify", "target_day": day.isoformat(), "record": record}


def _drill(event: Mapping[str, Any], mode: object, at: datetime, now: datetime) -> bool:
    """Whether this is a drill; a drill retry may only target a day not yet issued."""
    drill: object = event.get("drill", False)
    if not isinstance(drill, bool):
        raise WatchdogError("drill must be true or false")
    if drill and mode == "retry":
        issue = datetime.combine(target_day(at) - timedelta(days=1), ISSUE_TIME, ISSUE_TZ)
        if issue <= now:
            raise WatchdogError(
                f"a drill retry must target a day not yet issued; {issue.isoformat()} has passed"
            )
    return drill


def handle(
    event: Mapping[str, Any],
    *,
    config: Config,
    aws: Clients,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one check. Emails and re-raises on any failure (fail closed)."""
    drill = event.get("drill") is True
    try:
        at = _scheduled_time(event)
        mode = event.get("mode")
        drill = _drill(event, mode, at, now or datetime.now(UTC))
        if mode == "retry":
            result = _retry(config, aws, at, drill=drill)
        elif mode == "verify":
            result = _verify(config, aws, at, drill=drill)
        else:
            raise WatchdogError(f"unknown mode {mode!r}: expected 'retry' or 'verify'")
    except WatchdogError as exc:
        if not exc.emailed:
            _email(
                aws.sns,
                config.topic_arn,
                "watchdog error",
                f"The watchdog failed: {exc}",
                drill=drill,
            )
        raise
    except Exception as exc:
        _email(
            aws.sns,
            config.topic_arn,
            "watchdog error",
            f"The watchdog failed: {_kind(exc)}. Its CloudWatch logs have the details.",
            drill=drill,
        )
        raise
    log.info("watchdog %s", json.dumps(result))
    return result


def configure_logging() -> None:
    """INFO for our lines. The SDK stays at WARNING: at DEBUG, botocore logs response bodies,
    and the SSM reply holds the decrypted key."""
    logging.getLogger().setLevel(logging.INFO)
    for name in SDK_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _urllib_post(  # pragma: no cover
    url: str, body: bytes, headers: Mapping[str, str]
) -> tuple[int, bytes]:
    request = urllib.request.Request(  # noqa: S310  (Config.from_env allows only https)
        url, data=body, headers=dict(headers), method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:  # noqa: S310
            return int(response.status), bytes(response.read())
    except urllib.error.HTTPError as exc:
        return int(exc.code), b"{}"


def lambda_handler(event: dict[str, Any], _context: object) -> dict[str, Any]:  # pragma: no cover
    """The Lambda entry point: real AWS clients and HTTP, settings from the environment."""
    configure_logging()
    return handle(
        event,
        config=Config.from_env(os.environ),
        aws=Clients(
            s3=boto3.client("s3"),
            ssm=boto3.client("ssm"),
            sns=boto3.client("sns"),
            post=_urllib_post,
        ),
    )
