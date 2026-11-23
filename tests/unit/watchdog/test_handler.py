"""The watchdog's rules (#16, T9; D-011, D-041), on moto's fake S3, SSM and SNS and a fake Prefect.

- 08:00 (`retry`): a record means no action; no record means one Prefect run (publishing, with an
  idempotency key) and an email; a run that can't be started emails and fails.
- 09:00 (`verify`): a missing record emails; nothing is started.
- The minutes email is sent once a month, the first time the ledger passes 300.
- Any error emails its type and is re-raised (fail closed); the key never reaches an email or log.
"""

import ast
import contextlib
import dataclasses
import json
import logging
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from airwatch.forecast.record import record_key
from airwatch.monitoring import compute
from airwatch.storage import S3Store
from airwatch.watchdog import handler as wd

REGION = "us-east-1"
BUCKET = "pm25-forecast-data-test"
PARAM = "/pm25-forecast/prefect-api-key"
KEY = "pnu_" + "x" * 36
API = "https://api.prefect.cloud/api/accounts/a/workspaces/w"
DEPLOYMENT = "4a5b6c7d-8e9f-4a0b-9c1d-2e3f4a5b6c7d"
AT_0800 = "2026-11-21T14:00:00Z"
AT_0900 = "2026-11-21T15:00:00Z"
TARGET = date(2026, 11, 22)
RUN = {"id": "06b01005-4e4f-75ca-8000-a64c1229cea0", "name": "rose-ocelot"}


@dataclass
class FakePrefect:
    """Records each POST and answers with a fixed status, or raises."""

    status: int = 201
    raises: Exception | None = None
    calls: list[tuple[str, dict[str, Any], dict[str, str]]] = field(default_factory=list)

    def __call__(self, url: str, body: bytes, headers: Mapping[str, str]) -> tuple[int, bytes]:
        self.calls.append((url, json.loads(body), dict(headers)))
        if self.raises is not None:
            raise self.raises
        return self.status, json.dumps(RUN).encode()


@dataclass
class Aws:
    s3: Any
    ssm: Any
    sns: Any
    topic: str
    queue: Any
    queue_url: str

    def emails(self) -> list[dict[str, str]]:
        """Every message the topic delivered, read back through an SQS subscriber."""
        out: list[dict[str, str]] = []
        while True:
            got = self.queue.receive_message(QueueUrl=self.queue_url, MaxNumberOfMessages=10)
            batch = got.get("Messages", [])
            if not batch:
                return out
            for m in batch:
                note = json.loads(m["Body"])
                out.append({"subject": note.get("Subject", ""), "message": note["Message"]})
                self.queue.delete_message(QueueUrl=self.queue_url, ReceiptHandle=m["ReceiptHandle"])


@pytest.fixture(scope="module")
def _moto() -> Iterator[None]:
    with mock_aws():
        yield


@pytest.fixture
def aws(_moto: None) -> Iterator[Aws]:
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket=BUCKET)
    s3.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
    ssm = boto3.client("ssm", region_name=REGION)
    ssm.put_parameter(Name=PARAM, Value=KEY, Type="SecureString", Overwrite=True)
    sns = boto3.client("sns", region_name=REGION)
    topic = sns.create_topic(Name="pm25-forecast-alerts")["TopicArn"]
    sqs = boto3.client("sqs", region_name=REGION)
    queue_url = sqs.create_queue(QueueName="alerts-inbox")["QueueUrl"]
    queue_arn = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])
    sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=queue_arn["Attributes"]["QueueArn"])
    yield Aws(s3, ssm, sns, topic, sqs, queue_url)
    listing = s3.list_object_versions(Bucket=BUCKET)
    for v in listing.get("Versions", []) + listing.get("DeleteMarkers", []):
        s3.delete_object(Bucket=BUCKET, Key=v["Key"], VersionId=v["VersionId"])
    s3.delete_bucket(Bucket=BUCKET)
    sqs.delete_queue(QueueUrl=queue_url)
    sns.delete_topic(TopicArn=topic)


