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

    airnow_api_key: Secret
    aqs_email: Secret
    aqs_api_key: Secret

    aws_profile: str | None = None
    aws_region: AwsRegion = "us-east-1"

    city_tz: Zone = ZoneInfo("America/Phoenix")
    city_cbsa: Cbsa = "38060"

    data_bucket: BucketName = "pm25-forecast-data-65bc08"
    public_bucket: BucketName = "pm25-forecast-public-65bc08"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Read and validate the settings once per process."""
    return Settings()
