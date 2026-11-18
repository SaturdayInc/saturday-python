"""
Saturday API client: fueling prescriptions (carbohydrate, sodium and fluid) for endurance
sessions, sized to each athlete, and product fit and prep against them.

Every method returns the API's JSON as plain dictionaries, typed with the TypedDicts in
``saturday.types``.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Sequence, Union
from urllib.parse import quote

import httpx

from saturday.errors import RateLimitError, SaturdayError
from saturday.types import (
    Activity,
    ActivityFeedback,
    ActivityImportResponse,
    ActivityListResponse,
    ActivityTypesResponse,
    ApiKeyListResponse,
    Athlete,
    AthleteDataExport,
    AthleteListResponse,
    AthleteSettings,
    BatchAthleteResponse,
    BatchCalculateResponse,
    CoachConnectArrangements,
    CoachConnectChargesPage,
    CoachConnectEarnings,
    CoachConnectSummary,
    CoachLedgerPage,
    CoachSeatState,
    CoachTierStatus,
    ConsentListResponse,
    ConsentRecord,
    CreatedApiKey,
    DailyUsageResponse,
    ErrorCatalogResponse,
    FuelingProfile,
    HealthResponse,
    ImportActivityRequest,
    IntegrationStatusResponse,
    IntegrationSyncResponse,
    LicenseListResponse,
    NutritionCalculateResponse,
    OnboardingQuestionsResponse,
    Organization,
    OrganizationListResponse,
    OrganizationMember,
    OrganizationMembersResponse,
    OrganizationOffer,
    OrganizationSubscription,
    OrganizationSubscriptionListResponse,
    PartnerAccount,
    PrepResponse,
    PrescriptionEnvelope,
    ProductCompareResponse,
    ProductFitResponse,
    RotatedApiKey,
    SettingsSchemaResponse,
    SimulateSubscriptionResponse,
    StoredPrescriptionResponse,
    UsageResponse,
    Webhook,
    WebhookDeliveryList,
    WebhookCreateResponse,
    WebhookListResponse,
    WebhookTestResponse,
)

SDK_VERSION = "0.8.0"
DEFAULT_BASE_URL = "https://api.saturday.fit"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
# The longest Retry-After a 429 is waited out for. A longer one is a block that lasts minutes.
MAX_RETRY_AFTER_S = 30
_RETRY_SAFE_ACTIVITY_POST = re.compile(r"^/v1/athletes/[^/]+/(activities/[^/]+/(calculate|prep)|export)$")


def _retry_safe_on_server_error(method: str, path: str) -> bool:
    """A 5xx is retried only where a repeat cannot make a second record: every GET, PUT, PATCH
    and DELETE, and the POSTs that compute or read (calculations, product fit and compare, label
    reading, inference, an activity's calculate and prep, export)."""
    if method.upper() != "POST":
        return True
    bare = path.split("?")[0]
    return bare.startswith(("/v1/nutrition/", "/v1/infer/")) or bool(_RETRY_SAFE_ACTIVITY_POST.match(bare))


def _seg(value: str) -> str:
    """Encode one path segment."""
    return quote(str(value), safe="")


def _params(**values: Any) -> Optional[Dict[str, Any]]:
    """Query parameters, without the ones left unset."""
    out = {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in values.items() if v is not None and v != ""}
    return out or None


class Saturday:
    """
    Saturday API client.

    Args:
        api_key: A partner key (``sk_live_...`` or ``sk_test_...``) or a coach key (``cp_live_...`` or ``cp_test_...``).
        base_url: Defaults to https://api.saturday.fit.
        timeout: Per-request timeout in seconds. Defaults to 30.
        max_retries: Retries for 429s whose ``Retry-After`` is 30 seconds or less and for 5xx responses (not on a POST that creates or changes a record). Defaults to 3; 0 disables retries.
        bearer_token: An athlete's OAuth2 access token, sent in place of the API key.

    Example::

        client = Saturday(api_key="sk_test_...")
        athlete = client.athletes.create(external_id="user-42", sex="female", year_of_birth=1990, weight_kg=62)
        plan = client.nutrition.calculate(
            athlete_id=athlete["id"], activity_type="run", duration_min=90,
            intensity_level=5, thermal_stress_level=6, meal_before_min=120, is_race=False,
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
        self._max_retries = max_retries
        self._bearer_token = bearer_token

        self._client = httpx.Client(
            base_url=self._base_url,
            headers={
                "User-Agent": f"saturday-python/{SDK_VERSION}",
                "X-SDK-Version": SDK_VERSION,
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bearer_token or api_key}",
            },
            timeout=self._timeout,
        )

        self.nutrition = _NutritionResource(self)
        self.athletes = _AthletesResource(self)
        self.activities = _ActivitiesResource(self)
        self.onboarding = _OnboardingResource(self)
        self.reference = _ReferenceResource(self)
        self.infer = _InferResource(self)
        self.partner = _PartnerResource(self)
        self.webhooks = _WebhooksResource(self)
        self.organizations = _OrganizationsResource(self)
        self.integrations = _IntegrationsResource(self)
        self.testing = _TestingResource(self)
        self.meta = _MetaResource(self)
        self.knowledge = _KnowledgeResource(self)
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
        json: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        raw: bool = False,
    ) -> Any:
        """Send an authenticated request.

        A 429 whose ``Retry-After`` is 30 seconds or less is retried after that wait; a 5xx is
        retried after 1, 2 and 4 seconds, except on a POST that creates or changes a record, since
        the server may have done the write. Any other 429 (a daily ceiling has no ``Retry-After``)
        and every other 4xx raise at once.
        """
        last_error: Optional[SaturdayError] = None

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.request(method, path, json=json, params=params)
            except httpx.TimeoutException:
                raise SaturdayError(message=f"Request timed out after {self._timeout}s", code="timeout")
            except httpx.HTTPError as e:
                raise SaturdayError(message=str(e), code="connection_error")

            if response.is_success:
                if response.status_code == 204:
                    return None
                return response.content if raw else response.json()

            try:
                error_body = response.json()
            except Exception:
                error_body = {"error": {"type": "api_error", "code": "unknown", "message": response.text or f"HTTP {response.status_code}"}}
            error = SaturdayError.from_response(response.status_code, error_body, response.headers.get("Retry-After"))
            last_error = error

            if isinstance(error, RateLimitError):
                if error.daily_limit or error.retry_after > MAX_RETRY_AFTER_S:
                    raise error
                delay: float = error.retry_after
            elif response.status_code >= 500 and _retry_safe_on_server_error(method, path):
                delay = 2 ** attempt
            else:
                raise error
            if attempt < self._max_retries:
                time.sleep(delay)

        assert last_error is not None
        raise last_error


# --- Resources ---


class _NutritionResource:
    def __init__(self, client: Saturday):
        self._client = client

    def calculate(self, **request: Any) -> NutritionCalculateResponse:
        """Calculate a prescription for one session.

        Required: ``activity_type``, ``duration_min``. Send ``athlete_id`` to use a stored
        athlete, and ``meal_before_min`` (over 180 plans a fasted start) and ``is_race`` for
        exact numbers. A field name close to a real one (``type``, ``weight_kg``,
        ``is_race_event``) is refused with ``ValidationError`` code ``unsupported_field``.
        """
        return self._client.request("POST", "/v1/nutrition/calculate", json=request)

    def batch_calculate(self, scenarios: List[Dict[str, Any]]) -> BatchCalculateResponse:
        """Calculate up to 50 sessions. Each scenario counts as one call against your limits."""
        return self._client.request("POST", "/v1/nutrition/calculate/batch", json={"scenarios": scenarios})

    def product_fit(self, **request: Any) -> ProductFitResponse:
        """Size one catalog product against the athlete's prescription for a session.

        Required: ``athlete_id``, ``activity_type``, ``duration_min`` and ``product_id`` or
        ``product_query``. Optional: ``intensity_level``, ``thermal_stress_level``,
        ``meal_before_min``, ``is_race``.
        """
        return self._client.request("POST", "/v1/nutrition/products/fit", json=request)

    def compare_products(self, **request: Any) -> ProductCompareResponse:
        """Size two products (``product_a``, ``product_b``: each ``{"product_id"}`` or ``{"product_query"}``) and name the better fit."""
        return self._client.request("POST", "/v1/nutrition/products/compare", json=request)

    def extract(self, **request: Any) -> Dict[str, Any]:
        """Read a nutrition label from photos: ``image_base64`` or ``images_base64``."""
        return self._client.request("POST", "/v1/nutrition/extract", json=request)


class _AthletesResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create(self, **athlete: Any) -> Athlete:
        """Create an athlete. At least one of ``name``, ``email`` or ``external_id`` is required."""
        return self._client.request("POST", "/v1/athletes", json=athlete)

    def get(self, athlete_id: str) -> Athlete:
        return self._client.request("GET", f"/v1/athletes/{_seg(athlete_id)}")

    def list(
        self,
        *,
        limit: int = 50,
        cursor: Optional[str] = None,
        external_id: Optional[str] = None,
        profile_complete: Optional[bool] = None,
    ) -> AthleteListResponse:
        """One page of athletes. Pass ``pagination["next_cursor"]`` back as ``cursor``.

        ``external_id`` returns only the athletes you created with that id, newest first, in one
        page. The API does not deduplicate ``external_id``, so look an athlete up this way before
        creating one when a create may have been interrupted.
        """
        return self._client.request("GET", "/v1/athletes", params=_params(
            limit=limit, cursor=cursor, external_id=external_id, profile_complete=profile_complete,
        ))

    def update(self, athlete_id: str, **updates: Any) -> Athlete:
        """Update the fields you send. Settings sent here replace the stored settings."""
        return self._client.request("PATCH", f"/v1/athletes/{_seg(athlete_id)}", json=updates)

    def delete(self, athlete_id: str) -> None:
        """Delete the athlete and everything stored under them in your account. For a data-subject
        erasure request use ``erase``."""
        self._client.request("DELETE", f"/v1/athletes/{_seg(athlete_id)}")

    def get_settings(self, athlete_id: str) -> AthleteSettings:
        return self._client.request("GET", f"/v1/athletes/{_seg(athlete_id)}/settings")

    def update_settings(self, athlete_id: str, **settings: Any) -> AthleteSettings:
        """Replace the athlete's settings. Send every setting you want kept: omitted ones are cleared."""
        return self._client.request("PATCH", f"/v1/athletes/{_seg(athlete_id)}/settings", json=settings)

    def get_fueling_profile(self, athlete_id: str) -> FuelingProfile:
        """The athlete's Saturday app answers while they share them with you. Check ``sharing``:
        only ``on`` carries ``profile``; ``off`` and ``not_linked`` carry ``message``."""
        return self._client.request("GET", f"/v1/athletes/{_seg(athlete_id)}/fueling-profile")

    def batch_create(self, athletes: List[Dict[str, Any]]) -> BatchAthleteResponse:
        """Create up to 100 athletes in one call."""
        return self._client.request("POST", "/v1/athletes/batch", json={"athletes": athletes})

    def export(self, athlete_id: str) -> AthleteDataExport:
        """Everything Saturday holds for the athlete under your account (data portability)."""
        return self._client.request("POST", f"/v1/athletes/{_seg(athlete_id)}/export")

    def erase(self, athlete_id: str) -> None:
        """Erase the athlete for a right-to-erasure request: everything ``delete`` removes, plus
        ending the athlete's connected-provider grants and erasing the data those providers sent,
        with an audit record of the deletion."""
        self._client.request("POST", f"/v1/athletes/{_seg(athlete_id)}/delete")

    def list_consent(self, athlete_id: str) -> ConsentListResponse:
        return self._client.request("GET", f"/v1/athletes/{_seg(athlete_id)}/consent")

    def record_consent(self, athlete_id: str, *, consent_type: str, granted: bool) -> ConsentRecord:
        """``consent_type``: ``data_processing``, ``marketing`` or ``analytics``."""
        return self._client.request(
            "POST", f"/v1/athletes/{_seg(athlete_id)}/consent", json={"consent_type": consent_type, "granted": granted}
        )

    def revoke_consent(self, athlete_id: str, consent_id: str) -> None:
        self._client.request("DELETE", f"/v1/athletes/{_seg(athlete_id)}/consent/{_seg(consent_id)}")


class _ActivitiesResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create(self, athlete_id: str, **activity: Any) -> Activity:
        """Store a session. The fields are ``type`` and ``is_race_event``; ``activity_type`` and
        ``is_race`` are refused with ``ValidationError`` code ``unsupported_field``."""
        return self._client.request("POST", f"/v1/athletes/{_seg(athlete_id)}/activities", json=activity)

    def get(self, athlete_id: str, activity_id: str) -> Activity:
        return self._client.request("GET", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}")

    def list(self, athlete_id: str, *, limit: int = 20, cursor: Optional[str] = None) -> ActivityListResponse:
        """One page of the athlete's activities. Pass ``pagination["next_cursor"]`` back as ``cursor``."""
        return self._client.request(
            "GET", f"/v1/athletes/{_seg(athlete_id)}/activities", params=_params(limit=limit, cursor=cursor)
        )

    def update(self, athlete_id: str, activity_id: str, **updates: Any) -> Activity:
        return self._client.request("PATCH", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}", json=updates)

    def delete(self, athlete_id: str, activity_id: str) -> None:
        self._client.request("DELETE", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}")

    def calculate_prescription(self, athlete_id: str, activity_id: str) -> PrescriptionEnvelope:
        """Calculate the activity's prescription and store it."""
        return self._client.request("POST", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}/calculate")

    def get_prescription(self, athlete_id: str, activity_id: str) -> StoredPrescriptionResponse:
        """The stored prescription. ``NotFoundError`` until the activity has been calculated."""
        return self._client.request("GET", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}/prescription")

    def prep(self, athlete_id: str, activity_id: str, *, products: Optional[List[Dict[str, Any]]] = None) -> PrepResponse:
        """Size catalog products against the activity's prescription and show the gap left.

        Each product is ``{"product_id"}`` or ``{"product_query"}``, with optional ``servings``
        over the whole activity; without ``servings`` Saturday sizes it to what the plan still
        needs, in list order.
        """
        return self._client.request(
            "POST", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}/prep", json={"products": products or []}
        )

    def import_activities(
        self,
        athlete_id: str,
        activities: Sequence[Union[ImportActivityRequest, Dict[str, Any]]],
        *,
        calculate: Optional[bool] = None,
    ) -> ActivityImportResponse:
        """Import up to 200 activities. ``calculate=True`` calculates every one; an item's own
        ``"calculate": True`` calculates that item even when the request-level option is false."""
        payload: Dict[str, Any] = {"activities": activities}
        if calculate is not None:
            payload["calculate"] = calculate
        return self._client.request("POST", f"/v1/athletes/{_seg(athlete_id)}/activities/import", json=payload)

    def submit_feedback(self, athlete_id: str, activity_id: str, *, rating: int, notes: Optional[str] = None) -> ActivityFeedback:
        """``rating``: 1 (poor) to 5 (excellent)."""
        body: Dict[str, Any] = {"rating": rating}
        if notes is not None:
            body["notes"] = notes
        return self._client.request("POST", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}/feedback", json=body)