def _config(aws: Aws) -> wd.Config:
    return wd.Config(
        data_bucket=BUCKET,
        topic_arn=aws.topic,
        prefect_key_parameter=PARAM,
        prefect_api_url=API,
        deployment_id=DEPLOYMENT,
    )


def _handle(
    aws: Aws,
    event: dict[str, Any],
    prefect: FakePrefect | None = None,
    now: datetime = datetime(2026, 11, 21, 15, 0, tzinfo=UTC),
) -> dict[str, Any]:
    clients = wd.Clients(
        s3=aws.s3,
        ssm=aws.ssm,
        sns=aws.sns,
        post=prefect if prefect is not None else FakePrefect(),
    )
    return wd.handle(event, config=_config(aws), aws=clients, now=now)


def _put_record(aws: Aws, day: date = TARGET) -> None:
    aws.s3.put_object(Bucket=BUCKET, Key=record_key(day), Body=b"{}")


def _put_minutes(aws: Aws, runs: list[int], at: datetime) -> None:
    store = S3Store(aws.s3, BUCKET)
    for i, minutes in enumerate(runs):
        start = at - timedelta(minutes=minutes - compute.TEARDOWN_PAD_MIN)
        compute.record_run(store, f"00000000-0000-4000-8000-{i:012d}", start, at)


RETRY = {"mode": "retry", "scheduled_time": AT_0800}
VERIFY = {"mode": "verify", "scheduled_time": AT_0900}


def test_record_present_means_no_action(aws: Aws) -> None:
    _put_record(aws)
    prefect = FakePrefect()
    result = _handle(aws, RETRY, prefect)
    assert result["record"] == "present"
    assert prefect.calls == []
    assert aws.emails() == []


def test_record_absent_starts_one_publishing_run_then_emails(aws: Aws) -> None:
    prefect = FakePrefect(status=201)
    result = _handle(aws, RETRY, prefect)
    assert result["record"] == "missing"
    assert result["retry"] == "started"
    [(url, body, headers)] = prefect.calls
    assert url == f"{API}/deployments/{DEPLOYMENT}/create_flow_run"
    assert body["parameters"] == {"publish": True, "target_day": "2026-11-22"}
    assert body["idempotency_key"] == "watchdog-2026-11-22"
    assert headers["Authorization"] == f"Bearer {KEY}"
    [email] = aws.emails()
    assert "2026-11-22" in email["message"]
    assert "rose-ocelot" in email["message"]


def test_a_run_already_started_by_an_earlier_attempt_is_reported_not_repeated(aws: Aws) -> None:
    prefect = FakePrefect(status=200)
    result = _handle(aws, RETRY, prefect)
    assert result["retry"] == "already started"
    [email] = aws.emails()
    assert "already" in email["message"]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500])
def test_a_refused_retry_emails_and_fails(aws: Aws, status: int) -> None:
    with pytest.raises(wd.WatchdogError, match=str(status)):
        _handle(aws, RETRY, FakePrefect(status=status))
    [email] = aws.emails()
    assert "2026-11-22" in email["message"]
    assert str(status) in email["message"]


def test_an_unreachable_prefect_emails_the_error_type_and_fails(aws: Aws) -> None:
    with pytest.raises(wd.WatchdogError):
        _handle(aws, RETRY, FakePrefect(raises=TimeoutError("timed out at a URL")))
    [email] = aws.emails()
    assert "TimeoutError" in email["message"]
    assert "URL" not in email["message"]


def test_a_missing_key_parameter_emails_and_fails(aws: Aws) -> None:
    aws.ssm.delete_parameter(Name=PARAM)
    prefect = FakePrefect()
    with pytest.raises(wd.WatchdogError):
        _handle(aws, RETRY, prefect)
    assert prefect.calls == []
    [email] = aws.emails()
    assert "ParameterNotFound" in email["message"]


def test_verify_finds_the_record_and_stays_quiet(aws: Aws) -> None:
    _put_record(aws)
    assert _handle(aws, VERIFY)["record"] == "present"
    assert aws.emails() == []


