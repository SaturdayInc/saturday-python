"""
Typed errors. Every API error carries ``status``, ``code``, ``message``, ``error_type`` and,
when the API sets them, ``param`` and ``request_id``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class SaturdayError(Exception):
    """Base class for every API error. ``status`` is 0 for a timeout or connection error."""

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
        self.message = message
        self.status = status
        self.error_type = error_type
        self.code = code
        self.param = param
        self.request_id = request_id

    @classmethod
    def from_response(cls, status: int, error_body: Dict[str, Any], retry_after: Optional[str] = None) -> "SaturdayError":
        """The error subclass for an API error response."""
        detail = error_body.get("error", error_body) if isinstance(error_body, dict) else {}
        kwargs: Dict[str, Any] = {
            "message": detail.get("message", f"HTTP {status}"),
            "status": status,
            "error_type": detail.get("type", "api_error"),
            "code": detail.get("code", "unknown"),
            "param": detail.get("param"),
            "request_id": detail.get("request_id"),
        }
        if status in (400, 422):
            return ValidationError(**kwargs)
        if status == 401:
            return AuthenticationError(**kwargs)
        if status == 403:
            return PermissionDeniedError(**kwargs)
        if status == 404:
            return NotFoundError(**kwargs)
        if status == 429:
            seconds: Optional[int] = None
            if retry_after is not None:
                try:
                    seconds = max(0, int(retry_after))
                except ValueError:
                    seconds = None
            return RateLimitError(**kwargs, retry_after=seconds)
        return cls(**kwargs)


class AuthenticationError(SaturdayError):
    """401: the key or token is missing, invalid, revoked, or for the other environment."""


class PermissionDeniedError(SaturdayError):
    """403: the key cannot use this feature or resource (for example ``feature_alpha``)."""


class RateLimitError(SaturdayError):
    """429.

    A rate limit or pacing carries ``retry_after`` in seconds; the client waits out one of 60
    seconds or less itself. A daily ceiling has no ``retry_after`` (``daily_limit`` is True) and
    resets at midnight UTC.
    """

    def __init__(self, *args: Any, retry_after: Optional[int] = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after

    @property
    def daily_limit(self) -> bool:
        return self.retry_after is None


class ValidationError(SaturdayError):
    """400 or 422: the request is invalid. ``param`` names the field."""


class NotFoundError(SaturdayError):
    """404: no such resource for this key, or a route this key cannot see."""