class _OnboardingResource:
    """The headless onboarding schema: the questions the hosted page asks. Render them in your
    UI, write the answers with ``athletes.update`` or ``athletes.update_settings``, and show the
    response's ``attribution`` with them."""

    def __init__(self, client: Saturday):
        self._client = client

    def questions(self) -> OnboardingQuestionsResponse:
        return self._client.request("GET", "/v1/onboarding/questions")


class _ReferenceResource:
    def __init__(self, client: Saturday):
        self._client = client

    def activity_types(self) -> ActivityTypesResponse:
        return self._client.request("GET", "/v1/activity-types")

    def settings_schema(self) -> SettingsSchemaResponse:
        return self._client.request("GET", "/v1/settings/schema")


class _InferResource:
    def __init__(self, client: Saturday):
        self._client = client

    def activity_type(self, **workout: Any) -> Dict[str, Any]:
        """Map a workout from your system (``activity_name``, ``tags``, ``device``...) to a Saturday activity type."""
        return self._client.request("POST", "/v1/infer/activity-type", json=workout)

    def brick_types(self, **workout: Any) -> Dict[str, Any]:
        """Split a multisport workout into its legs."""
        return self._client.request("POST", "/v1/infer/brick-types", json=workout)


class _PartnerResource:
    def __init__(self, client: Saturday):
        self._client = client

    def get(self) -> PartnerAccount:
        """Your account and its limits."""
        return self._client.request("GET", "/v1/partner")

    def usage(self, *, from_date: Optional[str] = None, to_date: Optional[str] = None) -> UsageResponse:
        """Calls over a period (``YYYY-MM-DD``, UTC), 30 days by default."""
        return self._client.request("GET", "/v1/partner/usage", params=_params(**{"from": from_date, "to": to_date}))

    def usage_daily(self, *, from_date: Optional[str] = None, to_date: Optional[str] = None) -> DailyUsageResponse:
        """Calls per UTC day, 7 days by default."""
        return self._client.request("GET", "/v1/partner/usage/daily", params=_params(**{"from": from_date, "to": to_date}))

    def list_api_keys(self) -> ApiKeyListResponse:
        return self._client.request("GET", "/v1/partner/api-keys")

    def create_api_key(self, name: str, *, scopes: Optional[List[str]] = None) -> CreatedApiKey:
        """Create a key. The response's ``key`` is shown once."""
        body: Dict[str, Any] = {"name": name}
        if scopes is not None:
            body["scopes"] = scopes
        return self._client.request("POST", "/v1/partner/api-keys", json=body)

    def revoke_api_key(self, key_id: str) -> None:
        self._client.request("DELETE", f"/v1/partner/api-keys/{_seg(key_id)}")

    def rotate_api_key(self, key_id: str) -> RotatedApiKey:
        """Replace a key with a new one and revoke the old one at once."""
        return self._client.request("POST", f"/v1/partner/api-keys/{_seg(key_id)}/rotate")


