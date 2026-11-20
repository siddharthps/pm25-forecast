"""fetch_json (#9): retries, gives up cleanly, and never leaks credentials (fake transport)."""

import logging

import httpx
import pytest

from airwatch.observations.metadata import fetch_json

SECRET = {"email": "someone@example.invalid", "key": "key-value-3c9d"}
URL = "https://aqs.example.invalid/data/api/list/cbsas"


def client_from(responses: list[int | Exception]) -> tuple[httpx.Client, list[httpx.Request]]:
    """A client whose transport plays `responses` in order: a status code, or an exception."""
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        nxt = queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return httpx.Response(nxt, json={"Data": ["ok"]} if nxt == 200 else {"error": "x"})

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_success_returns_the_json() -> None:
    client, seen = client_from([200])
    assert fetch_json(client, URL, SECRET, backoff_s=0) == {"Data": ["ok"]}
    assert len(seen) == 1


@pytest.mark.parametrize("first", [500, 502, 503, 429, httpx.ConnectError("boom")])
def test_retryable_failures_are_retried(first: int | Exception) -> None:
    client, seen = client_from([first, 200])
    assert fetch_json(client, URL, SECRET, backoff_s=0) == {"Data": ["ok"]}
    assert len(seen) == 2


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_are_not_retried(status: int) -> None:
    client, seen = client_from([status])
    with pytest.raises(RuntimeError, match=str(status)):
        fetch_json(client, URL, SECRET, backoff_s=0)
    assert len(seen) == 1


def test_gives_up_after_the_last_attempt() -> None:
    client, seen = client_from([503, 503, 503])
    with pytest.raises(RuntimeError, match="after 3 attempt"):
        fetch_json(client, URL, SECRET, attempts=3, backoff_s=0)
    assert len(seen) == 3


def test_a_successful_request_logs_no_url_or_credentials(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = client_from([200])
    with caplog.at_level(logging.DEBUG):
        fetch_json(client, URL, SECRET, backoff_s=0)
    for secret in [*SECRET.values(), URL, "aqs.example.invalid"]:
        assert secret not in caplog.text


@pytest.mark.parametrize(
    "responses",
    [[401], [503, 503], [httpx.ConnectError("boom"), httpx.ConnectError("boom")]],
)
def test_failures_never_show_the_url_or_credentials(
    responses: list[int | Exception], caplog: pytest.LogCaptureFixture
) -> None:
    client, _ = client_from(responses)
    with caplog.at_level(logging.DEBUG), pytest.raises(RuntimeError) as info:
        fetch_json(client, URL, SECRET, attempts=2, backoff_s=0)
    shown = str(info.value) + caplog.text + repr(info.value.__cause__)
    for secret in [*SECRET.values(), URL, "aqs.example.invalid"]:
        assert secret not in shown
    assert info.value.__cause__ is None
