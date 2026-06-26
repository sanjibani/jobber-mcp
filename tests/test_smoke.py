"""Smoke tests for jobber-mcp — no live API calls required.

Built with ``respx`` (industry-standard httpx mocking) + ``pytest-asyncio``.
"""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import respx
from hypothesis import given, settings
from hypothesis import strategies as st

from jobber_mcp import (
    JobberAPIError,
    JobberAuthError,
    JobberClient,
    JobberConnectionError,
    JobberNotFoundError,
    JobberRateLimitError,
)
from jobber_mcp.server import _format_error, _json

GRAPHQL_URL = "https://api.getjobber.com/api/graphql/"


# --- Fixtures --------------------------------------------------------------


def _env(monkeypatch: pytest.MonkeyPatch, token: str = "test-tok") -> None:
    monkeypatch.setenv("JOBBER_ACCESS_TOKEN", token)


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[JobberClient]:
    _env(monkeypatch)
    c = JobberClient()
    try:
        yield c
    finally:
        await c.aclose()


# --- Client construction --------------------------------------------------


def test_client_missing_token_raises() -> None:
    os.environ.pop("JOBBER_ACCESS_TOKEN", None)
    with pytest.raises(JobberAuthError):
        JobberClient()


def test_client_uses_env_when_no_args(monkeypatch: pytest.MonkeyPatch) -> None:
    _env(monkeypatch, "my-tok")
    c = JobberClient()
    assert c._token == "my-tok"


@pytest.mark.asyncio
async def test_client_aclose_closes_underlying_httpx_client(client: JobberClient) -> None:
    assert not client._client.is_closed
    await client.aclose()
    assert client._client.is_closed


# --- Request shape ---------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_execute_sends_bearer_and_query(client: JobberClient) -> None:
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
        200, json={"data": {"clients": {"nodes": []}}}
    )
    )
    await client.execute("query { clients { nodes { id } } }")
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-tok"
    body = json.loads(route.calls[0].request.content)
    assert body["query"] == "query { clients { nodes { id } } }"
    assert "variables" not in body


@pytest.mark.asyncio
@respx.mock
async def test_execute_passes_variables(client: JobberClient) -> None:
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
        200, json={"data": {"clients": {"nodes": []}}}
    )
    )
    await client.execute(
        "query($first: Int!) { clients(first: $first) { nodes { id } } }",
        {"first": 10},
    )
    body = json.loads(route.calls[0].request.content)
    assert body["variables"] == {"first": 10}


@pytest.mark.asyncio
@respx.mock
async def test_execute_returns_data_payload(client: JobberClient) -> None:
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"clients": {"nodes": [{"id": "c1"}], "totalCount": 1}}},
        )
    )
    result = await client.list_clients()
    assert result["clients"]["nodes"] == [{"id": "c1"}]
    assert result["clients"]["totalCount"] == 1


# --- HTTP status code mapping ---------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_401_raises_auth_error(client: JobberClient) -> None:
    respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(401, text=""))
    with pytest.raises(JobberAuthError) as exc_info:
        await client.list_clients()
    assert exc_info.value.http_status == 401
    assert "OAuth" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_403_raises_auth_error(client: JobberClient) -> None:
    respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(403, text=""))
    with pytest.raises(JobberAuthError) as exc_info:
        await client.list_clients()
    assert exc_info.value.http_status == 403


@pytest.mark.asyncio
@respx.mock
async def test_429_includes_retry_after(client: JobberClient) -> None:
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(429, headers={"retry-after": "2.5"}, text="slow")
    )
    with pytest.raises(JobberRateLimitError) as exc_info:
        await client.list_clients()
    assert exc_info.value.retry_after == 2.5


@pytest.mark.asyncio
@respx.mock
async def test_500_captures_request_id(client: JobberClient) -> None:
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(500, headers={"x-request-id": "req-abc"}, text="boom")
    )
    with pytest.raises(JobberAPIError) as exc_info:
        await client.list_clients()
    assert exc_info.value.request_id == "req-abc"


@pytest.mark.asyncio
@respx.mock
async def test_connection_error_wrapped(client: JobberClient) -> None:
    respx.post(GRAPHQL_URL).mock(side_effect=httpx.ConnectError("DNS failure"))
    with pytest.raises(JobberConnectionError):
        await client.list_clients()


# --- GraphQL-level error handling (the special bit) ------------------------