class _WebhooksResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create(self, url: str, events: List[str]) -> WebhookCreateResponse:
        """Register an endpoint. Store ``response["webhook"]["secret"]`` now: it signs every
        delivery and is never returned again."""
        return self._client.request("POST", "/v1/webhooks", json={"url": url, "events": events})

    def list(self) -> WebhookListResponse:
        return self._client.request("GET", "/v1/webhooks")

    def get(self, webhook_id: str) -> Webhook:
        return self._client.request("GET", f"/v1/webhooks/{_seg(webhook_id)}")

    def update(self, webhook_id: str, *, url: Optional[str] = None, events: Optional[List[str]] = None, active: Optional[bool] = None) -> Webhook:
        body = {k: v for k, v in {"url": url, "events": events, "active": active}.items() if v is not None}
        return self._client.request("PATCH", f"/v1/webhooks/{_seg(webhook_id)}", json=body)

    def delete(self, webhook_id: str) -> None:
        self._client.request("DELETE", f"/v1/webhooks/{_seg(webhook_id)}")

    def test(self, webhook_id: str) -> WebhookTestResponse:
        """Deliver a ``webhook.test`` event now and return the delivery record, with your endpoint's status code."""
        return self._client.request("POST", f"/v1/webhooks/{_seg(webhook_id)}/test")

    def list_deliveries(self, webhook_id: str) -> WebhookDeliveryList:
        """The 50 most recent delivery attempts to the endpoint, newest first."""
        return self._client.request("GET", f"/v1/webhooks/{_seg(webhook_id)}/deliveries")


