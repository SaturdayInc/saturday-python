"""
Saturday API client with automatic retry and typed resource accessors.

Safety metadata is ALWAYS included in nutrition responses — athlete safety
cannot be paywalled. The ``not_instructions`` field is present in every
nutrition response for AI consumers.
"""

from __future__ import annotations

import time
from typing import Any, AsyncContextManager, AsyncIterator, Dict, List, Optional, Sequence, Union
from urllib.parse import quote

import httpx

from saturday.errors import RateLimitError, SaturdayError
from saturday.ai_stream import AIStreamError, AIStreamEvent, stream_ai
from saturday.types import (
    CoachSeatState,
    CoachLedgerPage,
    CoachTierStatus,
    CoachConnectSummary,
    CoachConnectEarnings,
    CoachConnectChargesPage,
    CoachConnectArrangements,
    Activity,
    ActivityFeedback,
    ActivityImportResponse,
    ActivityListResponse,
    Athlete,
    AthleteListResponse,
    AthleteSettings,
    BatchAthleteResponse,
    BatchCalculateResponse,
    ImportActivityRequest,
    NutritionCalculateResponse,
    PrescriptionEnvelope,
    StoredPrescriptionResponse,
)

SDK_VERSION = "0.7.0"
DEFAULT_BASE_URL = "https://api.saturday.fit"
DEFAULT_TIMEOUT = 30.0
# AI turns run up to the API's 60 s request cap, so an unconfigured stream deadline is longer than the JSON default.
DEFAULT_STREAM_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 3