def test_verify_emails_when_the_record_is_still_missing_and_starts_nothing(aws: Aws) -> None:
    prefect = FakePrefect()
    result = _handle(aws, VERIFY, prefect)
    assert result["record"] == "missing"
    assert prefect.calls == []
    [email] = aws.emails()
    assert "still" in email["message"] and "2026-11-22" in email["message"]


def test_verify_never_reads_the_key(aws: Aws) -> None:
    aws.ssm.delete_parameter(Name=PARAM)
    _put_record(aws)
    assert _handle(aws, VERIFY)["record"] == "present"


def test_another_days_record_does_not_count(aws: Aws) -> None:
    _put_record(aws, TARGET - timedelta(days=1))
    aws.s3.put_object(Bucket=BUCKET, Key=record_key(TARGET) + ".tmp", Body=b"{}")
    assert _handle(aws, VERIFY)["record"] == "missing"


def test_minutes_over_the_line_email_once_a_month(aws: Aws) -> None:
    _put_record(aws)
    at = datetime(2026, 11, 21, 12, 30, tzinfo=UTC)
    _put_minutes(aws, [200, 101], at)
    first = _handle(aws, RETRY)
    assert first["month_minutes"] == 301
    [email] = aws.emails()
    assert "301" in email["message"] and "500" in email["message"]
    again = _handle(aws, RETRY)
    assert again["month_minutes"] == 301
    assert aws.emails() == []


def test_minutes_at_the_line_do_not_email(aws: Aws) -> None:
    _put_record(aws)
    _put_minutes(aws, [150, 150], datetime(2026, 11, 21, 12, 30, tzinfo=UTC))
    assert _handle(aws, RETRY)["month_minutes"] == 300
    assert aws.emails() == []


def test_last_months_minutes_do_not_count(aws: Aws) -> None:
    _put_record(aws)
    _put_minutes(aws, [400], datetime(2026, 10, 31, 23, 0, tzinfo=UTC))
    assert _handle(aws, RETRY)["month_minutes"] == 0
    assert aws.emails() == []


def test_the_minutes_total_agrees_with_the_ledgers_own(aws: Aws) -> None:
    _put_record(aws)
    at = datetime(2026, 11, 21, 12, 30, tzinfo=UTC)
    _put_minutes(aws, [3, 4, 5], at)
    store = S3Store(aws.s3, BUCKET)
    usage = compute.record_run(store, "00000000-0000-4000-8000-0000000000aa", at, at)
    assert _handle(aws, RETRY)["month_minutes"] == usage.month_total


def test_the_alert_marker_leaves_the_ledger_readable(aws: Aws) -> None:
    """The marker lives outside the month's ledger folder, which record_run sums in full."""
    _put_record(aws)
    at = datetime(2026, 11, 21, 12, 30, tzinfo=UTC)
    _put_minutes(aws, [301], at)
    _handle(aws, RETRY)
    aws.emails()
    store = S3Store(aws.s3, BUCKET)
    usage = compute.record_run(store, "00000000-0000-4000-8000-0000000000bb", at, at)
    assert usage.month_total == 302


def test_verify_does_not_check_minutes(aws: Aws) -> None:
    _put_record(aws)
    _put_minutes(aws, [400], datetime(2026, 11, 21, 12, 30, tzinfo=UTC))
    assert "month_minutes" not in _handle(aws, VERIFY)
    assert aws.emails() == []


def test_a_failing_email_fails_the_run(aws: Aws) -> None:
    """The Lambda's error alarm is then the last line (fail closed)."""
    aws.sns.delete_topic(TopicArn=aws.topic)
    with pytest.raises(Exception):  # noqa: B017  (whatever SNS raises must propagate)
        _handle(aws, VERIFY)