class _OrganizationsResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create(self, display_name: str, *, description: Optional[str] = None, sport: Optional[str] = None) -> Organization:
        body = {k: v for k, v in {"display_name": display_name, "description": description, "sport": sport}.items() if v is not None}
        return self._client.request("POST", "/v1/organizations", json=body)

    def list(self) -> OrganizationListResponse:
        return self._client.request("GET", "/v1/organizations")

    def get(self, org_id: str) -> Organization:
        return self._client.request("GET", f"/v1/organizations/{_seg(org_id)}")

    def update(self, org_id: str, **updates: Any) -> Organization:
        """Update ``display_name``, ``description`` or ``sport``."""
        return self._client.request("PATCH", f"/v1/organizations/{_seg(org_id)}", json=updates)

    def add_member(self, org_id: str, email: str, *, role: str = "member", athlete_id: Optional[str] = None) -> OrganizationMember:
        body: Dict[str, Any] = {"email": email, "role": role}
        if athlete_id:
            body["athlete_id"] = athlete_id
        return self._client.request("POST", f"/v1/organizations/{_seg(org_id)}/members", json=body)

    def list_members(self, org_id: str) -> OrganizationMembersResponse:
        return self._client.request("GET", f"/v1/organizations/{_seg(org_id)}/members")

    def remove_member(self, org_id: str, member_id: str) -> None:
        self._client.request("DELETE", f"/v1/organizations/{_seg(org_id)}/members/{_seg(member_id)}")

    def set_offer(self, org_id: str, *, discount_percent: int, **options: Any) -> OrganizationOffer:
        """Set the organization's checkout discount (1 to 30 percent), replacing any active one.

        Options: ``applies_to_plan`` (``12_month`` or ``1_month``), ``negotiated_by``,
        ``starts_at`` and ``ends_at`` (Unix seconds), ``note``.
        """
        return self._client.request("PUT", f"/v1/organizations/{_seg(org_id)}/offer", json={"discount_percent": discount_percent, **options})

    def get_offer(self, org_id: str) -> OrganizationOffer:
        """The active offer. ``NotFoundError`` (``org_offer_not_found``) when there is none."""
        return self._client.request("GET", f"/v1/organizations/{_seg(org_id)}/offer")

    def delete_offer(self, org_id: str) -> None:
        self._client.request("DELETE", f"/v1/organizations/{_seg(org_id)}/offer")

    def create_subscription(self, org_id: str, *, type: str, seats: int, start_date: int, end_date: int) -> OrganizationSubscription:
        """Create a seat subscription (dates in Unix seconds). Seat subscriptions are set up
        with Saturday: without an allowance on your account this raises ``PermissionError``
        (``organization_subscription_restricted``)."""
        return self._client.request(
            "POST", f"/v1/organizations/{_seg(org_id)}/subscriptions",
            json={"type": type, "seats": seats, "start_date": start_date, "end_date": end_date},
        )

    def list_subscriptions(self, org_id: str) -> OrganizationSubscriptionListResponse:
        return self._client.request("GET", f"/v1/organizations/{_seg(org_id)}/subscriptions")

    def update_subscription(self, org_id: str, sub_id: str, **updates: Any) -> OrganizationSubscription:
        """Update ``seats``, ``status`` or ``end_date``."""
        return self._client.request("PATCH", f"/v1/organizations/{_seg(org_id)}/subscriptions/{_seg(sub_id)}", json=updates)

    def add_licenses(self, org_id: str, sub_id: str, licenses: List[Dict[str, Any]]) -> LicenseListResponse:
        """License athletes (``{"athlete_id", "email"?, "name"?}``) on a seat subscription."""
        return self._client.request(
            "POST", f"/v1/organizations/{_seg(org_id)}/subscriptions/{_seg(sub_id)}/licenses", json={"licenses": licenses}
        )

    def list_licenses(self, org_id: str, sub_id: str) -> LicenseListResponse:
        return self._client.request("GET", f"/v1/organizations/{_seg(org_id)}/subscriptions/{_seg(sub_id)}/licenses")

    def remove_license(self, org_id: str, sub_id: str, athlete_id: str) -> None:
        self._client.request(
            "DELETE", f"/v1/organizations/{_seg(org_id)}/subscriptions/{_seg(sub_id)}/licenses/{_seg(athlete_id)}"
        )


