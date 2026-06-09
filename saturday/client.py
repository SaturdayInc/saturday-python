"""
Saturday API client with automatic retry and typed resource accessors.

Safety metadata is ALWAYS included in nutrition responses — athlete safety
cannot be paywalled. The ``not_instructions`` field is present in every
nutrition response for AI consumers.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from saturday.errors import SaturdayError

SDK_VERSION = "0.2.0"
DEFAULT_BASE_URL = "https://api.saturday.fit"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3


class Saturday:
    """
    Saturday Nutrition Intelligence API client.

    Args:
        api_key: Your partner API key (sk_live_... or sk_test_...).
        base_url: Base URL override. Defaults to https://api.saturday.fit.
        timeout: Request timeout in seconds. Defaults to 30.
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
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        bearer_token: Optional[str] = None,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
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
            timeout=timeout,
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
                    return response.json()

                # Parse error
                try:
                    error_body = response.json()
                except Exception:
                    error_body = {"error": {"type": "api_error", "code": "unknown", "message": response.text}}

                error = SaturdayError.from_response(response.status_code, error_body)
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

    def calculate(self, **kwargs: Any) -> Dict[str, Any]:
        """Calculate a personalized fuel/hydration/electrolyte prescription."""
        return self._client.request("POST", "/v1/nutrition/calculate", json=kwargs)

    def batch_calculate(self, scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Batch calculate prescriptions for multiple scenarios (max 50)."""
        return self._client.request("POST", "/v1/nutrition/calculate/batch", json={"scenarios": scenarios})


class _AthletesResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create(self, **kwargs: Any) -> Dict[str, Any]:
        """Create a new athlete under your partner account."""
        return self._client.request("POST", "/v1/athletes", json=kwargs)

    def get(self, athlete_id: str) -> Dict[str, Any]:
        """Get an athlete by ID."""
        return self._client.request("GET", f"/v1/athletes/{athlete_id}")

    def list(self, *, limit: int = 50, cursor: Optional[str] = None, search: Optional[str] = None) -> Dict[str, Any]:
        """List athletes for your partner account.

        The response array is under the ``athletes`` key, with ``has_more`` and a
        ``cursor`` for the next page. Pass that ``cursor`` back here to page forward.
        """
        params: Dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        if search:
            params["search"] = search
        return self._client.request("GET", "/v1/athletes", params=params)

    def update(self, athlete_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Partially update an athlete's profile."""
        return self._client.request("PATCH", f"/v1/athletes/{athlete_id}", json=kwargs)

    def delete(self, athlete_id: str) -> None:
        """Delete an athlete and all associated data."""
        self._client.request("DELETE", f"/v1/athletes/{athlete_id}")

    def get_settings(self, athlete_id: str) -> Dict[str, Any]:
        """Get an athlete's fueling preference settings."""
        return self._client.request("GET", f"/v1/athletes/{athlete_id}/settings")

    def update_settings(self, athlete_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Update an athlete's fueling preference settings."""
        return self._client.request("PATCH", f"/v1/athletes/{athlete_id}/settings", json=kwargs)

    def batch_create(self, athletes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Batch create up to 100 athletes."""
        return self._client.request("POST", "/v1/athletes/batch", json={"athletes": athletes})

    def export(self, athlete_id: str) -> Dict[str, Any]:
        """Export all athlete data (GDPR data portability)."""
        return self._client.request("POST", f"/v1/athletes/{athlete_id}/export")


class _ActivitiesResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create(self, athlete_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Create a new activity for an athlete."""
        return self._client.request("POST", f"/v1/athletes/{athlete_id}/activities", json=kwargs)

    def get(self, athlete_id: str, activity_id: str) -> Dict[str, Any]:
        """Get an activity by ID."""
        return self._client.request("GET", f"/v1/athletes/{athlete_id}/activities/{activity_id}")

    def list(self, athlete_id: str, *, limit: int = 20, cursor: Optional[str] = None) -> Dict[str, Any]:
        """List activities for an athlete.

        The response array is under the ``activities`` key, with ``has_more`` and a
        ``cursor`` for the next page. Pass that ``cursor`` back here to page forward.
        """
        params: Dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._client.request("GET", f"/v1/athletes/{athlete_id}/activities", params=params)

    def update(self, athlete_id: str, activity_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Partially update an activity."""
        return self._client.request("PATCH", f"/v1/athletes/{athlete_id}/activities/{activity_id}", json=kwargs)

    def delete(self, athlete_id: str, activity_id: str) -> None:
        """Delete an activity and its prescription."""
        self._client.request("DELETE", f"/v1/athletes/{athlete_id}/activities/{activity_id}")

    def calculate_prescription(self, athlete_id: str, activity_id: str) -> Dict[str, Any]:
        """Calculate/recalculate a nutrition prescription for this activity."""
        return self._client.request("POST", f"/v1/athletes/{athlete_id}/activities/{activity_id}/calculate")

    def get_prescription(self, athlete_id: str, activity_id: str) -> Dict[str, Any]:
        """Get the stored prescription for an activity."""
        return self._client.request("GET", f"/v1/athletes/{athlete_id}/activities/{activity_id}/prescription")

    def submit_feedback(self, athlete_id: str, activity_id: str, **kwargs: Any) -> Dict[str, Any]:
        """Submit post-activity feedback on prescription quality."""
        return self._client.request("POST", f"/v1/athletes/{athlete_id}/activities/{activity_id}/feedback", json=kwargs)


class _ProductsResource:
    def __init__(self, client: Saturday):
        self._client = client

    def get_by_barcode(self, barcode: str) -> Dict[str, Any]:
        """Look up a product by barcode."""
        return self._client.request("GET", f"/v1/products/{barcode}")

    def search(self, query: str, *, category: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
        """Search the product database."""
        params: Dict[str, Any] = {"q": query, "limit": limit}
        if category:
            params["category"] = category
        return self._client.request("GET", "/v1/products/search", params=params)

    def list_curated(self, *, category: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """List Saturday's curated product database."""
        params: Dict[str, Any] = {"limit": limit}
        if category:
            params["category"] = category
        return self._client.request("GET", "/v1/products/curated", params=params)

    def list_categories(self) -> Dict[str, Any]:
        """List product categories."""
        return self._client.request("GET", "/v1/products/categories")


class _AIResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create_conversation(self, athlete_id: str, initial_message: Optional[str] = None) -> Dict[str, Any]:
        """Start a new AI coaching conversation for an athlete."""
        body: Dict[str, Any] = {"athlete_id": athlete_id}
        if initial_message:
            body["initial_message"] = initial_message
        return self._client.request("POST", "/v1/ai/conversations", json=body)

    def send_message(self, conv_id: str, message: str) -> Dict[str, Any]:
        """Send a message and receive the AI response."""
        return self._client.request("POST", f"/v1/ai/conversations/{conv_id}/messages", json={"message": message})

    def get_messages(self, conv_id: str, *, limit: int = 50) -> Dict[str, Any]:
        """Get conversation history."""
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