@pytest.mark.parametrize(
    "event",
    [
        {"mode": "publish", "scheduled_time": AT_0800},
        {"mode": "retry"},
        {"mode": "retry", "scheduled_time": "2026-11-21 14:00"},
        {"mode": "retry", "scheduled_time": "2026-11-21T11:59:00Z"},
        {"mode": "retry", "scheduled_time": "yesterdayZ"},
    ],
    ids=["unknown-mode", "no-time", "not-utc-z", "before-the-issue-time", "not-iso"],
)
def test_a_bad_event_emails_and_fails(aws: Aws, event: dict[str, Any]) -> None:
    with pytest.raises(wd.WatchdogError):
        _handle(aws, event)
    [email] = aws.emails()
    assert "watchdog" in email["subject"].lower()


@pytest.fixture
def lambda_logging() -> Iterator[None]:
    """The Lambda's logging setup, undone afterwards so other tests keep their levels."""
    names = ["", *wd.SDK_LOGGERS]
    saved = {n: logging.getLogger(n).level for n in names}
    wd.configure_logging()
    yield
    for n, level in saved.items():
        logging.getLogger(n).setLevel(level)


@pytest.mark.usefixtures("lambda_logging")
def test_the_key_never_reaches_an_email_or_a_log(
    aws: Aws, caplog: pytest.LogCaptureFixture
) -> None:
    """Even with the root logger at DEBUG: botocore would log the SSM reply, key included."""
    caplog.set_level(logging.DEBUG)
    for prefect in (FakePrefect(201), FakePrefect(401), FakePrefect(raises=OSError(KEY))):
        with contextlib.suppress(wd.WatchdogError):
            _handle(aws, RETRY, prefect)
    sent = aws.emails()
    assert len(sent) == 3
    assert all(KEY not in e["message"] and KEY not in e["subject"] for e in sent)
    assert KEY not in caplog.text


def test_it_uses_the_forecasts_record_key_and_ledger_rules() -> None:
    assert wd.record_key(TARGET) == record_key(TARGET)
    assert wd.LEDGER_PREFIX == compute.PREFIX
    assert wd.ALERT_MINUTES == compute.MONTHLY_ALERT_MIN
    assert wd.FREE_MINUTES == compute.MONTHLY_FREE_MIN
    assert not wd.ALERT_PREFIX.startswith(compute.PREFIX)


def test_config_comes_from_the_environment() -> None:
    env = {
        "DATA_BUCKET": BUCKET,
        "ALERT_TOPIC_ARN": "arn:aws:sns:us-east-1:123456789012:pm25-forecast-alerts",
        "PREFECT_KEY_PARAMETER": PARAM,
        "PREFECT_API_URL": API,
        "PREFECT_DEPLOYMENT_ID": DEPLOYMENT,
    }
    assert wd.Config.from_env(env).deployment_id == DEPLOYMENT
    with pytest.raises(KeyError):
        wd.Config.from_env({k: v for k, v in env.items() if k != "DATA_BUCKET"})
    with pytest.raises(ValueError, match="https"):
        wd.Config.from_env({**env, "PREFECT_API_URL": "http://api.prefect.cloud/api"})


def test_it_imports_only_the_standard_library_and_boto3() -> None:
    """The zip ships this file alone with boto3 and tzdata, so it can't import airwatch."""
    tree = ast.parse(Path(wd.__file__).read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "no relative imports"
            roots.add((node.module or "").split(".")[0])
    allowed = set(sys.stdlib_module_names) | {"boto3", "botocore"}
    assert roots <= allowed, roots - allowed


def test_a_corrupt_ledger_entry_emails_its_type_and_fails(aws: Aws) -> None:
    _put_record(aws)
    aws.s3.put_object(
        Bucket=BUCKET, Key="reports/compute/month=2026-11/run=bad.json", Body=b"not json"
    )
    with pytest.raises(json.JSONDecodeError):
        _handle(aws, RETRY)
    [email] = aws.emails()
    assert "JSONDecodeError" in email["message"]
    assert "not json" not in email["message"]


def test_an_aws_error_emails_its_code(aws: Aws) -> None:
    config = dataclasses.replace(_config(aws), data_bucket="no-such-bucket")
    clients = wd.Clients(s3=aws.s3, ssm=aws.ssm, sns=aws.sns, post=FakePrefect())
    with pytest.raises(ClientError):
        wd.handle(VERIFY, config=config, aws=clients)
    [email] = aws.emails()
    assert "NoSuchBucket" in email["message"]


class RefusingPut:
    """S3 that refuses writes with AccessDenied: not the 412 that means 'already sent'."""

    def __init__(self, real: Any) -> None:
        self._real = real

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def put_object(self, **_: Any) -> None:
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "PutObject")


