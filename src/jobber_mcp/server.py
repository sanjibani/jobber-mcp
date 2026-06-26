"""Jobber MCP server.

Exposes Jobber's GraphQL API as MCP tools for home-service businesses.
Read clients, jobs, quotes, invoices; create new clients and add notes.

Quick start:
    pip install -e .
    export JOBBER_ACCESS_TOKEN=...
    jobber_mcp
"""
from __future__ import annotations

import json
import sys
from typing import Any

import structlog
from mcp.server.fastmcp import FastMCP

from .client import JobberClient
from .exceptions import (
    JobberAPIError,
    JobberAuthError,
    JobberConnectionError,
    JobberError,
    JobberNotFoundError,
    JobberRateLimitError,
)

log = structlog.get_logger(__name__)


def _format_error(e: Exception) -> str:
    if isinstance(e, JobberAuthError):
        return (
            "Authentication failed against Jobber. Check JOBBER_ACCESS_TOKEN. "
            "Tokens expire — re-run the OAuth flow at https://developer.getjobber.com/docs/. "
            f"Details: {e}"
        )
    if isinstance(e, JobberNotFoundError):
        return f"Resource not found: {e}"
    if isinstance(e, JobberRateLimitError):
        wait = f" Retry in {e.retry_after}s." if e.retry_after else ""
        return f"Jobber rate limit hit.{wait} Slow down."
    if isinstance(e, JobberConnectionError):
        return f"Network failure talking to Jobber: {e}"
    if isinstance(e, JobberAPIError):
        request_id = f" (request_id: {e.request_id})" if e.request_id else ""
        gql = f" (graphql_errors: {len(e.graphql_errors)})" if e.graphql_errors else ""
        return f"Jobber API error (HTTP {e.http_status}){request_id}{gql}: {e}"
    if isinstance(e, JobberError):
        return f"Jobber error: {e}"
    return f"Unexpected error: {e!r}"


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, default=str, ensure_ascii=False)


mcp = FastMCP(
    "jobber_mcp",
    instructions=(
        "Tools for Jobber — home service business management (HVAC, plumbing, "
        "landscaping, etc.). Read clients, jobs, quotes, invoices; create clients "
        "and add notes. Auth: OAuth2 bearer token passed via JOBBER_ACCESS_TOKEN env var."
    ),
)


def _client() -> JobberClient:
    return JobberClient()


# ----- Read tools -----------------------------------------------------------


@mcp.tool()
async def list_clients(limit: int = 25) -> str:
    """List clients (homeowners/businesses you service) with their contact info."""
    try:
        return _json(await _client().list_clients(first=limit))
    except JobberError as e:
        return _format_error(e)


@mcp.tool()
async def list_jobs(limit: int = 25, status: str | None = None) -> str:
    """List jobs (work orders).

    Optional status filter — common values: ``active``, ``awaiting``,
    ``completed``, ``canceled``, ``needsAttention``.
    """
    try:
        return _json(await _client().list_jobs(first=limit, status=status))
    except JobberError as e:
        return _format_error(e)


@mcp.tool()
async def list_quotes(limit: int = 25, status: str | None = None) -> str:
    """List quotes with optional status filter.

    Common statuses: ``awaiting_response``, ``approved``, ``declined``,
    ``converted``, ``expires``.
    """
    try:
        return _json(await _client().list_quotes(first=limit, status=status))
    except JobberError as e:
        return _format_error(e)


@mcp.tool()
async def list_invoices(limit: int = 25, status: str | None = None) -> str:
    """List invoices with optional status filter."""
    try:
        return _json(await _client().list_invoices(first=limit, status=status))
    except JobberError as e:
        return _format_error(e)


@mcp.tool()
async def health_check() -> str:
    """Verify the access token is valid by listing 1 client."""
    try:
        await _client().list_clients(first=1)
        return _json({"status": "ok"})
    except JobberError as e:
        return _format_error(e)


# ----- Write tools ----------------------------------------------------------


@mcp.tool()
async def create_client(
    first_name: str,
    last_name: str,
    company_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> str:
    """Create a new client (homeowner / business).

    App-created clients are automatically tagged with your app's name in
    Jobber's Lead source field — this is the only way leads enter the
    system via your integration.
    """
    try:
        return _json(await _client().create_client(
            first_name=first_name,
            last_name=last_name,
            company_name=company_name,
            email=email,
            phone=phone,
        ))
    except JobberError as e:
        return _format_error(e)


@mcp.tool()
async def add_client_note(client_id: str, body: str, pinned: bool = False) -> str:
    """Add a note to a client's record. Useful after a phone call or site visit."""
    try:
        return _json(await _client().create_note(client_id=client_id, body=body, pinned=pinned))
    except JobberError as e:
        return _format_error(e)


def main() -> None:
    try:
        mcp.run()
    except JobberAuthError as e:
        log.error("server.auth_failed_on_start", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
