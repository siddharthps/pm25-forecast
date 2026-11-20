"""Typed settings: the only place that reads the environment (SPEC § Structure).

Nothing is read at import time. Call `get_settings()` at the start of a run: it reads the
environment (and a local `.env`, if present) once, validates everything, and fails fast.

Secrets are `SecretStr`: they show as `**********` in `repr`, `str`, dumps and logs. Validation
errors never echo input values, so a key pasted into the wrong variable can't leak into a log.
The AQS email is personal data, so it's treated as a secret too.
"""

from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BeforeValidator, Field, SecretStr, StringConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]


def _zone(value: object) -> ZoneInfo:
    if isinstance(value, ZoneInfo):
        return value
    if not isinstance(value, str):
        raise ValueError("must be an IANA time zone name")
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("not a known IANA time zone name") from exc


Zone = Annotated[ZoneInfo, BeforeValidator(_zone)]
Secret = Annotated[SecretStr, Field(min_length=1)]
AwsRegion = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}(-[a-z]+)+-\d$")]
Cbsa = Annotated[str, StringConstraints(pattern=r"^\d{5}$")]
BucketName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")]


class Settings(BaseSettings):
    """Every setting the pipeline reads. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
        arbitrary_types_allowed=True,
    )

    # EPA AirNow API (live observations).
    airnow_api_key: Secret
    # EPA AQS Data Mart API (validated history): registered email plus key.
    aqs_email: Secret
    aqs_api_key: Secret

    # AWS: no keys here. Locally an SSO profile; in the cloud the runtime's own credentials.
    aws_profile: str | None = None
    aws_region: AwsRegion = "us-east-1"

    # The forecast city (D-030: Phoenix, chosen by the frozen D-006 check). Its zone sets local
    # calendar days (D-005). The issue time's zone is separate and frozen (timeutil.ISSUE_TZ,
    # America/Chicago, D-019).
    city_tz: Zone = ZoneInfo("America/Phoenix")
    city_cbsa: Cbsa = "38060"

    # The private data bucket from T3b (Terraform output `private_bucket`; D-028). Never public.
    data_bucket: BucketName = "pm25-forecast-data-65bc08"
    # The public bucket (Terraform output `public_bucket`; D-028): derived JSON for the page only.
    public_bucket: BucketName = "pm25-forecast-public-65bc08"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Read and validate the settings once per process."""
    return Settings()
