"""
Typed errors. Every API error carries ``status``, ``code``, ``message``, ``error_type`` and,
when the API sets them, ``param``, ``request_id`` and (for ``athlete_exists``) ``athlete_id``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Optional

# The 429 codes that reset at UTC midnight. Nothing they refuse succeeds before then.
# simulated_subscriber_daily_limit_reached is the test environment's: the key has marked its day's
# allowance of athletes with testing.simulate_subscription.
DAILY_LIMIT_CODES = (
    "daily_call_limit_reached",
    "intelligence_daily_limit_reached",
    "athlete_free_daily_limit_reached",
    "distinct_lookup_daily_limit_reached",
    "simulated_subscriber_daily_limit_reached",
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
        athlete_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.status = status
        self.error_type = error_type
        self.code = code
        self.param = param
        self.request_id = request_id
        # For athlete_exists (409): the athlete that holds the external_id you sent.
        self.athlete_id = athlete_id
        # Seconds to wait, from the Retry-After header, when the response carried one (429s and 503s).
        self.retry_after = retry_after

    @classmethod
    def from_response(cls, status: int, error_body: Any, retry_after: Optional[str] = None) -> "SaturdayError":
        """The error subclass for an API error response."""
        if isinstance(error_body, dict):
            raw_detail = error_body.get("error", error_body)
            detail = raw_detail if isinstance(raw_detail, dict) else {}
        else:
            detail = {}
        message = detail.get("message")
        if not isinstance(message, str) or not message:
            message = f"HTTP {status}"
        error_type = detail.get("type")
        if not isinstance(error_type, str) or not error_type:
            error_type = "api_error"
        code = detail.get("code")
        if not isinstance(code, str) or not code:
            code = "unknown"
        param = detail.get("param") if isinstance(detail.get("param"), str) else None
        request_id = detail.get("request_id") if isinstance(detail.get("request_id"), str) else None
        athlete_id = detail.get("athlete_id") if isinstance(detail.get("athlete_id"), str) else None
        kwargs: Dict[str, Any] = {
            "message": message,
            "status": status,
            "error_type": error_type,
            "code": code,
            "param": param,
            "request_id": request_id,
            "athlete_id": athlete_id,
        }
        seconds: Optional[float] = None
        if retry_after is not None:
            stripped = retry_after.strip() if isinstance(retry_after, str) else retry_after
            if stripped is None or stripped == "":
                seconds = None
            else:
                try:
                    seconds = max(0.0, float(stripped))  # type: ignore[arg-type]
                except (ValueError, TypeError):
                    try:
                        parsed = parsedate_to_datetime(stripped)  # type: ignore[arg-type]
                        if parsed is None:
                            seconds = None
                        else:
                            if parsed.tzinfo is None:
                                parsed = parsed.replace(tzinfo=timezone.utc)
                            seconds = max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())
                    except Exception:
                        seconds = None
                if seconds is not None and float(seconds).is_integer():
                    seconds = int(seconds)
        if status in (400, 422):
            return ValidationError(**kwargs)
        if status == 401:
            return AuthenticationError(**kwargs)
        if status == 403:
            return PermissionDeniedError(**kwargs)
        if status == 404:
            return NotFoundError(**kwargs)
        if status == 409:
            return ConflictError(**kwargs)
        if status == 429:
            return RateLimitError(**kwargs, retry_after=seconds)
        return cls(**kwargs, retry_after=seconds)


class AuthenticationError(SaturdayError):
    """401: the key or token is missing, invalid, revoked, or for the other environment."""


class PermissionDeniedError(SaturdayError):
    """403: the key cannot use this feature or resource. Read ``code``: ``feature_alpha`` (a feature
    not yet open to your key), ``plan_inactive`` (the paid Saturday plan this key comes with has
    ended; the key works again, with its athletes, once the plan is active),
    ``resource_limit_exceeded`` (the key's athletes are at their limit; write to api@saturday.fit
    to raise it)."""


class RateLimitError(SaturdayError):
    """429. Read ``code``:

    - ``rate_limit_exceeded``: a short-term throttle. The client waits ``retry_after`` and retries.
    - ``catalog_paced``: new products are paced; ``retry_after`` is the seconds until they resume.
      The client retries a wait of 30 seconds or less; a longer one is raised to you.
    - ``rate_limited``: an unusual request pattern; calculations are blocked for ``retry_after`` seconds.
    - ``daily_call_limit_reached``, ``intelligence_daily_limit_reached``,
      ``athlete_free_daily_limit_reached``, ``distinct_lookup_daily_limit_reached``, and on the
      test environment ``simulated_subscriber_daily_limit_reached``: a daily ceiling.
      ``daily_limit`` is True and ``resets_at`` is the UTC midnight it resets at. Never retried.
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


class ConflictError(SaturdayError):
    """409: the request conflicts with a record you hold. For ``athlete_exists``, another of your
    athletes holds the ``external_id`` you sent: nothing was created or changed, and
    ``athlete_id`` names that athlete."""
