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
AQS_ENV = {"AQS_API_KEY": AQS_KEY, "AQS_EMAIL": AQS_EMAIL}
ALL_ENV = {"AIRNOW_API_KEY": AIRNOW} | AQS_ENV


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """A clean environment with every secret set, and no .env file read."""
    for name in [*ALL_ENV, "AWS_PROFILE", "AWS_REGION", "CITY_TZ", "CITY_CBSA", "DATA_BUCKET"]:
        monkeypatch.delenv(name, raising=False)
    for name, value in ALL_ENV.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    return monkeypatch


def _settings() -> Settings:
    return Settings(_env_file=None)


@pytest.mark.usefixtures("env")
def test_reads_the_environment() -> None:
    s = _settings()
    assert s.airnow_api_key is not None
    assert s.airnow_api_key.get_secret_value() == AIRNOW
    assert s.aqs_credentials() == {"email": AQS_EMAIL, "key": AQS_KEY}
    assert s.aws_region == "us-east-1"
    assert s.city_tz == ZoneInfo("America/Phoenix")
    assert s.city_cbsa == "38060"
    assert s.data_bucket == "pm25-forecast-data-65bc08"
    assert s.public_bucket == "pm25-forecast-public-65bc08"


@pytest.mark.usefixtures("env")
def test_secrets_never_appear_in_repr_str_dump_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    s = _settings()
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("test").info("settings: %s / %r", s, s)
    shown = [repr(s), str(s), s.model_dump_json(), str(s.model_dump()), caplog.text]
    for text in shown:
        for secret in SECRETS:
            assert secret not in text


def test_the_daily_forecast_needs_no_secret(env: pytest.MonkeyPatch) -> None:
    """AirNow's hourly files are public and AWS access is federated (D-040): nothing to hold."""
    for name in ALL_ENV:
        env.delenv(name)
    s = _settings()
    assert (s.airnow_api_key, s.aqs_email, s.aqs_api_key) == (None, None, None)


@pytest.mark.parametrize("missing", sorted(AQS_ENV))
def test_asking_for_aqs_credentials_without_them_fails_clearly(
    env: pytest.MonkeyPatch, missing: str
) -> None:
    env.delenv(missing)
    with pytest.raises(RuntimeError, match="AQS_EMAIL and AQS_API_KEY") as info:
        _settings().aqs_credentials()
    for secret in SECRETS:
        assert secret not in str(info.value)


@pytest.mark.parametrize("name", sorted(ALL_ENV))
def test_an_empty_secret_fails_without_echoing_any_secret(
    env: pytest.MonkeyPatch, name: str
) -> None:
    env.setenv(name, "")
    with pytest.raises(ValidationError) as info:
        _settings()
    for secret in SECRETS:
        assert secret not in str(info.value)


def test_an_invalid_value_error_hides_the_input(env: pytest.MonkeyPatch) -> None:
    """A key pasted into the wrong variable must not reach a log through the error."""
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


@pytest.mark.parametrize("bad", ["3806", "380600", "38O60", ""])
def test_city_cbsa_must_be_five_digits(env: pytest.MonkeyPatch, bad: str) -> None:
    env.setenv("CITY_CBSA", bad)
    with pytest.raises(ValidationError):
        _settings()


@pytest.mark.usefixtures("env")
def test_city_tz_rejects_a_non_string() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, city_tz=-6)  # type: ignore[arg-type]


@pytest.mark.usefixtures("env")
def test_settings_are_frozen() -> None:
    s = _settings()
    with pytest.raises(ValidationError):
        s.aws_region = "eu-west-1"  # type: ignore[misc]


@pytest.mark.usefixtures("env")
def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_importing_config_reads_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """No import-time side effects: with no variables set, importing must still succeed."""
    for name in [*ALL_ENV, "AWS_PROFILE", "AWS_REGION", "CITY_TZ", "CITY_CBSA", "DATA_BUCKET"]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    importlib.reload(config)
    assert not hasattr(config, "settings")
