"""Async GraphQL client for Jobber.

Uses Jobber's GraphQL API at ``https://api.getjobber.com/api/graphql``.
OAuth2 access tokens come from Jobber's developer console — you'll get one
per install of your app. Tokens can be cached; this client does NOT auto-refresh
(use the refresh_token grant on your backend; the MCP server itself takes a
pre-minted access token via ``JOBBER_ACCESS_TOKEN``).

Built on industry-leading patterns (encode/httpx, stripe-python):
- **Shared ``httpx.AsyncClient``** with connection pooling + transport retries.
- **Typed exception hierarchy** with structured fields. See ``exceptions.py``.
- **Application-level retry** with exponential backoff + full jitter.
- **GraphQL-aware error handling**: HTTP 200 responses with ``errors[]`` are
  surfaced as ``JobberAPIError`` with ``graphql_errors`` populated.

Docs: https://developer.getjobber.com/docs/
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import random
import time
from typing import Any

import httpx
import structlog

from . import __version__
from .exceptions import (
    JobberAPIError,
    JobberAuthError,
    JobberConnectionError,
    JobberError,
    JobberNotFoundError,
    JobberRateLimitError,
)

log = structlog.get_logger(__name__)


# --- Configuration constants -----------------------------------------------

DEFAULT_BASE_URL = "https://api.getjobber.com/api/graphql"
DEFAULT_TIMEOUT = 30.0

# Connection pool sizing
DEFAULT_MAX_CONNECTIONS = 100
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 20
DEFAULT_KEEPALIVE_EXPIRY = 30.0

# Application-level retry
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_RETRY_DELAY = 0.5
DEFAULT_MAX_RETRY_DELAY = 30.0

RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# GraphQL error code patterns that mean "not found"
GQL_NOT_FOUND_PATTERNS = ("not_found", "not found", "record_not_found", "NotFound")


# --- Internal helpers ------------------------------------------------------


def _retry_delay(attempt: int, retry_after: float | None = None) -> float:
    """Exponential backoff with full jitter, clamped to [0.5, 30] seconds."""
    if retry_after is not None:
        return min(float(retry_after), DEFAULT_MAX_RETRY_DELAY)
    delay = min(DEFAULT_BASE_RETRY_DELAY * (2 ** attempt), DEFAULT_MAX_RETRY_DELAY)
    return float(delay * random.uniform(0.5, 1.0))  # full jitter


def _is_not_found_error(graphql_errors: list[dict[str, Any]]) -> bool:
    """Check whether the GraphQL error list looks like a not-found response."""
    for err in graphql_errors:
        msg = str(err.get("message", "")).lower()
        ext = err.get("extensions", {}) or {}
        code = str(ext.get("code", "")).lower()
        if any(p in msg for p in GQL_NOT_FOUND_PATTERNS):
            return True
        if any(p in code for p in GQL_NOT_FOUND_PATTERNS):
            return True
    return False


class JobberClient:
    """Async GraphQL client for Jobber.

    Auth: OAuth2 bearer token (passed in directly). The MCP server reads the
    token from the ``JOBBER_ACCESS_TOKEN`` env var. For multi-tenant apps,
    run multiple MCP server instances — each with its own token.

    Use as an async context manager:

        async with JobberClient() as client:
            clients = await client.list_clients()
    """

    def __init__(
        self,
        access_token: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        token = access_token or os.environ.get("JOBBER_ACCESS_TOKEN")
        if not token:
            raise JobberAuthError(
                "Jobber access token missing. Set JOBBER_ACCESS_TOKEN env var or "
                "pass it to the client. Get one via OAuth2 flow at "
                "https://developer.getjobber.com/docs/"
            )
        assert token is not None
        self._token: str = token
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries

        # Build shared httpx.AsyncClient with pooling + transport retries.
        transport = httpx.AsyncHTTPTransport(retries=3)
        limits = httpx.Limits(
            max_connections=DEFAULT_MAX_CONNECTIONS,
            max_keepalive_connections=DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
            keepalive_expiry=DEFAULT_KEEPALIVE_EXPIRY,
        )
        timeout_obj = httpx.Timeout(
            timeout,
            connect=10.0,
            read=timeout,
            write=10.0,
            pool=5.0,
        )
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_obj,
            limits=limits,
            transport=transport,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": f"jobber-mcp/{__version__}",
            },
            follow_redirects=False,
        )

    # --- Context manager ------------------------------------------------------

    async def __aenter__(self) -> JobberClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- GraphQL error mapping ------------------------------------------------

    def _map_graphql_errors(
        self,
        errors: list[dict[str, Any]],
        data: dict[str, Any] | None,
    ) -> None:
        """Map a GraphQL-level errors[] to the most specific typed exception."""
        if _is_not_found_error(errors):
            raise JobberNotFoundError(
                f"Jobber resource not found: {errors[0].get('message')}",
                http_status=200,
                graphql_errors=errors,
                body=data,
            )
        raise JobberAPIError(
            f"GraphQL errors: {errors}",
            http_status=200,
            graphql_errors=errors,
            body=data,
        )

    def _raise_for_status(self, response: httpx.Response) -> None:
        request_id = (
            response.headers.get("x-request-id")
            or response.headers.get("x-amzn-requestid")
            or response.headers.get("request-id")
        )
        try:
            body = response.json()
        except ValueError:
            body = response.text

        if response.status_code == 401:
            raise JobberAuthError(
                "Jobber rejected the bearer token (HTTP 401). "
                "Token may be expired — re-run the OAuth flow.",
                http_status=401,
                request_id=request_id,
                body=body,
            )
        if response.status_code == 403:
            raise JobberAuthError(
                "Jobber denied access (HTTP 403). "
                "Your app may not have the right scopes for this operation.",
                http_status=403,
                request_id=request_id,
                body=body,
            )
        if response.status_code == 404:
            raise JobberNotFoundError(
                f"Jobber resource not found: {response.url}",
                http_status=404,
                request_id=request_id,
                body=body,
            )
        if response.status_code == 429:
            retry_after: float | None = None
            with contextlib.suppress(ValueError):
                ra_header = response.headers.get("retry-after")
                if ra_header:
                    retry_after = float(ra_header)
            raise JobberRateLimitError(
                "Jobber rate limit hit (HTTP 429). Slow down.",
                retry_after=retry_after,
                request_id=request_id,
                body=body,
            )
        if 500 <= response.status_code < 600:
            raise JobberAPIError(
                f"Jobber server error (HTTP {response.status_code})",
                http_status=response.status_code,
                request_id=request_id,
                body=body,
            )
        raise JobberAPIError(
            f"Jobber returned HTTP {response.status_code}",
            http_status=response.status_code,
            request_id=request_id,
            body=body,
        )

    async def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a GraphQL query/mutation. Returns the ``data`` payload.

        Raises:
            JobberAuthError: on HTTP 401/403.
            JobberNotFoundError: on GraphQL not-found errors (HTTP 200 with errors[]).
            JobberAPIError: on transport errors, 5xx, or other GraphQL errors.
            JobberConnectionError: on network-level failures.
        """
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        last_exc: JobberError | None = None
        for attempt in range(self._max_retries + 1):
            log.info("graphql.start", attempt=attempt, query_chars=len(query))
            t0 = time.monotonic()
            try:
                response = await self._client.post("", json=payload)
            except httpx.HTTPError as exc:
                duration_ms = (time.monotonic() - t0) * 1000
                log.warning(
                    "graphql.connection_error",
                    error=str(exc),
                    duration_ms=round(duration_ms, 1),
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(_retry_delay(attempt))
                    continue
                raise JobberConnectionError(
                    f"Network failure calling Jobber GraphQL: {exc}",
                ) from exc

            duration_ms = (time.monotonic() - t0) * 1000
            log.info(
                "graphql.end",
                status=response.status_code,
                duration_ms=round(duration_ms, 1),
            )

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < self._max_retries:
                retry_after: float | None = None
                with contextlib.suppress(ValueError):
                    ra_header = response.headers.get("retry-after")
                    if ra_header:
                        retry_after = float(ra_header)
                delay = _retry_delay(attempt, retry_after)
                log.warning(
                    "graphql.retry",
                    status=response.status_code,
                    attempt=attempt,
                    delay=round(delay, 2),
                )
                await asyncio.sleep(delay)
                continue

            if 200 <= response.status_code < 300:
                try:
                    data = response.json()
                except ValueError as exc:
                    raise JobberAPIError(
                        f"Jobber returned non-JSON response: {response.text}",
                    ) from exc

                # GraphQL can return 200 with errors[] populated
                if data.get("errors"):
                    self._map_graphql_errors(data["errors"], data.get("data"))

                return data.get("data") or {}

            try:
                self._raise_for_status(response)
            except JobberRateLimitError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    delay = _retry_delay(attempt, exc.retry_after)
                    await asyncio.sleep(delay)
                    continue
                raise
            except (JobberAPIError, JobberAuthError, JobberNotFoundError):
                raise
            except JobberError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(_retry_delay(attempt))
                    continue
                raise

        assert last_exc is not None
        raise last_exc

    # ----- High-level helpers ------------------------------------------------

    async def list_clients(self, first: int = 25) -> dict[str, Any]:
        """List clients with their basic fields."""
        query = """
        query ListClients($first: Int!) {
          clients(first: $first) {
            nodes {
              id
              firstName
              lastName
              companyName
              emails { description address primary }
              phones { description number primary }
              billingAddress { city region country }
            }
            totalCount
          }
        }
        """
        return await self.execute(query, {"first": first})

    async def list_jobs(
        self,
        first: int = 25,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List jobs (work orders) with optional status filter.

        Common statuses: ``active``, ``awaiting``, ``completed``, ``canceled``,
        ``needsAttention``.
        """
        query = """
        query ListJobs($first: Int!, $status: JobStatus) {
          jobs(first: $first, filter: { status: { equalTo: $status } }) {
            nodes {
              id
              title
              description
              jobStatus
              startAt
              endAt
              jobNumber
              client { id firstName lastName companyName }
            }
            totalCount
          }
        }
        """
        return await self.execute(query, {"first": first, "status": status})

    async def list_quotes(
        self,
        first: int = 25,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List quotes with optional status filter.

        Common statuses: ``awaiting_response``, ``approved``, ``declined``,
        ``converted``, ``expires``.
        """
        query = """
        query ListQuotes($first: Int!, $status: QuoteStatus) {
          quotes(first: $first, filter: { quoteStatus: { equalTo: $status } }) {
            nodes {
              id
              title
              quoteStatus
              quoteNumber
              createdAt
              client { id firstName lastName companyName }
            }
            totalCount
          }
        }
        """
        return await self.execute(query, {"first": first, "status": status})

    async def list_invoices(
        self,
        first: int = 25,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List invoices with optional status filter."""
        query = """
        query ListInvoices($first: Int!, $status: InvoiceStatus) {
          invoices(first: $first, filter: { invoiceStatus: { equalTo: $status } }) {
            nodes {
              id
              invoiceNumber
              invoiceStatus
              total
              amountDue
              issueDate
              dueDate
              client { id firstName lastName companyName }
            }
            totalCount
          }
        }
        """
        return await self.execute(query, {"first": first, "status": status})

    async def create_client(
        self,
        first_name: str,
        last_name: str,
        *,
        company_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> dict[str, Any]:
        """Create a new client."""
        mutation = """
        mutation CreateClient($input: ClientCreateInput!) {
          clientCreate(input: $input) {
            client {
              id
              firstName
              lastName
              companyName
              emails { description address primary }
              phones { description number primary }
            }
            userErrors { message path }
          }
        }
        """
        emails = [{"description": "MAIN", "primary": True, "address": email}] if email else None
        phones = [{"description": "MOBILE", "primary": True, "number": phone}] if phone else None
        return await self.execute(mutation, {
            "input": {
                "firstName": first_name,
                "lastName": last_name,
                **({"companyName": company_name} if company_name else {}),
                **({"emails": emails} if emails else {}),
                **({"phones": phones} if phones else {}),
            }
        })

    async def create_note(
        self,
        client_id: str,
        body: str,
        *,
        pinned: bool = False,
    ) -> dict[str, Any]:
        """Add a note to a client record."""
        mutation = """
        mutation CreateNote($input: ClientNoteCreateInput!) {
          clientNoteCreate(input: $input) {
            clientNote { id body createdAt pinned }
            userErrors { message path }
          }
        }
        """
        return await self.execute(mutation, {
            "input": {"clientId": client_id, "body": body, "pinned": pinned}
        })
