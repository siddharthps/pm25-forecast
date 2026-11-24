"""The watchdog's rules (#16, T9; D-011, D-041), on moto's fake S3, SSM and SNS and a fake Prefect.

- 08:00 (`retry`): a record means no action; no record means one Prefect run (publishing, with an
  idempotency key) and an email; a run that can't be started emails and fails.
- 09:00 (`verify`): a missing record emails; nothing is started.
- The minutes email is sent once a month, the first time the ledger passes 300.
- Any error emails its type and is re-raised (fail closed); the key never reaches an email or log.
- Mondays (#113, D-058): 08:00 starts the weekly lock workflow once (a create-once marker first,
  then GitHub's dispatch, then the run's ID recorded); 09:00 emails unless that run succeeded. The
  forecast checks and the lock checks never skip each other.
"""

import contextlib
import dataclasses
import json
import logging
import sys
import threading
import urllib.error
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
from tests.project_files import import_roots

REGION = "us-east-1"
BUCKET = "pm25-forecast-data-test"
PARAM = "/pm25-forecast/prefect-api-key"
KEY = "pnu_" + "x" * 36
API = "https://api.prefect.cloud/api/accounts/a/workspaces/w"
DEPLOYMENT = "4a5b6c7d-8e9f-4a0b-9c1d-2e3f4a5b6c7d"
AT_0800 = "2026-11-21T14:00:00Z"
AT_0900 = "2026-11-21T15:00:00Z"
TARGET = date(2026, 11, 22)
GH_PARAM = "/pm25-forecast/github-lock-token"
GH_TOKEN = "github_pat_" + "y" * 40
REPO = "siddharthps/pm25-forecast"
WORKFLOW = "uv-lock-upgrade.yml"
MONDAY = date(2026, 11, 30)
MON_0800 = "2026-11-30T14:00:00Z"
MON_0900 = "2026-11-30T15:00:00Z"
LOCK_RUN_ID = 45500000001
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
    ssm.put_parameter(Name=GH_PARAM, Value=GH_TOKEN, Type="SecureString", Overwrite=True)
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
        github_token_parameter=GH_PARAM,
        github_repo=REPO,
        lock_workflow=WORKFLOW,
    )


def _no_get(url: str, _: Mapping[str, str]) -> tuple[int, bytes]:
    raise AssertionError(f"no GitHub read expected: {url}")


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
        get=_no_get,
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


@pytest.mark.parametrize("event", [RETRY, VERIFY], ids=["retry-0800", "verify-0900"])
def test_record_present_means_no_action(aws: Aws, event: dict[str, Any]) -> None:
    _put_record(aws)
    prefect = FakePrefect()
    result = _handle(aws, event, prefect)
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
    assert body["tags"] == ["watchdog"]
    [email] = aws.emails()
    assert "2026-11-22" in email["message"]
    assert "rose-ocelot" in email["message"]
    assert "DRILL" not in email["subject"]


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
        "GITHUB_TOKEN_PARAMETER": GH_PARAM,
        "GITHUB_REPO": REPO,
        "LOCK_WORKFLOW": WORKFLOW,
    }
    config = wd.Config.from_env(env)
    assert (config.deployment_id, config.github_repo, config.lock_workflow) == (
        DEPLOYMENT,
        REPO,
        WORKFLOW,
    )
    assert config.github_token_parameter == GH_PARAM
    with pytest.raises(KeyError):
        wd.Config.from_env({k: v for k, v in env.items() if k != "GITHUB_REPO"})
    with pytest.raises(KeyError):
        wd.Config.from_env({k: v for k, v in env.items() if k != "DATA_BUCKET"})
    with pytest.raises(ValueError, match="https"):
        wd.Config.from_env({**env, "PREFECT_API_URL": "http://api.prefect.cloud/api"})


def test_it_imports_only_the_standard_library_and_boto3() -> None:
    """The zip ships this file alone with boto3 and tzdata, so it can't import airwatch.

    mutmut's rewritten copy (under `mutants/`) also imports mutmut's trampoline (#113); the real
    file never may."""
    source = Path(wd.__file__)
    roots = import_roots(source)
    assert roots, "guards the guard: no imports found"
    allowed = set(sys.stdlib_module_names) | {"boto3", "botocore"}
    if "mutants" in source.parts:
        allowed.add("mutmut")
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
    clients = wd.Clients(s3=aws.s3, ssm=aws.ssm, sns=aws.sns, post=FakePrefect(), get=_no_get)
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
    clients = wd.Clients(
        s3=RefusingPut(aws.s3), ssm=aws.ssm, sns=aws.sns, post=FakePrefect(), get=_no_get
    )
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


@dataclass
class LocalPrefect:
    """A real HTTP server on 127.0.0.1 that answers `status`, or drops the connection if None."""

    url: str
    status: int | None = 201
    seen: list[tuple[str, str, bytes, dict[str, str]]] = field(default_factory=list)


