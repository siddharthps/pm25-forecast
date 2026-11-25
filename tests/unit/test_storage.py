"""S3 storage (#13, T6): plain get/put, and create-only-if-absent for the durable record.

S3's documented behaviour (conditional writes, read 2026-11-19; D-034):

- `If-None-Match: *` on PutObject writes only if the key has no current version; otherwise 412.
- Two racing writes: the first to finish wins, the others get 412.
- 409 means a delete raced the write; the docs say to retry.

moto enforces the 412 (checked 2026-11-19); the 409 path is faked.
"""

from collections.abc import Iterator
from typing import Any, cast

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from airwatch.storage import S3Store, WriteConflictError

BUCKET = "test-private-bucket"


@pytest.fixture
def s3() -> Iterator[Any]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        client.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
        yield client


def versions(s3: Any, key: str) -> int:
    return len(s3.list_object_versions(Bucket=BUCKET, Prefix=key).get("Versions", []))


def test_get_returns_none_for_a_missing_key(s3: Any) -> None:
    assert S3Store(s3, BUCKET).get("nothing/here.json") is None


def test_put_then_get_round_trips(s3: Any) -> None:
    store = S3Store(s3, BUCKET)
    store.put("a/b.json", b"{}")
    assert store.get("a/b.json") == b"{}"


def test_create_writes_once_and_refuses_the_second_time(s3: Any) -> None:
    store = S3Store(s3, BUCKET)
    assert store.create_if_absent("records/x.json", b"first") is True
    assert store.create_if_absent("records/x.json", b"second") is False
    assert store.get("records/x.json") == b"first"
    assert versions(s3, "records/x.json") == 1


class Flaky:
    """A client whose put_object answers 409 for the first `conflicts` calls."""

    def __init__(self, real: Any, conflicts: int) -> None:
        self.real, self.left, self.calls = real, conflicts, 0
        self.exceptions = real.exceptions

    def put_object(self, **kw: Any) -> Any:
        self.calls += 1
        if self.left:
            self.left -= 1
            err = {
                "Error": {"Code": "ConditionalRequestConflict"},
                "ResponseMetadata": {"HTTPStatusCode": 409},
            }
            raise ClientError(err, "PutObject")  # type: ignore[arg-type]
        return self.real.put_object(**kw)


def test_a_409_conflict_is_retried(s3: Any) -> None:
    flaky = Flaky(s3, conflicts=2)
    store = S3Store(cast(Any, flaky), BUCKET, retry_pause_s=0)
    assert store.create_if_absent("records/y.json", b"data") is True
    assert flaky.calls == 3


def test_repeated_409s_give_up_with_an_error_after_three_tries(s3: Any) -> None:
    flaky = Flaky(s3, conflicts=10)
    store = S3Store(cast(Any, flaky), BUCKET, retry_pause_s=0)
    with pytest.raises(WriteConflictError, match=r"\(409\) after 3 attempts$"):
        store.create_if_absent("records/z.json", b"data")
    assert flaky.calls == 3


def test_409_retries_pause_one_second_then_two_by_default(
    s3: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default pause, growing with each try (#140: neither was pinned)."""
    pauses: list[float] = []
    monkeypatch.setattr("airwatch.storage.time.sleep", pauses.append)
    with pytest.raises(WriteConflictError):
        S3Store(cast(Any, Flaky(s3, conflicts=10)), BUCKET).create_if_absent("records/p", b"d")
    assert pauses == [1.0, 2.0]


def test_other_errors_are_not_mistaken_for_an_existing_record(s3: Any) -> None:
    store = S3Store(s3, "no-such-bucket-here")
    with pytest.raises(ClientError):
        store.create_if_absent("records/w.json", b"data")


def test_list_keys_returns_every_key_under_a_prefix_past_one_page(s3: Any) -> None:
    store = S3Store(s3, BUCKET)
    for i in range(1005):
        store.put(f"records/forecast_date=d{i:04d}/forecast.json", b"{}")
    store.put("reports/other.json", b"{}")
    keys = store.list_keys("records/")
    assert len(keys) == 1005
    assert keys == sorted(keys)
    assert all(k.startswith("records/") for k in keys)


@pytest.mark.parametrize(
    ("response", "status"),
    [
        ({"Error": {"Code": "Conflict"}}, None),
        ({"Error": {"Code": "Conflict"}, "ResponseMetadata": {}}, None),
        ({"Error": {"Code": "Conflict"}, "ResponseMetadata": {"HTTPStatusCode": 409}}, 409),
    ],
    ids=["no metadata", "no status", "409"],
)
def test_an_errors_status_is_read_only_when_given(
    response: dict[str, Any], status: int | None
) -> None:
    """Killed mutmut survivors (#112): an AWS error without metadata has no status, not a crash."""
    from airwatch.storage import _status  # noqa: PLC0415  (a private helper, tested alone)

    assert _status(ClientError(cast(Any, response), "PutObject")) == status