class Saturday:
    """
    Saturday Nutrition Intelligence API client.

    Args:
        api_key: Your partner API key (sk_live_... or sk_test_...).
        base_url: Base URL override. Defaults to https://api.saturday.fit.
        timeout: Request timeout in seconds. Defaults to 30 for JSON requests and 60 for AI streams; an explicit value applies to both.
        max_retries: Maximum retry attempts for transient failures. Defaults to 3.
        bearer_token: OAuth2 Bearer token (alternative to API key).

    Example::

        client = Saturday(api_key="sk_live_...")
        rx = client.nutrition.calculate(
            activity_type="run",
            duration_min=90,
            thermal_stress_level=8,
        )
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: Optional[float] = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        bearer_token: Optional[str] = None,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = DEFAULT_TIMEOUT if timeout is None else timeout
        self._stream_timeout = DEFAULT_STREAM_TIMEOUT if timeout is None else timeout
        self._max_retries = max_retries
        self._bearer_token = bearer_token

        headers = {
            "User-Agent": f"saturday-python/{SDK_VERSION}",
            "X-SDK-Version": SDK_VERSION,
            "Content-Type": "application/json",
        }
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        else:
            headers["Authorization"] = f"Bearer {api_key}"

        self._client = httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
        )

        # Resource accessors
        self.nutrition = _NutritionResource(self)
        self.athletes = _AthletesResource(self)
        self.activities = _ActivitiesResource(self)
        self.products = _ProductsResource(self)
        self.ai = _AIResource(self)
        self.webhooks = _WebhooksResource(self)
        self.organizations = _OrganizationsResource(self)
        self.gear = _GearResource(self)
        self.knowledge = _KnowledgeResource(self)
        self.onboarding = _OnboardingResource(self)
        self.coach = _CoachResource(self)

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "Saturday":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        raw: bool = False,
    ) -> Any:
        """Make an authenticated API request with automatic retry on 429/5xx."""
        last_error: Optional[SaturdayError] = None

        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                delay = (2 ** (attempt - 1))
                time.sleep(delay)

            try:
                response = self._client.request(
                    method,
                    path,
                    json=json,
                    params=params,
                )

                if response.is_success:
                    if response.status_code == 204:
                        return None
                    if raw:
                        return response.content
                    return response.json()

                # Parse error
                try:
                    error_body = response.json()
                except Exception:
                    error_body = {"error": {"type": "api_error", "code": "unknown", "message": response.text}}

                error = SaturdayError.from_response(response.status_code, error_body)
                if isinstance(error, RateLimitError):
                    try:
                        error.retry_after = max(0, int(response.headers.get("Retry-After", "60")))
                    except ValueError:
                        pass
                last_error = error

                # Only retry on rate limit or server errors
                if response.status_code == 429 or response.status_code >= 500:
                    continue

                raise error

            except httpx.TimeoutException:
                raise SaturdayError(
                    message=f"Request timed out after {self._timeout}s",
                    code="timeout",
                )
            except SaturdayError:
                raise
            except httpx.HTTPError as e:
                raise SaturdayError(message=str(e), code="connection_error")

        # All retries exhausted
        if last_error:
            raise last_error
        raise SaturdayError(message="Max retries exceeded", code="max_retries_exceeded")


# --- Resource Classes ---


class _NutritionResource:
    def __init__(self, client: Saturday):
        self._client = client

    def calculate(self, **kwargs: Any) -> NutritionCalculateResponse:
        """Calculate a personalized fuel/hydration/electrolyte prescription."""
        return self._client.request("POST", "/v1/nutrition/calculate", json=kwargs)

    def batch_calculate(self, scenarios: List[Dict[str, Any]]) -> BatchCalculateResponse:
        """Batch calculate up to 50 scenarios; quota is charged per scenario."""
        return self._client.request("POST", "/v1/nutrition/calculate/batch", json={"scenarios": scenarios})


class _OnboardingResource:
    """Athlete onboarding — the headless mechanism for collecting a fueling
    profile in your own UI (API_OB).

    ``questions()`` returns the versioned question schema (the same definitions
    the hosted onboarding page renders); render it natively and write answers
    via ``athletes.update_settings()`` or athlete create/update. Exact numbers
    require a complete profile — every calculate response's ``precision`` object
    tells you what is still missing::

        rx = client.nutrition.calculate(activity_type="run", duration_min=90)
        p = rx["precision"]
        if not p["profile_complete"]:
            for f in p["missing_fields"]:        # sorted most-impactful-first
                print(f["field"], f["band_impact"])
            invite_url = p.get("onboarding", {}).get("url")  # athlete-scoped requests only

    **Attribution is required** when you render these questions in your UI — the
    schema response carries the ``attribution`` object, same contract as
    calculations.
    """

    def __init__(self, client: Saturday):
        self._client = client

    def questions(self) -> Dict[str, Any]:
        """Fetch the versioned onboarding question schema.

        Returns ``{"schema_version", "questions": [...], "attribution": {...}}``.
        Each question is ``{"field", "type" (single_select | multi_select |
        year_of_birth | weight), "required", "title_en", "l10n_key"?,
        "options"? [{"value", "label_en", "l10n_key"?, "pre_checked"?}],
        "min"?, "max"?}``. Option scales are odd-point (e.g. {1, 5, 9}), not
        continuous sliders — store the exact values given.
        """
        return self._client.request("GET", "/v1/onboarding/questions")


class _AthletesResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create(self, **kwargs: Any) -> Athlete:
        """Create a new athlete under your partner account."""
        return self._client.request("POST", "/v1/athletes", json=kwargs)

    def get(self, athlete_id: str) -> Athlete:
        """Get an athlete by ID."""
        return self._client.request("GET", f"/v1/athletes/{athlete_id}")

    def list(self, *, limit: int = 50, cursor: Optional[str] = None, search: Optional[str] = None) -> AthleteListResponse:
        """List athletes for your partner account.

        The array is under ``athletes``. Read ``pagination.has_more`` and pass
        ``pagination.next_cursor`` back as ``cursor`` for the next page.
        The legacy ``search`` argument is currently ignored by the API.
        """
        params: Dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if search:
            params["search"] = search
        return self._client.request("GET", "/v1/athletes", params=params)

    def update(self, athlete_id: str, **kwargs: Any) -> Athlete:
        """Partially update an athlete's profile."""
        return self._client.request("PATCH", f"/v1/athletes/{athlete_id}", json=kwargs)

    def delete(self, athlete_id: str) -> None:
        """Delete an athlete and all associated data."""
        self._client.request("DELETE", f"/v1/athletes/{athlete_id}")

    def get_settings(self, athlete_id: str) -> AthleteSettings:
        """Get an athlete's fueling preference settings."""
        return self._client.request("GET", f"/v1/athletes/{athlete_id}/settings")

    def update_settings(self, athlete_id: str, **kwargs: Any) -> AthleteSettings:
        """Replace partner-managed athlete settings; send the complete intended settings."""
        return self._client.request("PATCH", f"/v1/athletes/{athlete_id}/settings", json=kwargs)

    def batch_create(self, athletes: List[Dict[str, Any]]) -> BatchAthleteResponse:
        """Batch create up to 100 athletes; quota is charged per athlete."""
        return self._client.request("POST", "/v1/athletes/batch", json={"athletes": athletes})

    def export(self, athlete_id: str) -> Dict[str, Any]:
        """Export all athlete data (GDPR data portability)."""
        return self._client.request("POST", f"/v1/athletes/{athlete_id}/export")


