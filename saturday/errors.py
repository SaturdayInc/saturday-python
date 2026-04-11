"""
Typed error classes for Saturday API errors.

All errors follow the Stripe-style format with type, code, message,
and optional param/documentation_url fields.
"""

from __future__ import annotations
from typing import Optional


class SaturdayError(Exception):
    """Base error for all Saturday API errors."""

    def __init__(
        self,
        message: str,
        status: int = 0,
        error_type: str = "api_error",
        code: str = "unknown",
        param: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.code = code
        self.param = param
        self.request_id = request_id

    @classmethod
    def from_response(cls, status: int, error_body: dict) -> "SaturdayError":
        """Create the appropriate error subclass from an API error response."""
        detail = error_body.get("error", error_body)
        msg = detail.get("message", "Unknown error")
        kwargs = {
            "message": msg,
            "status": status,
            "error_type": detail.get("type", "api_error"),
            "code": detail.get("code", "unknown"),
            "param": detail.get("param"),
            "request_id": detail.get("request_id"),
        }

        if status == 401:
            return AuthenticationError(**kwargs)
        elif status == 404:
            return NotFoundError(**kwargs)
        elif status == 429:
            return RateLimitError(**kwargs)
        elif status in (400, 422):
            return ValidationError(**kwargs)
        else:
            return cls(**kwargs)


class AuthenticationError(SaturdayError):
    """Missing or invalid API key / Bearer token."""
    pass


class RateLimitError(SaturdayError):
    """Rate limit exceeded. Check retry_after for seconds to wait."""

    def __init__(self, *args, retry_after: int = 60, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class ValidationError(SaturdayError):
    """Request validation failed (400 or 422)."""
    pass


class NotFoundError(SaturdayError):
    """Resource not found (404)."""
    pass