class _IntegrationsResource:
    def __init__(self, client: Saturday):
        self._client = client

    def sync(self, provider: str, *, athlete_id: str, access_token: str, **options: Any) -> IntegrationSyncResponse:
        """Pull the athlete's activities from the provider (``strava``) into Saturday.

        Options: ``refresh_token``, ``sync_types``, ``date_range`` (``{"from", "to"}``).
        """
        return self._client.request(
            "POST", f"/v1/integrations/{_seg(provider)}/sync",
            json={"athlete_id": athlete_id, "access_token": access_token, **options},
        )

    def status(self, provider: str, athlete_id: str) -> IntegrationStatusResponse:
        return self._client.request("GET", f"/v1/integrations/{_seg(provider)}/status", params={"athlete_id": athlete_id})

    def disconnect(self, provider: str, athlete_id: str) -> Dict[str, Any]:
        return self._client.request("POST", f"/v1/integrations/{_seg(provider)}/disconnect", json={"athlete_id": athlete_id})


class _TestingResource:
    """Test environment only (``sk_test_`` keys). In production these routes answer 404."""

    def __init__(self, client: Saturday):
        self._client = client

    def simulate_subscription(self, athlete_id: str, *, active: bool = True) -> SimulateSubscriptionResponse:
        """Give the athlete a simulated Saturday subscription (``active=True``) or take it away."""
        return self._client.request(
            "POST", f"/v1/test/athletes/{_seg(athlete_id)}/simulate-subscription", json={"active": active}
        )