def test_a_refused_marker_write_is_an_error_not_already_sent(aws: Aws) -> None:
    _put_record(aws)
    _put_minutes(aws, [301], datetime(2026, 11, 21, 12, 30, tzinfo=UTC))
    clients = wd.Clients(s3=RefusingPut(aws.s3), ssm=aws.ssm, sns=aws.sns, post=FakePrefect())
    with pytest.raises(ClientError):
        wd.handle(RETRY, config=_config(aws), aws=clients)
    [email] = aws.emails()
    assert "AccessDenied" in email["message"]


DRILL_NOW = datetime(2026, 11, 21, 3, 0, tzinfo=UTC)
DRILL = {"mode": "retry", "scheduled_time": "2026-11-22T14:00:00Z", "drill": True}


def test_a_drill_uses_its_own_key_and_says_drill(aws: Aws) -> None:
    prefect = FakePrefect(status=201)
    result = _handle(aws, DRILL, prefect, now=DRILL_NOW)
    assert result["retry"] == "started"
    [(_, body, _)] = prefect.calls
    assert body["idempotency_key"] == "watchdog-drill-2026-11-23"
    assert body["tags"] == ["watchdog", "drill"]
    assert body["parameters"] == {"publish": True, "target_day": "2026-11-23"}
    [email] = aws.emails()
    assert "DRILL" in email["subject"]


def test_a_real_retry_never_uses_a_drill_key(aws: Aws) -> None:
    prefect = FakePrefect(status=201)
    _handle(aws, RETRY, prefect)
    [(_, body, _)] = prefect.calls
    assert "drill" not in body["idempotency_key"]
    assert "DRILL" not in aws.emails()[0]["subject"]


def test_a_drill_retry_for_an_issued_day_is_refused_before_starting_anything(aws: Aws) -> None:
    """Its run could otherwise publish a real record late."""
    prefect = FakePrefect()
    issued = {"mode": "retry", "scheduled_time": AT_0800, "drill": True}
    with pytest.raises(wd.WatchdogError, match="not yet issued"):
        _handle(aws, issued, prefect, now=datetime(2026, 11, 21, 12, 0, tzinfo=UTC))
    assert prefect.calls == []
    [email] = aws.emails()
    assert "DRILL" in email["subject"]


def test_a_drill_verify_may_check_any_day(aws: Aws) -> None:
    _put_record(aws)
    drill = {**VERIFY, "drill": True}
    assert _handle(aws, drill, now=datetime(2026, 11, 22, 0, 0, tzinfo=UTC))["record"] == "present"


def test_drill_must_be_a_boolean(aws: Aws) -> None:
    with pytest.raises(wd.WatchdogError, match="drill"):
        _handle(aws, {**RETRY, "drill": "yes"})
    [email] = aws.emails()
    assert "watchdog" in email["subject"].lower()


def test_a_placeholder_left_by_the_scheduler_is_named_in_the_email(aws: Aws) -> None:
    """2026-11-21: the scheduler sent its placeholder unsubstituted; the email should say so."""
    event = {"mode": "retry", "scheduled_time": "<aws.scheduler.scheduled-time>"}
    with pytest.raises(wd.WatchdogError):
        _handle(aws, event)
    [email] = aws.emails()
    assert "<aws.scheduler.scheduled-time>" in email["message"]


def test_a_long_bad_value_is_cut_short_in_the_email(aws: Aws) -> None:
    with pytest.raises(wd.WatchdogError):
        _handle(aws, {"mode": "retry", "scheduled_time": "x" * 500})
    [email] = aws.emails()
    assert "x" * 61 not in email["message"]
