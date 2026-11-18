"""Settings (#7, T3): validated at construction, secrets never shown, nothing read at import."""

import importlib
import logging
import pathlib
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from airwatch import config
from airwatch.config import Settings, get_settings

AIRNOW = "airnow-test-value-7f3a"
AQS_KEY = "aqs-test-value-91c2"
AQS_EMAIL = "someone@example.invalid"
SECRETS = (AIRNOW, AQS_KEY, AQS_EMAIL)
REQUIRED_ENV = {"AIRNOW_API_KEY": AIRNOW, "AQS_API_KEY": AQS_KEY, "AQS_EMAIL": AQS_EMAIL}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """A clean environment with only the required variables, and no .env file read."""
    for name in [*REQUIRED_ENV, "AWS_PROFILE", "AWS_REGION", "CITY_TZ"]:
        monkeypatch.delenv(name, raising=False)
    for name, value in REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    return monkeypatch


def _settings() -> Settings:
    return Settings(_env_file=None)


@pytest.mark.usefixtures("env")
def test_reads_the_environment() -> None:
    s = _settings()
    assert s.airnow_api_key.get_secret_value() == AIRNOW
    assert s.aqs_api_key.get_secret_value() == AQS_KEY
    assert s.aqs_email.get_secret_value() == AQS_EMAIL
    assert s.aws_region == "us-east-1"
    assert s.city_tz == ZoneInfo("America/Chicago")


@pytest.mark.usefixtures("env")
def test_secrets_never_appear_in_repr_str_dump_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    s = _settings()
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("test").info("settings: %s / %r", s, s)
    shown = [repr(s), str(s), s.model_dump_json(), str(s.model_dump()), caplog.text]
    for text in shown:
        for secret in SECRETS:
            assert secret not in text


@pytest.mark.parametrize("missing", sorted(REQUIRED_ENV))
def test_a_missing_secret_fails_at_startup(env: pytest.MonkeyPatch, missing: str) -> None:
    env.delenv(missing)
    with pytest.raises(ValidationError):
        _settings()


@pytest.mark.parametrize("name", sorted(REQUIRED_ENV))
def test_an_empty_secret_fails_without_echoing_any_secret(
    env: pytest.MonkeyPatch, name: str
) -> None:
    env.setenv(name, "")
    with pytest.raises(ValidationError) as info:
        _settings()
    for secret in SECRETS:
        assert secret not in str(info.value)


def test_an_invalid_value_error_hides_the_input(env: pytest.MonkeyPatch) -> None:
    # Validation errors normally echo the input; settings errors must not (a key pasted into the
    # wrong variable would otherwise end up in a log).
    env.setenv("CITY_TZ", AIRNOW)
    with pytest.raises(ValidationError) as info:
        _settings()
    assert AIRNOW not in str(info.value)


def test_city_tz_must_be_a_real_zone(env: pytest.MonkeyPatch) -> None:
    env.setenv("CITY_TZ", "America/Denver")
    assert _settings().city_tz == ZoneInfo("America/Denver")
    env.setenv("CITY_TZ", "Mars/Olympus_Mons")
    with pytest.raises(ValidationError):
        _settings()


@pytest.mark.usefixtures("env")
def test_city_tz_rejects_a_non_string() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, city_tz=-6)  # type: ignore[arg-type]  # the point: wrong type


@pytest.mark.usefixtures("env")
def test_settings_are_frozen() -> None:
    s = _settings()
    with pytest.raises(ValidationError):
        s.aws_region = "eu-west-1"  # type: ignore[misc]  # the point: frozen at runtime too


@pytest.mark.usefixtures("env")
def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_importing_config_reads_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    # No import-time side effects: with no variables set, importing must still succeed.
    for name in [*REQUIRED_ENV, "AWS_PROFILE", "AWS_REGION", "CITY_TZ"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # and no .env file in reach
    importlib.reload(config)
    assert not hasattr(config, "settings")
