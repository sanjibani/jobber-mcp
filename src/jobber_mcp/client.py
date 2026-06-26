"""Async GraphQL client for Jobber.

Uses Jobber's GraphQL API at ``https://api.getjobber.com/api/graphql``.
OAuth2 access tokens come from Jobber's developer console — you'll get one
per install of your app. Tokens can be cached; this client does NOT auto-refresh
(use the refresh_token grant on your backend; the MCP server itself takes a
pre-minted access token via ``JOBBER_ACCESS_TOKEN``).

Docs: https://developer.getjobber.com/docs/
"""
from __future__ import annotations

import os
from typing import Any

import httpx


DEFAULT_BASE_URL = "https://api.getjobber.com/api/graphql"
DEFAULT_TIMEOUT = 30.0


class JobberError(RuntimeError):
    """Base exception for Jobber client errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        errors: Any = None,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.errors = errors  # GraphQL-level errors (when HTTP 200)
        self.data = data


class JobberAuthError(JobberError):
    """Raised when the access token is missing or rejected."""


class JobberAPIError(JobberError):
    """Raised on transport / GraphQL errors."""


class JobberClient:
    """Async GraphQL client for Jobber.

    Auth: OAuth2 bearer token (passed in directly). The MCP server reads the
    token from the ``JOBBER_ACCESS_TOKEN`` env var. For multi-tenant apps,
    run multiple MCP server instances — each with its own token.
    """

    def __init__(
        self,
        access_token: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        token = access_token or os.environ.get("JOBBER_ACCESS_TOKEN")
        if not token:
            raise JobberAuthError(
                "Jobber access token missing. Set JOBBER_ACCESS_TOKEN env var or pass it to the client. "
                "Get one via OAuth2 flow at https://developer.getjobber.com/docs/"
            )
        self._token = token
        self._base_url = base_url
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def execute(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a GraphQL query/mutation. Returns the ``data`` payload.

        Raises JobberAuthError on HTTP 401 / OAuth errors.
        Raises JobberAPIError on transport errors or when GraphQL returns errors.
        """
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            response = await http.post(
                self._base_url,
                json=payload,
                headers=self._headers(),
            )

        if response.status_code == 401:
            raise JobberAuthError(
                "Jobber rejected the bearer token (HTTP 401). Token may be expired — re-run the OAuth flow.",
                status_code=401,
            )
        if response.status_code == 403:
            raise JobberAuthError(
                "Jobber denied access (HTTP 403). Your app may not have the right scopes for this operation.",
                status_code=403,
            )
        if not 200 <= response.status_code < 300:
            try:
                body = response.json()
            except ValueError:
                body = response.text
            raise JobberAPIError(
                f"Jobber returned HTTP {response.status_code}",
                status_code=response.status_code,
                errors=body,
            )

        try:
            data = response.json()
        except ValueError as e:
            raise JobberAPIError(f"Jobber returned non-JSON response: {response.text}") from e

        # GraphQL can return 200 with errors[] populated
        if data.get("errors"):
            raise JobberAPIError(
                f"GraphQL errors: {data['errors']}",
                status_code=200,
                errors=data["errors"],
                data=data.get("data"),
            )

        return data.get("data") or {}

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