@pytest.fixture
def local_prefect() -> Iterator[LocalPrefect]:
    state = LocalPrefect(url="")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            state.seen.append((self.command, self.path, body, dict(self.headers)))
            if state.status is None:
                self.close_connection = True
                return
            reply = json.dumps(RUN).encode()
            self.send_response(state.status)
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *_: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_address[1]}/create_flow_run"
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    yield state
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize(
    ("status", "body"),
    [(201, json.dumps(RUN).encode()), (200, json.dumps(RUN).encode()), (401, b"{}"), (500, b"{}")],
    ids=["created", "already-started", "refused", "server-error"],
)
def test_the_real_sender_returns_the_status_prefect_answered(
    local_prefect: LocalPrefect, status: int, body: bytes
) -> None:
    """urllib raises on 4xx/5xx; the sender turns that back into a status for the email rules."""
    local_prefect.status = status
    sent = b'{"parameters": {"publish": true}}'
    headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    assert wd._urllib_post(local_prefect.url, sent, headers) == (status, body)
    [(method, path, received, got_headers)] = local_prefect.seen
    assert (method, path, received) == ("POST", "/create_flow_run", sent)
    assert got_headers["Authorization"] == f"Bearer {KEY}"


def test_the_real_sender_lets_a_dropped_connection_raise(local_prefect: LocalPrefect) -> None:
    """Not a status: the watchdog reports it as "Prefect didn't answer" and fails."""
    local_prefect.status = None
    with pytest.raises(OSError) as caught:
        wd._urllib_post(local_prefect.url, b"{}", {})
    assert not isinstance(caught.value, urllib.error.HTTPError)