@pytest.mark.asyncio
@respx.mock
async def test_graphql_not_found_message_raises_not_found(client: JobberClient) -> None:
    """Jobber returns HTTP 200 with errors[] containing 'not found' patterns."""
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": None,
                "errors": [{"message": "Record not found", "extensions": {"code": "NOT_FOUND"}}],
            },
        )
    )
    with pytest.raises(JobberNotFoundError) as exc_info:
        await client.list_clients()
    assert exc_info.value.http_status == 200
    assert exc_info.value.graphql_errors is not None
    assert exc_info.value.graphql_errors[0]["message"] == "Record not found"


@pytest.mark.asyncio
@respx.mock
async def test_graphql_validation_error_raises_api_error(client: JobberClient) -> None:
    """GraphQL validation errors (not 'not found') raise JobberAPIError."""
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": None,
                "errors": [
                    {
                        "message": "Variable $first must be Int",
                        "extensions": {"code": "VALIDATION"},
                    }
                ],
            },
        )
    )
    with pytest.raises(JobberAPIError) as exc_info:
        await client.list_clients()
    assert exc_info.value.http_status == 200
    assert "Variable" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_graphql_non_json_response_raises_api_error(client: JobberClient) -> None:
    respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )
    with pytest.raises(JobberAPIError, match="non-JSON"):
        await client.list_clients()


# --- Retry with exponential backoff ---------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_429_is_retried_then_raises(client: JobberClient) -> None:
    route = respx.post(GRAPHQL_URL).mock(return_value=httpx.Response(429, text="slow"))
    client._max_retries = 2
    with pytest.raises(JobberRateLimitError):
        await client.list_clients()
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_5xx_eventually_succeeds_after_retry(client: JobberClient) -> None:
    route = respx.post(GRAPHQL_URL).mock(
        side_effect=[
            httpx.Response(502, text="bad gateway"),
            httpx.Response(503, text="unavailable"),
            httpx.Response(200, json={"data": {"clients": {"nodes": []}}}),
        ]
    )
    client._max_retries = 3
    result = await client.list_clients()
    assert result == {"clients": {"nodes": []}}
    assert route.call_count == 3


# --- Mutations (write) -----------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_create_client_sends_mutation(client: JobberClient) -> None:
    route = respx.post(GRAPHQL_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "clientCreate": {
                        "client": {"id": "c1", "firstName": "Sarah", "lastName": "Lee"},
                        "userErrors": [],
                    }
                }
            },
        )
    )
    result = await client.create_client("Sarah", "Lee", email="sarah@example.com")
    assert result["clientCreate"]["client"]["firstName"] == "Sarah"
    body = json.loads(route.calls[0].request.content)
    assert "mutation CreateClient" in body["query"]
    assert body["variables"]["input"]["firstName"] == "Sarah"
    assert body["variables"]["input"]["emails"][0]["address"] == "sarah@example.com"


# --- Property-based test --------------------------------------------------


@given(st.dictionaries(st.text(min_size=1), st.integers() | st.text() | st.booleans(), max_size=10))
@settings(max_examples=50, deadline=None)
def test_json_serialization_round_trip(d: dict[str, Any]) -> None:
    try:
        json.loads(_json(d))
    except (TypeError, ValueError):
        pytest.skip("non-JSON value")
    assert json.loads(_json(d)) == d


# --- Server error helpers -------------------------------------------------


def test_format_error_auth_suggests_oauth_flow() -> None:
    msg = _format_error(JobberAuthError("bad"))
    assert "JOBBER_ACCESS_TOKEN" in msg
    assert "OAuth" in msg


def test_format_error_404_says_not_found() -> None:
    msg = _format_error(JobberNotFoundError("missing"))
    assert "not found" in msg.lower()


def test_format_error_429_includes_retry_after() -> None:
    msg = _format_error(JobberRateLimitError("slow", retry_after=5.0))
    assert "Retry in 5.0s" in msg or "Retry in 5s" in msg


def test_format_error_api_includes_graphql_count() -> None:
    err = JobberAPIError("boom", graphql_errors=[{"message": "x"}])
    msg = _format_error(err)
    assert "graphql_errors: 1" in msg


def test_format_error_connection_says_network() -> None:
    msg = _format_error(JobberConnectionError("dns"))
    assert "network" in msg.lower()


def test_format_error_generic() -> None:
    msg = _format_error(ValueError("nope"))
    assert "Unexpected" in msg


def test_error_repr_includes_structured_fields() -> None:
    err = JobberAPIError("boom", http_status=200, error_code="oops", request_id="req-1")
    r = repr(err)
    assert "http_status=200" in r
    assert "error_code='oops'" in r
    assert "request_id='req-1'" in r
