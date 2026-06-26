"""Jobber MCP — public surface."""
__version__ = "0.2.0"

from .client import JobberClient
from .exceptions import (
    JobberAPIError,
    JobberAuthError,
    JobberConnectionError,
    JobberError,
    JobberNotFoundError,
    JobberRateLimitError,
)
from .server import main, mcp

__all__ = [
    "JobberAPIError",
    "JobberAuthError",
    "JobberClient",
    "JobberConnectionError",
    "JobberError",
    "JobberNotFoundError",
    "JobberRateLimitError",
    "main",
    "mcp",
]