class _ActivitiesResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create(self, athlete_id: str, **kwargs: Any) -> Activity:
        """Create a new activity for an athlete."""
        return self._client.request("POST", f"/v1/athletes/{athlete_id}/activities", json=kwargs)

    def get(self, athlete_id: str, activity_id: str) -> Activity:
        """Get an activity by ID."""
        return self._client.request("GET", f"/v1/athletes/{athlete_id}/activities/{activity_id}")

    def list(self, athlete_id: str, *, limit: int = 20, cursor: Optional[str] = None) -> ActivityListResponse:
        """List activities for an athlete.

        The array is under ``activities``. Read ``pagination.has_more`` and pass
        ``pagination.next_cursor`` back as ``cursor`` for the next page.
        """
        params: Dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._client.request("GET", f"/v1/athletes/{athlete_id}/activities", params=params)

    def update(self, athlete_id: str, activity_id: str, **kwargs: Any) -> Activity:
        """Partially update an activity."""
        return self._client.request("PATCH", f"/v1/athletes/{athlete_id}/activities/{activity_id}", json=kwargs)

    def delete(self, athlete_id: str, activity_id: str) -> None:
        """Delete an activity and its prescription."""
        self._client.request("DELETE", f"/v1/athletes/{athlete_id}/activities/{activity_id}")

    def calculate_prescription(self, athlete_id: str, activity_id: str) -> PrescriptionEnvelope:
        """Calculate/recalculate a nutrition prescription for this activity."""
        return self._client.request("POST", f"/v1/athletes/{athlete_id}/activities/{activity_id}/calculate")

    def get_prescription(self, athlete_id: str, activity_id: str) -> StoredPrescriptionResponse:
        """Get the stored prescription for an activity."""
        return self._client.request("GET", f"/v1/athletes/{athlete_id}/activities/{activity_id}/prescription")

    def import_activities(
        self,
        athlete_id: str,
        activities: Sequence[Union[ImportActivityRequest, Dict[str, Any]]],
        *,
        calculate: Optional[bool] = None,
    ) -> ActivityImportResponse:
        """Import up to 200 activities; calculation is opt-in and quota is per activity."""
        payload: Dict[str, Any] = {"activities": activities}
        if calculate is not None:
            payload["calculate"] = calculate
        return self._client.request("POST", f"/v1/athletes/{athlete_id}/activities/import", json=payload)

    def submit_feedback(self, athlete_id: str, activity_id: str, **kwargs: Any) -> ActivityFeedback:
        """Submit post-activity feedback on prescription quality."""
        return self._client.request("POST", f"/v1/athletes/{athlete_id}/activities/{activity_id}/feedback", json=kwargs)


