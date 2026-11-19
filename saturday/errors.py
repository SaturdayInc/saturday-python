"""
Typed errors. Every API error carries ``status``, ``code``, ``message``, ``error_type`` and,
when the API sets them, ``param`` and ``request_id``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

# The 429 codes that reset at UTC midnight. Nothing succeeds before then.
DAILY_LIMIT_CODES = (
    "daily_call_limit_reached",
    "intelligence_daily_limit_reached",
    "athlete_free_daily_limit_reached",
    "distinct_lookup_daily_limit_reached",
)

# The longest wait the client sleeps through inside one call, in seconds.
MAX_RETRY_WAIT_SECONDS = 30


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
        retry_after: Optional[float] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.error_type = error_type
        self.code = code
        self.param = param
        self.request_id = request_id
        # Seconds to wait, from the Retry-After header, when the response carried one (429s and 503s).
        self.retry_after = retry_after

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
        seconds: Optional[float] = None
        if retry_after is not None:
            try:
                seconds = max(0.0, float(retry_after))
            except ValueError:
                seconds = None
            if seconds is not None and seconds.is_integer():
                seconds = int(seconds)
        if status in (400, 422):
            return ValidationError(**kwargs)
        if status == 401:
            return AuthenticationError(**kwargs)
        if status == 403:
            return PermissionDeniedError(**kwargs)
        if status == 404:
            return NotFoundError(**kwargs)
        if status == 429:
            return RateLimitError(**kwargs, retry_after=seconds)
        return cls(**kwargs, retry_after=seconds)


class AuthenticationError(SaturdayError):
    """401: the key or token is missing, invalid, revoked, or for the other environment."""


class PermissionDeniedError(SaturdayError):
    """403: the key cannot use this feature or resource (for example ``feature_alpha``)."""


class RateLimitError(SaturdayError):
    """429. Read ``code``:

    - ``rate_limit_exceeded``: a short-term throttle. The client waits ``retry_after`` and retries.
    - ``catalog_paced``: new products are paced; ``retry_after`` is the seconds until they resume.
      The client retries a wait of 30 seconds or less; a longer one is raised to you.
    - ``rate_limited``: an unusual request pattern; calculations are blocked for ``retry_after`` seconds.
    - ``daily_call_limit_reached``, ``intelligence_daily_limit_reached``,
      ``athlete_free_daily_limit_reached``, ``distinct_lookup_daily_limit_reached``: a daily
      ceiling. ``daily_limit`` is True and ``resets_at`` is the UTC midnight it resets at. Never retried.
    """

    def __init__(self, *args: Any, retry_after: Optional[float] = None, now: Optional[datetime] = None, **kwargs: Any):
        kwargs["retry_after"] = retry_after
        super().__init__(*args, **kwargs)
        # An API that predates the daily codes marks a daily ceiling by sending no Retry-After.
        self.daily_limit = self.code in DAILY_LIMIT_CODES or retry_after is None
        self.resets_at: Optional[datetime] = None
        if self.daily_limit:
            now = now or datetime.now(timezone.utc)
            if retry_after is not None:
                self.resets_at = now + timedelta(seconds=retry_after)
            else:
                self.resets_at = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)

    @property
    def retryable(self) -> bool:
        """Whether the client retries this itself: a throttle or a short pacing wait, never a daily ceiling or a block."""
        if self.daily_limit or self.code == "rate_limited" or self.retry_after is None:
            return False
        return self.retry_after <= MAX_RETRY_WAIT_SECONDS


class ValidationError(SaturdayError):
    """400 or 422: the request is invalid. ``param`` names the field, as a path into your body
    (``legs[1].duration_mins``). For code ``unsupported_field`` (a field the request does not
    take), ``suggestion`` is the field it was probably meant to be, or None when the API names none.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.suggestion: Optional[str] = _suggested_field(self.message) if self.code == "unsupported_field" else None


def _suggested_field(message: str) -> Optional[str]:
    """The field an unsupported_field message points to: ``Did you mean "x"?`` or ``Send "x"``."""
    match = re.search(r'(?:Did you mean|Send) "([A-Za-z0-9_.\[\]]+)"', message or "")
    return match.group(1) if match else None


class NotFoundError(SaturdayError):
    """404: no such resource for this key, or a route this key cannot see."""