class _MetaResource:
    def __init__(self, client: Saturday):
        self._client = client

    def discovery(self) -> Dict[str, Any]:
        """The routes and features this key can see."""
        return self._client.request("GET", "/v1/")

    def errors(self) -> ErrorCatalogResponse:
        """Every error code the API can return, with its HTTP status and whether a retry can succeed."""
        return self._client.request("GET", "/v1/errors")

    def health(self) -> HealthResponse:
        return self._client.request("GET", "/v1/health")


class _KnowledgeResource:
    """Early access: a key without access gets ``PermissionError`` (``feature_alpha``)."""

    def __init__(self, client: Saturday):
        self._client = client

    def search(self, query: str, *, limit: Optional[int] = None, category: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"query": query}
        if limit is not None:
            body["limit"] = limit
        if category:
            body["category"] = category
        return self._client.request("POST", "/v1/knowledge/search", json=body)

    def list_topics(self) -> Dict[str, Any]:
        return self._client.request("GET", "/v1/knowledge/topics")

    def get_article(self, article_id: str) -> Dict[str, Any]:
        return self._client.request("GET", f"/v1/knowledge/articles/{_seg(article_id)}")


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
        "urgent_threshold"}}, "combinators": [...], "quiet_hours": {...},
        "hourly_cap": {"enabled", "per_hour"}, "preset"}``.
        Triggers: under_fuel, symptom, low_rating, hyponatremia_pattern, dial_down,
        sleep_trend, went_quiet. Channels: in_portal, email, push, webhook (no SMS).
        ``hourly_cap`` limits the emails, and separately the pushes, one athlete's alerts
        send in any 60 minutes (``per_hour`` 1 to 12; with no scope setting it, on at 1).
        Leaving it out clears it at this scope. ``channel_config`` (the email address and push
        devices alerts go to) is replaced too: send back the one ``get_notification_rules``
        returned. Left out at the overall scope, email and push alerts turn off.
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
