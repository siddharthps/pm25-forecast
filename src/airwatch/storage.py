"""S3 storage: the few operations the pipeline needs, on one bucket (one home for them).

`create_if_absent` is the at-most-once primitive for the durable record (T6, D-034). It uses
S3's conditional write, `If-None-Match: *`, as AWS documents it (read 2026-11-19):

- the write succeeds only if the key has no current version; otherwise S3 answers **412**;
- of two racing writes, the first to finish wins and the others get 412;
- **409** means a delete raced the write, and the docs say to retry.

On a versioned bucket a delete would reopen the key, so the pipeline has no delete permission
(infra/iam.tf) and no lifecycle rule expires a current record (infra/s3.tf).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

__all__ = ["S3Store"]

HTTP_PRECONDITION_FAILED = 412
HTTP_CONFLICT = 409
CONFLICT_ATTEMPTS = 3


def _status(exc: ClientError) -> int | None:
    meta: dict[str, Any] = exc.response.get("ResponseMetadata", {})  # type: ignore[assignment]
    status = meta.get("HTTPStatusCode")
    return int(status) if status is not None else None


class S3Store:
    """get / put / create_if_absent on one bucket."""

    def __init__(self, client: S3Client, bucket: str, *, retry_pause_s: float = 1.0) -> None:
        self._s3 = client
        self._bucket = bucket
        self._pause = retry_pause_s

    def get(self, key: str) -> bytes | None:
        try:
            body = self._s3.get_object(Bucket=self._bucket, Key=key)["Body"]
        except self._s3.exceptions.NoSuchKey:
            return None
        return body.read()

    def put(self, key: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self._bucket, Key=key, Body=data)

    def create_if_absent(self, key: str, data: bytes) -> bool:
        """Write `data` only if `key` doesn't exist. True if written; False if it already was."""
        for attempt in range(1, CONFLICT_ATTEMPTS + 1):
            try:
                self._s3.put_object(Bucket=self._bucket, Key=key, Body=data, IfNoneMatch="*")
            except ClientError as exc:
                status = _status(exc)
                if status == HTTP_PRECONDITION_FAILED:
                    return False
                if status != HTTP_CONFLICT:
                    raise
                if attempt == CONFLICT_ATTEMPTS:
                    msg = f"conditional write kept conflicting (409) after {attempt} attempts"
                    raise RuntimeError(msg) from None
                time.sleep(self._pause * attempt)
            else:
                return True
        raise AssertionError("unreachable")  # pragma: no cover
