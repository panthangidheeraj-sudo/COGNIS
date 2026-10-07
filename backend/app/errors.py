"""Typed errors. API errors serialise to ``{code, message, details?}`` as API_CONTRACT.md requires."""
from __future__ import annotations

from typing import Any, Literal

ApiErrorCode = Literal["not_found", "ambiguous", "blocked", "rate_limited", "unavailable", "invalid", "network", "unknown"]

_STATUS = {"not_found": 404, "ambiguous": 409, "blocked": 403, "rate_limited": 429, "invalid": 422, "unavailable": 503, "network": 502, "unknown": 500}


class ApiError(Exception):
    def __init__(self, code: ApiErrorCode, message: str, *, status: int | None = None, details: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status or _STATUS.get(code, 500)
        self.details = details

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return body


class SourceError(Exception):
    """A classified connector failure (never raised past the connector boundary)."""

    def __init__(self, kind: str, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retryable = retryable


class UnsafeUrlError(ValueError):
    """URL rejected by the SSRF/URL policy before any network access."""


class BudgetExhausted(Exception):
    """Raised when a hard request/cost/time budget would be exceeded."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class LLMOutputError(Exception):
    """Model output failed schema validation after retries."""
