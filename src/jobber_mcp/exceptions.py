"""Jobber exceptions — typed hierarchy with structured context.

Pattern: stripe-python / boto3 — every error carries structured fields
(http_status, error_code, request_id) so callers can branch on cause, not
just message text. The base class is never raised directly.

Jobber's GraphQL API has a special case: HTTP 200 responses can carry
``errors[]`` populated at the GraphQL layer. These are surfaced as
``JobberAPIError`` with ``http_status=200`` and ``graphql_errors`` populated.
"""
from __future__ import annotations

from typing import Any


class JobberError(Exception):
    """Base exception for all Jobber client errors."""

    http_status: int | None = None

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
        body: Any = None,
        graphql_errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status if http_status is not None else self.http_status
        self.error_code = error_code
        self.request_id = request_id
        self.body = body
        self.graphql_errors = graphql_errors

    def __repr__(self) -> str:
        parts = [f"http_status={self.http_status!r}"]
        if self.error_code:
            parts.append(f"error_code={self.error_code!r}")
        if self.request_id:
            parts.append(f"request_id={self.request_id!r}")
        if self.graphql_errors:
            parts.append(f"graphql_errors={len(self.graphql_errors)} entries")
        return f"{type(self).__name__}({', '.join(parts)})"


class JobberAuthError(JobberError):
    """401 (bad/expired token) or 403 (insufficient scope)."""

    http_status = 401


class JobberNotFoundError(JobberError):
    """GraphQL returned a NOT_FOUND error."""

    http_status = 404


class JobberRateLimitError(JobberError):
    """429 — rate limit hit."""

    http_status = 429

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class JobberAPIError(JobberError):
    """5xx, GraphQL-level errors (HTTP 200 with errors[]), or other
    non-2xx responses. ``graphql_errors`` is populated when the server
    returned HTTP 200 with errors[]."""

    http_status = 500


class JobberConnectionError(JobberError):
    """Network-level failure."""

    http_status = None
