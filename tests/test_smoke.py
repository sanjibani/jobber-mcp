"""Smoke tests for jobber-mcp — no live API calls required."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from jobber_mcp import JobberAPIError, JobberAuthError, JobberClient
from jobber_mcp.server import _format_error, _json


# ----- Client construction --------------------------------------------------


def test_client_missing_token_raises() -> None:
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(JobberAuthError):
            JobberClient()


def test_client_uses_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBBER_ACCESS_TOKEN", "tok-xyz")
    client = JobberClient()
    assert client._token == "tok-xyz"


# ----- Async execution ------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_returns_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBBER_ACCESS_TOKEN", "tok")
    fake_response = AsyncMock()
    fake_response.status_code = 200
    fake_response.json = lambda: {"data": {"clients": {"nodes": [], "totalCount": 0}}}

    fake_http = AsyncMock()
    fake_http.__aenter__ = AsyncMock(return_value=fake_http)
    fake_http.__aexit__ = AsyncMock(return_value=None)
    fake_http.post = AsyncMock(return_value=fake_response)

    with patch("jobber_mcp.client.httpx.AsyncClient", return_value=fake_http):
        client = JobberClient()
        result = await client.list_clients()
        assert result == {"clients": {"nodes": [], "totalCount": 0}}
        args, kwargs = fake_http.post.call_args
        assert args[0] == "https://api.getjobber.com/api/graphql"
        assert kwargs["headers"]["Authorization"] == "Bearer tok"
        assert "query" in kwargs["json"]


@pytest.mark.asyncio
async def test_execute_raises_on_401(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBBER_ACCESS_TOKEN", "tok")
    fake = AsyncMock()
    fake.status_code = 401
    fake.json = lambda: {"errors": ["invalid_request"]}
    fake_http = AsyncMock()
    fake_http.__aenter__ = AsyncMock(return_value=fake_http)
    fake_http.__aexit__ = AsyncMock(return_value=None)
    fake_http.post = AsyncMock(return_value=fake)

    with patch("jobber_mcp.client.httpx.AsyncClient", return_value=fake_http):
        client = JobberClient()
        with pytest.raises(JobberAuthError):
            await client.list_clients()


@pytest.mark.asyncio
async def test_execute_raises_on_graphql_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """GraphQL can return HTTP 200 with errors[] populated — must raise."""
    monkeypatch.setenv("JOBBER_ACCESS_TOKEN", "tok")
    fake = AsyncMock()
    fake.status_code = 200
    fake.json = lambda: {"errors": [{"message": "Field 'foo' not found"}], "data": None}
    fake_http = AsyncMock()
    fake_http.__aenter__ = AsyncMock(return_value=fake_http)
    fake_http.__aexit__ = AsyncMock(return_value=None)
    fake_http.post = AsyncMock(return_value=fake)

    with patch("jobber_mcp.client.httpx.AsyncClient", return_value=fake_http):
        client = JobberClient()
        with pytest.raises(JobberAPIError, match="GraphQL errors"):
            await client.list_clients()


@pytest.mark.asyncio
async def test_create_client_builds_correct_input(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOBBER_ACCESS_TOKEN", "tok")
    fake = AsyncMock()
    fake.status_code = 200
    fake.json = lambda: {"data": {"clientCreate": {"client": {"id": "c1"}}}}
    fake_http = AsyncMock()
    fake_http.__aenter__ = AsyncMock(return_value=fake_http)
    fake_http.__aexit__ = AsyncMock(return_value=None)
    fake_http.post = AsyncMock(return_value=fake)

    with patch("jobber_mcp.client.httpx.AsyncClient", return_value=fake_http):
        client = JobberClient()
        await client.create_client(
            first_name="Jane", last_name="Doe",
            email="jane@example.com", phone="5551234567",
        )
        # Verify the JSON payload sent to GraphQL endpoint
        sent = fake_http.post.call_args.kwargs["json"]
        assert sent["variables"]["input"]["firstName"] == "Jane"
        assert sent["variables"]["input"]["lastName"] == "Doe"
        assert sent["variables"]["input"]["emails"][0]["address"] == "jane@example.com"
        assert sent["variables"]["input"]["phones"][0]["number"] == "5551234567"


# ----- Server helpers -------------------------------------------------------


def test_format_error_auth() -> None:
    msg = _format_error(JobberAuthError("nope", 401))
    assert "Authentication" in msg


def test_format_error_generic() -> None:
    msg = _format_error(ValueError("nope"))
    assert "Unexpected" in msg


def test_json_serializes() -> None:
    assert json.loads(_json({"a": 1})) == {"a": 1}