@dataclass
class FakeWeb:
    """Prefect and GitHub behind one POST, and GitHub's GET: records each call, answers set ones."""

    prefect: FakePrefect = field(default_factory=FakePrefect)
    dispatch_status: int = 200
    dispatch_reply: dict[str, Any] = field(
        default_factory=lambda: {"workflow_run_id": LOCK_RUN_ID, "run_url": "u", "html_url": "h"}
    )
    dispatch_raises: Exception | None = None
    run_status: int = 200
    run: dict[str, Any] = field(
        default_factory=lambda: {
            "id": LOCK_RUN_ID,
            "status": "completed",
            "conclusion": "success",
            "path": f".github/workflows/{WORKFLOW}",
            "html_url": "https://github.com/siddharthps/pm25-forecast/actions/runs/45500000001",
        }
    )
    dispatches: list[tuple[str, dict[str, Any], dict[str, str]]] = field(default_factory=list)
    reads: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def post(self, url: str, body: bytes, headers: Mapping[str, str]) -> tuple[int, bytes]:
        if not url.startswith("https://api.github.com/"):
            return self.prefect(url, body, headers)
        self.dispatches.append((url, json.loads(body), dict(headers)))
        if self.dispatch_raises is not None:
            raise self.dispatch_raises
        return self.dispatch_status, json.dumps(self.dispatch_reply).encode()

    def get(self, url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        self.reads.append((url, dict(headers)))
        return self.run_status, json.dumps(self.run).encode()


def _monday(
    aws: Aws, event: dict[str, Any], web: FakeWeb, now: datetime | None = None
) -> dict[str, Any]:
    clients = wd.Clients(s3=aws.s3, ssm=aws.ssm, sns=aws.sns, post=web.post, get=web.get)
    at = now or datetime(2026, 11, 30, 15, 30, tzinfo=UTC)
    return wd.handle(event, config=_config(aws), aws=clients, now=at)


MON_RETRY = {"mode": "retry", "scheduled_time": MON_0800}
MON_VERIFY = {"mode": "verify", "scheduled_time": MON_0900}
DISPATCH_KEY = f"reports/lock-runs/date={MONDAY}/dispatch.json"
RUN_KEY = f"reports/lock-runs/date={MONDAY}/run.json"


def _put_lock_run(aws: Aws, run_id: int = LOCK_RUN_ID) -> None:
    body = json.dumps({"run_id": run_id, "dispatched_utc": "2026-11-30T14:00:00+00:00"})
    aws.s3.put_object(Bucket=BUCKET, Key=RUN_KEY, Body=body.encode())


@pytest.mark.parametrize("event", [RETRY, VERIFY], ids=["retry-0800", "verify-0900"])
def test_not_monday_means_no_github_call(aws: Aws, event: dict[str, Any]) -> None:
    _put_record(aws)
    web = FakeWeb()
    result = _monday(aws, event, web, now=datetime(2026, 11, 21, 15, 30, tzinfo=UTC))
    assert result["lock"] == "not due"
    assert (web.dispatches, web.reads) == ([], [])
    assert aws.emails() == []


def test_monday_0800_dispatches_the_lock_workflow_once_and_records_its_run(aws: Aws) -> None:
    _put_record(aws, MONDAY + timedelta(days=1))
    web = FakeWeb()
    result = _monday(aws, MON_RETRY, web)
    assert (result["record"], result["lock"], result["lock_run_id"]) == (
        "present",
        "dispatched",
        LOCK_RUN_ID,
    )
    [(url, body, headers)] = web.dispatches
    assert url == f"https://api.github.com/repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches"
    assert body == {"ref": "main"}
    assert headers["Authorization"] == f"Bearer {GH_TOKEN}"
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2026-03-10"
    stored = json.loads(aws.s3.get_object(Bucket=BUCKET, Key=RUN_KEY)["Body"].read())
    assert stored["run_id"] == LOCK_RUN_ID
    assert web.prefect.calls == []
    assert aws.emails() == []


def test_a_second_monday_0800_call_dispatches_nothing(aws: Aws) -> None:
    _put_record(aws, MONDAY + timedelta(days=1))
    web = FakeWeb()
    _monday(aws, MON_RETRY, web)
    again = _monday(aws, MON_RETRY, web)
    assert again["lock"] == "already dispatched"
    assert len(web.dispatches) == 1


def test_the_marker_is_written_before_the_dispatch(aws: Aws) -> None:
    """Record before the outward action: a dispatch that fails still uses up the week."""
    _put_record(aws, MONDAY + timedelta(days=1))
    web = FakeWeb(dispatch_raises=TimeoutError("timed out at a URL"))
    with pytest.raises(wd.WatchdogError, match="GitHub didn't answer: TimeoutError"):
        _monday(aws, MON_RETRY, web)
    assert wd._exists(aws.s3, BUCKET, DISPATCH_KEY)
    assert not wd._exists(aws.s3, BUCKET, RUN_KEY)
    [email] = aws.emails()
    assert "lock run NOT started" in email["subject"]
    assert "gh workflow run uv-lock-upgrade.yml" in email["message"]
    assert "timed out at a URL" not in email["message"]
    again = FakeWeb()
    assert _monday(aws, MON_RETRY, again)["lock"] == "already dispatched"
    assert again.dispatches == []


@pytest.mark.parametrize("status", [204, 401, 403, 404, 422, 500])
def test_a_refused_dispatch_emails_and_fails(aws: Aws, status: int) -> None:
    _put_record(aws, MONDAY + timedelta(days=1))
    with pytest.raises(wd.WatchdogError, match=f"HTTP {status}"):
        _monday(aws, MON_RETRY, FakeWeb(dispatch_status=status))
    [email] = aws.emails()
    assert f"HTTP {status}" in email["message"]


def test_a_dispatch_reply_without_a_run_id_emails_and_fails(aws: Aws) -> None:
    _put_record(aws, MONDAY + timedelta(days=1))
    with pytest.raises(wd.WatchdogError, match="run ID"):
        _monday(aws, MON_RETRY, FakeWeb(dispatch_reply={"run_url": "u"}))
    assert len(aws.emails()) == 1


def test_a_missing_github_token_emails_and_fails_closed(aws: Aws) -> None:
    _put_record(aws, MONDAY + timedelta(days=1))
    aws.ssm.delete_parameter(Name=GH_PARAM)
    web = FakeWeb()
    with pytest.raises(wd.WatchdogError, match="GitHub token: ParameterNotFound"):
        _monday(aws, MON_RETRY, web)
    assert web.dispatches == []
    [email] = aws.emails()
    assert "ParameterNotFound" in email["message"]


def test_monday_0900_with_a_successful_run_is_silent(aws: Aws) -> None:
    _put_record(aws, MONDAY + timedelta(days=1))
    _put_lock_run(aws)
    web = FakeWeb()
    result = _monday(aws, MON_VERIFY, web)
    assert result["lock"] == "succeeded"
    [(url, headers)] = web.reads
    assert url == f"https://api.github.com/repos/{REPO}/actions/runs/{LOCK_RUN_ID}"
    assert headers["Authorization"] == f"Bearer {GH_TOKEN}"
    assert web.dispatches == []
    assert aws.emails() == []


@pytest.mark.parametrize(
    ("status", "conclusion", "shown"),
    [
        ("completed", "failure", "failure"),
        ("completed", "cancelled", "cancelled"),
        ("in_progress", None, "in_progress"),
        ("queued", None, "queued"),
    ],
)
def test_monday_0900_with_a_run_not_succeeded_emails(
    aws: Aws, status: str, conclusion: str | None, shown: str
) -> None:
    _put_record(aws, MONDAY + timedelta(days=1))
    _put_lock_run(aws)
    web = FakeWeb()
    web.run.update(status=status, conclusion=conclusion)
    result = _monday(aws, MON_VERIFY, web)
    assert result["lock"] == shown
    [email] = aws.emails()
    assert f"weekly lock run {shown}" in email["subject"]
    assert "actions/runs/45500000001" in email["message"]


def test_monday_0900_with_no_recorded_run_emails(aws: Aws) -> None:
    _put_record(aws, MONDAY + timedelta(days=1))
    web = FakeWeb()
    result = _monday(aws, MON_VERIFY, web)
    assert result["lock"] == "missing"
    assert web.reads == []
    [email] = aws.emails()
    assert "weekly lock run missing" in email["subject"]


def test_monday_0900_refuses_a_run_from_another_workflow(aws: Aws) -> None:
    _put_record(aws, MONDAY + timedelta(days=1))
    _put_lock_run(aws)
    web = FakeWeb()
    web.run["path"] = ".github/workflows/ci.yml"
    with pytest.raises(wd.WatchdogError, match="isn't the lock workflow"):
        _monday(aws, MON_VERIFY, web)
    assert len(aws.emails()) == 1


@pytest.mark.parametrize("status", [401, 404, 500])
def test_monday_0900_when_github_wont_return_the_run_emails_and_fails(
    aws: Aws, status: int
) -> None:
    _put_record(aws, MONDAY + timedelta(days=1))
    _put_lock_run(aws)
    with pytest.raises(wd.WatchdogError, match=f"HTTP {status}"):
        _monday(aws, MON_VERIFY, FakeWeb(run_status=status))
    assert len(aws.emails()) == 1


def test_a_failed_forecast_retry_never_skips_the_lock_dispatch(aws: Aws) -> None:
    web = FakeWeb(prefect=FakePrefect(status=500))
    with pytest.raises(wd.WatchdogError, match="Prefect refused"):
        _monday(aws, MON_RETRY, web)
    assert len(web.dispatches) == 1
    assert wd._exists(aws.s3, BUCKET, RUN_KEY)
    [email] = aws.emails()
    assert "retry FAILED" in email["subject"]


def test_a_failed_lock_dispatch_never_skips_the_forecast_retry(aws: Aws) -> None:
    web = FakeWeb(dispatch_status=500)
    with pytest.raises(wd.WatchdogError, match="GitHub refused"):
        _monday(aws, MON_RETRY, web)
    assert len(web.prefect.calls) == 1
    subjects = sorted(e["subject"] for e in aws.emails())
    assert len(subjects) == 2
    assert any("retry started" in s for s in subjects)
    assert any("lock run NOT started" in s for s in subjects)


def test_a_failed_lock_check_never_skips_the_forecast_verify(aws: Aws) -> None:
    _put_lock_run(aws)
    web = FakeWeb(run_status=500)
    with pytest.raises(wd.WatchdogError, match="HTTP 500"):
        _monday(aws, MON_VERIFY, web)
    subjects = [e["subject"] for e in aws.emails()]
    assert any("still missing" in s for s in subjects)
    assert any("watchdog error" in s for s in subjects)


def test_both_checks_failing_raises_the_first_and_emails_both(aws: Aws) -> None:
    web = FakeWeb(prefect=FakePrefect(status=500), dispatch_status=403)
    with pytest.raises(wd.WatchdogError, match="Prefect refused"):
        _monday(aws, MON_RETRY, web)
    assert len(aws.emails()) == 2


def test_a_drill_dispatch_keeps_its_own_marker(aws: Aws) -> None:
    """A drill on a coming Monday never uses up that week's real dispatch."""
    web = FakeWeb()
    drill = {**MON_RETRY, "drill": True}
    result = _monday(aws, drill, web, now=datetime(2026, 11, 29, 20, tzinfo=UTC))
    assert result["lock"] == "dispatched"
    assert wd._exists(aws.s3, BUCKET, f"reports/lock-runs/date={MONDAY}/dispatch-drill.json")
    assert not wd._exists(aws.s3, BUCKET, DISPATCH_KEY)
    assert all("DRILL" in e["subject"] for e in aws.emails())


@pytest.mark.usefixtures("lambda_logging")
def test_the_github_token_never_reaches_an_email_or_log(
    aws: Aws, caplog: pytest.LogCaptureFixture
) -> None:
    """Root at DEBUG, as the Prefect key's test: the SDK's own lines stay at WARNING."""
    caplog.set_level(logging.DEBUG)
    web = FakeWeb(dispatch_status=401, prefect=FakePrefect(status=500))
    with pytest.raises(wd.WatchdogError):
        _monday(aws, MON_RETRY, web)
    _put_lock_run(aws)
    with pytest.raises(wd.WatchdogError):
        _monday(aws, MON_VERIFY, FakeWeb(run_status=401))
    text = json.dumps(aws.emails()) + caplog.text
    assert GH_TOKEN not in text
    assert KEY not in text