class _ProductsResource:
    """Saturday's curated product catalog.

    Every method takes ``athlete_id``: the catalog opens on that athlete's
    Saturday subscription, not on your partner account. A subscribed athlete (or
    one inside their 30-day trial) gets ``tier: "full"`` with products; anyone
    else gets ``tier: "teaser"`` with empty product lists plus the category
    taxonomy and a subscribe CTA. Both are 200. Branch on ``tier``.
    """

    def __init__(self, client: Saturday):
        self._client = client

    def get_by_barcode(self, barcode: str, athlete_id: str) -> Dict[str, Any]:
        """Look up a curated product by barcode, on behalf of an athlete."""
        return self._client.request(
            "GET", f"/v1/products/{barcode}", params={"athlete_id": athlete_id}
        )

    def search(self, query: str, athlete_id: str) -> Dict[str, Any]:
        """Search the curated catalog, matched across name, brand, type, and keywords."""
        return self._client.request(
            "GET", "/v1/products/search", params={"q": query, "athlete_id": athlete_id}
        )

    def list_curated(self, athlete_id: str, *, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Page through Saturday's curated catalog (10 per page).

        Pass the ``next_cursor`` from the previous response to advance.
        """
        params: Dict[str, Any] = {"athlete_id": athlete_id}
        if cursor:
            params["cursor"] = cursor
        return self._client.request("GET", "/v1/products/curated", params=params)

    def list_categories(self, athlete_id: str) -> Dict[str, Any]:
        """List the product taxonomy. Free for every athlete."""
        return self._client.request(
            "GET", "/v1/products/categories", params={"athlete_id": athlete_id}
        )


class _AIResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create_conversation(self, athlete_id: str, initial_message: Optional[str] = None) -> Dict[str, Any]:
        """Deprecated: use async create_conversation_stream; sends no request."""
        raise AIStreamError("streaming_required", "Use async with ai.create_conversation_stream(athlete_id, message) and consume every event. No request was sent.")

    def send_message(self, conv_id: str, message: str) -> Dict[str, Any]:
        """Deprecated: use async send_message_stream; sends no request."""
        raise AIStreamError("streaming_required", "Use async with ai.send_message_stream(conv_id, message) and consume every event. No request was sent.")

    def create_conversation_stream(self, athlete_id: str, message: str, *, timeout: Optional[float] = None) -> AsyncContextManager[AsyncIterator[AIStreamEvent]]:
        """Async context manager for a single-attempt AI POST with a total deadline: the client timeout, else 60 s."""
        return stream_ai(self._client._base_url, dict(self._client._client.headers), "/v1/ai/conversations",
                         {"athlete_id": athlete_id, "message": message}, self._client._stream_timeout if timeout is None else timeout)

    def send_message_stream(self, conv_id: str, message: str, *, timeout: Optional[float] = None) -> AsyncContextManager[AsyncIterator[AIStreamEvent]]:
        """Async context manager preserving all events, including errors and warnings; the deadline is the client timeout, else 60 s."""
        return stream_ai(self._client._base_url, dict(self._client._client.headers), f"/v1/ai/conversations/{quote(conv_id, safe='')}/messages",
                         {"message": message}, self._client._stream_timeout if timeout is None else timeout)

    def get_messages(self, conv_id: str, *, limit: int = 50) -> Dict[str, Any]:
        """Get stored JSON history; the server ignores the legacy limit argument."""
        return self._client.request("GET", f"/v1/ai/conversations/{conv_id}/messages", params={"limit": limit})

    def get_conversation(self, conv_id: str) -> Dict[str, Any]:
        """Get conversation metadata."""
        return self._client.request("GET", f"/v1/ai/conversations/{conv_id}")

    def delete_conversation(self, conv_id: str) -> None:
        """Delete a conversation."""
        self._client.request("DELETE", f"/v1/ai/conversations/{conv_id}")

    def list_conversations(self, athlete_id: str, *, limit: int = 20) -> Dict[str, Any]:
        """List conversations for an athlete."""
        return self._client.request("GET", f"/v1/athletes/{athlete_id}/ai/conversations", params={"limit": limit})


class _WebhooksResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create(self, url: str, events: List[str], description: Optional[str] = None) -> Dict[str, Any]:
        """Register a webhook endpoint."""
        body: Dict[str, Any] = {"url": url, "events": events}
        if description:
            body["description"] = description
        return self._client.request("POST", "/v1/webhooks", json=body)

    def list(self) -> Dict[str, Any]:
        """List registered webhooks."""
        return self._client.request("GET", "/v1/webhooks")

    def get(self, webhook_id: str) -> Dict[str, Any]:
        """Get webhook details."""
        return self._client.request("GET", f"/v1/webhooks/{webhook_id}")

    def update(self, webhook_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Update a webhook."""
        return self._client.request("PATCH", f"/v1/webhooks/{webhook_id}", json=kwargs)

    def delete(self, webhook_id: str) -> None:
        """Delete a webhook."""
        self._client.request("DELETE", f"/v1/webhooks/{webhook_id}")

    def test(self, webhook_id: str) -> Dict[str, Any]:
        """Send a test event."""
        return self._client.request("POST", f"/v1/webhooks/{webhook_id}/test")


class _OrganizationsResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create(self, display_name: str, **kwargs: Any) -> Dict[str, Any]:
        """Create an organization."""
        return self._client.request("POST", "/v1/organizations", json={"display_name": display_name, **kwargs})

    def list(self) -> Dict[str, Any]:
        """List organizations."""
        return self._client.request("GET", "/v1/organizations")

    def get(self, org_id: str) -> Dict[str, Any]:
        """Get organization details."""
        return self._client.request("GET", f"/v1/organizations/{org_id}")

    def add_member(self, org_id: str, email: str, role: str, athlete_id: Optional[str] = None) -> Dict[str, Any]:
        """Add a member to an organization."""
        body: Dict[str, Any] = {"email": email, "role": role}
        if athlete_id:
            body["athlete_id"] = athlete_id
        return self._client.request("POST", f"/v1/organizations/{org_id}/members", json=body)

    def list_members(self, org_id: str) -> Dict[str, Any]:
        """List organization members."""
        return self._client.request("GET", f"/v1/organizations/{org_id}/members")

    def remove_member(self, org_id: str, member_id: str) -> None:
        """Remove a member from an organization."""
        self._client.request("DELETE", f"/v1/organizations/{org_id}/members/{member_id}")


class _GearResource:
    def __init__(self, client: Saturday):
        self._client = client

    def list(self, athlete_id: str) -> Dict[str, Any]:
        """List athlete's gear."""
        return self._client.request("GET", f"/v1/athletes/{athlete_id}/gear")

    def create(self, athlete_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Add a gear item."""
        return self._client.request("POST", f"/v1/athletes/{athlete_id}/gear", json=kwargs)

    def update(self, athlete_id: str, gear_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Update a gear item."""
        return self._client.request("PATCH", f"/v1/athletes/{athlete_id}/gear/{gear_id}", json=kwargs)

    def delete(self, athlete_id: str, gear_id: str) -> None:
        """Delete a gear item."""
        self._client.request("DELETE", f"/v1/athletes/{athlete_id}/gear/{gear_id}")


class _KnowledgeResource:
    def __init__(self, client: Saturday):
        self._client = client

    def search(self, query: str, *, limit: int = 5, category: Optional[str] = None) -> Dict[str, Any]:
        """Search the nutrition knowledge base."""
        body: Dict[str, Any] = {"query": query, "limit": limit}
        if category:
            body["category"] = category
        return self._client.request("POST", "/v1/knowledge/search", json=body)

    def list_topics(self) -> Dict[str, Any]:
        """List knowledge base topics."""
        return self._client.request("GET", "/v1/knowledge/topics")

    def get_article(self, article_id: str) -> Dict[str, Any]:
        """Get a knowledge article."""
        return self._client.request("GET", f"/v1/knowledge/articles/{article_id}")

class _CoachResource:
    """Coach API — ``/v1/coach/*`` (Module 5).

    READS scope to the coach's own roster (every ``athlete_uid`` is roster-confined;
    a non-roster athlete raises :class:`NotFoundError`). WRITES only ever touch the
    coach's OWN config — athlete fueling data is read-only via this API. Requires
    the Pro-Coach+ tier; a lapsed coach's reads/writes return 404.

    Authenticate with a coach API key (``cp_live_``/``cp_test_``, passed as
    ``api_key``) or an OAuth2 coach-scoped bearer token::

        client = Saturday(api_key="cp_live_...")
        digest = client.coach.roster_digest(window=7)
        client.coach.apply_preset(scope="overall", preset="balanced")
    """

    def __init__(self, client: Saturday):
        self._client = client

    # --- Reads ---

    def roster(self, *, window: Optional[int] = None) -> Dict[str, Any]:
        """List the roster with per-athlete needs-attention markers."""
        params: Dict[str, Any] = {}
        if window is not None:
            params["window"] = window
        return self._client.request("GET", "/v1/coach/roster", params=params or None)

    def roster_digest(self, *, window: Optional[int] = None) -> Dict[str, Any]:
        """The flagged-only digest: only athletes who crossed a concern bar this window."""
        params: Dict[str, Any] = {}
        if window is not None:
            params["window"] = window
        return self._client.request("GET", "/v1/coach/roster/digest", params=params or None)

    def fueling_rollup(
        self, athlete_uid: str, *, window: Optional[int] = None, focus: Optional[str] = None
    ) -> Dict[str, Any]:
        """One athlete's in-window fueling rollup + concern summary (roster-confined)."""
        return self._client.request(
            "GET",
            f"/v1/coach/athletes/{athlete_uid}/fueling-rollup",
            params=_coach_read_params(window, focus),
        )

    def report(
        self,
        athlete_uid: str,
        *,
        window: Optional[int] = None,
        focus: Optional[str] = None,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        """The AI fueling report (narrative + structured). ``refresh=True`` forces regeneration."""
        params = _coach_read_params(window, focus) or {}
        if refresh:
            params["refresh"] = "true"
        return self._client.request(
            "GET", f"/v1/coach/athletes/{athlete_uid}/report", params=params or None
        )

    def report_pdf(
        self, athlete_uid: str, *, window: Optional[int] = None, focus: Optional[str] = None
    ) -> bytes:
        """The report as a downloadable PDF (returns the raw bytes)."""
        params = _coach_read_params(window, focus) or {}
        params["format"] = "pdf"
        return self._client.request(
            "GET", f"/v1/coach/athletes/{athlete_uid}/report", params=params, raw=True
        )

    def session_detail(self, athlete_uid: str, activity_id: str) -> Dict[str, Any]:
        """Drill into one session by activity id (planned-vs-actual + markers)."""
        return self._client.request(
            "GET", f"/v1/coach/athletes/{athlete_uid}/sessions/{activity_id}"
        )

    # --- Config: alert rules ---

    def get_notification_rules(
        self, *, scope: Optional[str] = None, scope_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Read the alert rules set at exactly one scope (not the merged resolution)."""
        return self._client.request(
            "GET", "/v1/coach/config/notification-rules", params=_scope_params(scope, scope_id)
        )

    def set_notification_rules(
        self, scope: str, rules: Dict[str, Any], *, scope_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Replace the alert rules at a scope (idempotent upsert).

        ``rules`` is the full set:
        ``{"notification_rules": {"<trigger>": {"enabled", "channels", "cadence",
        "urgent_threshold"}}, "combinators": [...], "quiet_hours": {...}, "preset"}``.
        Triggers: under_fuel, symptom, low_rating, hyponatremia_pattern, dial_down,
        sleep_trend, went_quiet. Channels: in_portal, email, push, webhook (no SMS).
        """
        return self._client.request(
            "PUT",
            "/v1/coach/config/notification-rules",
            json={"scope": scope, "scope_id": scope_id, "rules": rules},
        )

    def apply_preset(self, *, scope: str, preset: str, scope_id: Optional[str] = None) -> Dict[str, Any]:
        """Apply a named preset (``hands_off`` / ``balanced`` / ``hands_on``) at a scope."""
        return self._client.request(
            "POST",
            "/v1/coach/config/preset",
            json={"scope": scope, "scope_id": scope_id, "preset": preset},
        )

    # --- Config: AI report + concern settings ---

    def get_report_settings(
        self, *, scope: Optional[str] = None, scope_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Read the AI-report + concern-threshold settings at a scope."""
        return self._client.request(
            "GET", "/v1/coach/config/report-settings", params=_scope_params(scope, scope_id)
        )

    def set_report_settings(
        self, scope: str, settings: Dict[str, Any], *, scope_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Upsert AI-report + concern-threshold settings at a scope (unset fields fall through).

        ``settings`` keys: ``ai_report_window_days`` (7|14|30), ``ai_report_focus``
        (worst|rolling|key), and the optional concern cutoffs (each a fraction in (0,1]):
        ``concern_carb_cutoff``, ``concern_sodium_cutoff``, ``concern_fluid_cutoff``,
        ``hyponatremia_fluid_min``, ``hyponatremia_sodium_max``.
        """
        return self._client.request(
            "PUT",
            "/v1/coach/config/report-settings",
            json={"scope": scope, "scope_id": scope_id, "settings": settings},
        )

    # --- Webhooks ---

    def list_webhooks(self) -> Dict[str, Any]:
        """List the coach's webhook endpoints (secrets never returned)."""
        return self._client.request("GET", "/v1/coach/webhooks")

    def register_webhook(self, url: str, *, events: Optional[List[str]] = None) -> Dict[str, Any]:
        """Register a webhook endpoint. The signing secret is returned ONCE — store it.

        ``events`` subscribes to a subset of ``concern.detected`` /
        ``athlete.needs_attention``; omit (or pass empty) for all coach events.
        """
        return self._client.request(
            "POST", "/v1/coach/webhooks", json={"url": url, "events": events or []}
        )

    def delete_webhook(self, webhook_id: str) -> Dict[str, Any]:
        """Delete a webhook endpoint by id."""
        return self._client.request("DELETE", f"/v1/coach/webhooks/{webhook_id}")

    def disable_webhook(self, webhook_id: str) -> Dict[str, Any]:
        """Disable a webhook endpoint (stops delivery without deleting it)."""
        return self._client.request("POST", f"/v1/coach/webhooks/{webhook_id}/disable")

    def enable_webhook(self, webhook_id: str) -> Dict[str, Any]:
        """Re-enable a previously disabled webhook endpoint."""
        return self._client.request("POST", f"/v1/coach/webhooks/{webhook_id}/enable")

    # --- Billing (read-only; the key must carry billing:read) ---

    def seat_state(self, *, org_id: Optional[str] = None) -> CoachSeatState:
        """The live seat picture. Pass ``org_id`` to read the coach's organization as payer."""
        params = {"org_id": org_id} if org_id else None
        return self._client.request("GET", "/v1/coach/billing/seat-state", params=params)

    def ledger(
        self,
        *,
        view: Optional[str] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> CoachLedgerPage:
        """One page of the coach's financial ledger, newest first.

        ``view`` is ``all``, ``expenditures`` or ``inflows``; ``limit`` is 1 to 200;
        pass a page's ``next_cursor`` back as ``cursor`` for the next one.
        """
        params: Dict[str, Any] = {}
        if view:
            params["view"] = view
        if limit is not None:
            params["limit"] = limit
        if cursor:
            params["cursor"] = cursor
        return self._client.request("GET", "/v1/coach/billing/ledger", params=params or None)

    def tier_status(self) -> CoachTierStatus:
        """The coach's active tier subscriptions and access status."""
        return self._client.request("GET", "/v1/coach/billing/tier-status")

    def connect_summary(self) -> CoachConnectSummary:
        """Stripe Connect account status plus this month's and lifetime totals."""
        return self._client.request("GET", "/v1/coach/billing/connect/summary")

    def connect_earnings(self) -> CoachConnectEarnings:
        """Earnings totals across settled charges plus the most recent per-charge breakdowns."""
        return self._client.request("GET", "/v1/coach/billing/connect/earnings")

    def connect_transactions(
        self, *, limit: Optional[int] = None, cursor: Optional[str] = None
    ) -> CoachConnectChargesPage:
        """One page of Connect charges, newest first. Pass ``next_cursor`` back as ``cursor``."""
        params: Dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if cursor:
            params["cursor"] = cursor
        return self._client.request(
            "GET", "/v1/coach/billing/connect/transactions", params=params or None
        )

    def connect_arrangements(self) -> CoachConnectArrangements:
        """Every billing arrangement the coach has configured, in any status."""
        return self._client.request("GET", "/v1/coach/billing/connect/arrangements")


def _coach_read_params(window: Optional[int], focus: Optional[str]) -> Optional[Dict[str, Any]]:
    """Build the ?window=&focus= params for a coach per-athlete read."""
    params: Dict[str, Any] = {}
    if window is not None:
        params["window"] = window
    if focus:
        params["focus"] = focus
    return params or None


def _scope_params(scope: Optional[str], scope_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Build the ?scope=&scope_id= params for a coach config read."""
    params: Dict[str, Any] = {}
    if scope:
        params["scope"] = scope
    if scope_id:
        params["scope_id"] = scope_id
    return params or None
