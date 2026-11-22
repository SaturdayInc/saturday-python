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

from saturday.errors import MAX_RETRY_WAIT_SECONDS, RateLimitError, SaturdayError
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
    DiscoveryResponse,
    ErrorCatalogResponse,
    FuelingProfile,
    HealthResponse,
    ImportActivityRequest,
    IntegrationDisconnectResponse,
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
        max_retries: Retries for throttled or briefly paced 429s and for 5xx responses (not on a POST that creates or changes a record). Defaults to 3; 0 disables retries.
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
        """Send an authenticated request, retrying up to ``max_retries`` times where a retry can
        succeed: a 429 throttle or short pacing wait (``RateLimitError.retryable``), and a 5xx after
        its ``Retry-After`` or 1, 2 and 4 seconds, except on a POST that creates or changes a record,
        since the server may have done the write. Daily ceilings, blocks, waits over 30 seconds and
        every other 4xx raise at once.
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
                if not error.retryable:
                    raise error
                delay: float = error.retry_after  # type: ignore[assignment]
            elif response.status_code >= 500 and _retry_safe_on_server_error(method, path):
                if error.retry_after is not None and error.retry_after > MAX_RETRY_WAIT_SECONDS:
                    raise error
                delay = error.retry_after if error.retry_after is not None else 2 ** attempt
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

        Required: ``activity_type``, and ``duration_min`` for a single sport. Send ``athlete_id``
        to use a stored athlete, and every session input (``intensity_level``,
        ``thermal_stress_level``, ``meal_before_min``: over 180 plans a fasted start, ``is_race``)
        for exact numbers. ``sweat_level``, ``satiety_level`` and ``fitness_level`` take 1, 3, 5,
        7 or 9, ``saltiness`` 1, 5 or 9, and
        ``carb_upper_limit_override`` 50 to 150 g/hr in steps of 10.

        A brick or triathlon is one call: ``activity_type="brick"`` (or ``"triathlon"``) with
        ``legs``, 2 to 10 dicts of ``activity_type``, ``duration_min``, ``intensity_level`` and
        ``thermal_stress_level``; leave the top-level effort and heat out. The answer's ``legs``
        gives each leg's share.

        A field the request does not take is refused with ``ValidationError`` code
        ``unsupported_field``: ``param`` names it and ``suggestion`` the field it was probably
        meant to be.
        """
        return self._client.request("POST", "/v1/nutrition/calculate", json=request)

    def batch_calculate(self, scenarios: List[Dict[str, Any]]) -> BatchCalculateResponse:
        """Calculate up to 50 sessions. Each scenario counts as one call against your limits."""
        return self._client.request("POST", "/v1/nutrition/calculate/batch", json={"scenarios": scenarios})

    def product_fit(self, **request: Any) -> ProductFitResponse:
        """Size one catalog product against the athlete's prescription for a session.

        Required: ``athlete_id``, ``activity_type`` and ``product_id`` or ``product_query``, with
        ``duration_min`` for a single sport. A brick or triathlon carries ``legs`` (each with
        ``activity_type``, ``duration_min``, ``intensity_level`` and ``thermal_stress_level``, as on
        ``calculate``) and its exact answer sizes the product for each leg under ``legs``. Send
        ``intensity_level``, ``thermal_stress_level`` (on the legs for a brick or triathlon),
        ``meal_before_min`` and ``is_race`` too: one left out computes at its everyday value and
        the plan is the middle of the athlete's ranges, with ``plan_basis`` naming it. A session
        error names its field in ``ValidationError.param``.

        For an athlete on the trial, each call spends one of the athlete's trial calls, as
        ``calculate`` does; past today's calls the plan is from ranges, with
        ``plan_basis["source"]`` ``trial_allowance``.
        """
        return self._client.request("POST", "/v1/nutrition/products/fit", json=request)

    def compare_products(self, **request: Any) -> ProductCompareResponse:
        """Size two products (``product_a``, ``product_b``: each ``{"product_id"}`` or ``{"product_query"}``) and name the better fit.

        The session fields are ``product_fit``'s; a brick or triathlon with ``legs`` is compared
        for each leg under ``legs`` too. Spends one trial call, as ``product_fit`` does.
        """
        return self._client.request("POST", "/v1/nutrition/products/compare", json=request)

    def extract(self, **request: Any) -> Dict[str, Any]:
        """Read a nutrition label from photos: ``image_base64`` or ``images_base64``."""
        return self._client.request("POST", "/v1/nutrition/extract", json=request)


class _AthletesResource:
    def __init__(self, client: Saturday):
        self._client = client

    def create(self, **athlete: Any) -> Athlete:
        """Create an athlete. At least one of ``name``, ``email`` or ``external_id`` is required.

        ``external_id`` is unique within your partner account: one another of your athletes holds
        creates nothing and raises ``ConflictError`` (``athlete_exists``) whose ``athlete_id`` names
        that athlete, so a retried create is safe.
        """
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
        page. Athletes created before ``external_id`` became unique may share one.
        """
        return self._client.request("GET", "/v1/athletes", params=_params(
            limit=limit, cursor=cursor, external_id=external_id, profile_complete=profile_complete,
        ))

    def update(self, athlete_id: str, **updates: Any) -> Athlete:
        """Update the fields you send. Settings sent here replace the stored settings. An
        ``external_id`` another of your athletes holds changes nothing and raises ``ConflictError``
        (``athlete_exists``)."""
        return self._client.request("PATCH", f"/v1/athletes/{_seg(athlete_id)}", json=updates)

    def delete(self, athlete_id: str) -> None:
        """Delete the athlete and everything stored under them in your account. For a
        right-to-erasure request use ``erase``."""
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
        """Create up to 100 athletes in one call. An item whose ``external_id`` one of your athletes
        holds, an earlier item of the same batch included, fails with ``athlete_exists`` and that
        athlete's id in ``errors[i]["athlete_id"]``."""
        return self._client.request("POST", "/v1/athletes/batch", json={"athletes": athletes})

    def export(self, athlete_id: str) -> AthleteDataExport:
        """Everything Saturday holds for the athlete under your account (data portability)."""
        return self._client.request("POST", f"/v1/athletes/{_seg(athlete_id)}/export")

    def erase(self, athlete_id: str) -> None:
        """Erase everything Saturday holds for you about the athlete, for a right-to-erasure request.

        Each provider connection you supplied for the athlete with ``integrations.sync`` is revoked
        at the provider first; then the athlete and everything stored under them are deleted
        (activities, those synced through your connections included, prescriptions, feedback,
        consent records, usage logs) with the athlete's link to a Saturday account. A linked
        athlete's own Saturday account is not changed. A ``SaturdayError`` with status 503 and code
        ``provider_erasure_incomplete`` means a connection could not be revoked yet and nothing was
        deleted: call ``erase`` again.
        """
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
        """Store a session: one sport with ``duration_min``, or ``type="brick"`` (or
        ``"triathlon"``) with ``legs``, 2 to 10 dicts of ``type``, ``duration_min``,
        ``intensity_level`` and ``thermal_stress_level``. The fields are ``type`` and
        ``is_race_event``; any field the request does not take (``activity_type`` and ``is_race``
        included) is refused with ``ValidationError`` code ``unsupported_field``."""
        return self._client.request("POST", f"/v1/athletes/{_seg(athlete_id)}/activities", json=activity)

    def get(self, athlete_id: str, activity_id: str) -> Activity:
        return self._client.request("GET", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}")

    def list(self, athlete_id: str, *, limit: int = 20, cursor: Optional[str] = None) -> ActivityListResponse:
        """One page of the athlete's activities. Pass ``pagination["next_cursor"]`` back as ``cursor``."""
        return self._client.request(
            "GET", f"/v1/athletes/{_seg(athlete_id)}/activities", params=_params(limit=limit, cursor=cursor)
        )

    def update(self, athlete_id: str, activity_id: str, **updates: Any) -> Activity:
        """Change the fields you send. ``legs`` replaces a brick's or triathlon's legs and sets
        ``duration_min`` to their total. Changing ``type`` to brick or triathlon needs ``legs`` in
        the same call unless the activity holds legs already; changing it to a single sport removes
        the legs. A brick or triathlon refuses ``intensity_level``, ``thermal_stress_level`` and a
        ``duration_min`` other than its legs' total: change its legs instead.

        A change to ``type``, ``legs``, ``duration_min``, ``intensity_level``,
        ``thermal_stress_level``, ``is_race_event`` or ``meal_before_min`` removes the stored
        prescription: ``get_prescription`` raises ``NotFoundError`` (``prescription_not_found``) until
        you calculate the activity again. A field sent at its stored value changes nothing, and
        ``external_id`` alone keeps the prescription."""
        return self._client.request("PATCH", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}", json=updates)

    def delete(self, athlete_id: str, activity_id: str) -> None:
        self._client.request("DELETE", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}")

    def calculate_prescription(self, athlete_id: str, activity_id: str) -> PrescriptionEnvelope:
        """Calculate the activity's prescription and store it."""
        return self._client.request("POST", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}/calculate")

    def get_prescription(self, athlete_id: str, activity_id: str) -> StoredPrescriptionResponse:
        """The prescription calculated for the activity's session as it stands. ``NotFoundError``
        (``prescription_not_found``) until the activity has been calculated, and again after an
        ``update`` that changes the session, until it is calculated again."""
        return self._client.request("GET", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}/prescription")

    def prep(
        self,
        athlete_id: str,
        activity_id: str,
        *,
        products: Optional[List[Dict[str, Any]]] = None,
        legs: Optional[List[Dict[str, Any]]] = None,
    ) -> PrepResponse:
        """Size catalog products against the activity's prescription and show the gap left.

        Each product is ``{"product_id"}`` or ``{"product_query"}``, with optional ``servings``
        over the whole activity; without ``servings`` Saturday sizes it to what the plan still
        needs, in list order.

        A brick or triathlon with exact numbers is prepped leg by leg under ``legs``: ``products``
        is sized against each leg, its ``servings`` counting per leg, or send ``legs``, one
        ``{"products": [...]}`` per leg of the activity in order, for a list per leg. Send one or
        the other: both raise ``ValidationError`` (``invalid_value`` on ``products``). ``legs`` on a
        single session, or with another count, raises ``ValidationError`` with ``param`` ``legs``.
        """
        body: Dict[str, Any] = {"legs": legs} if legs is not None else {}
        if products is not None or legs is None:
            body["products"] = products or []
        return self._client.request("POST", f"/v1/athletes/{_seg(athlete_id)}/activities/{_seg(activity_id)}/prep", json=body)

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

    def activity_types(self, *, activity_type: Optional[str] = None) -> ActivityTypesResponse:
        """The single sports, and with a partner API key ``linked_session_types``: brick and
        triathlon with the rules for their legs. ``activity_type`` narrows both lists to that type."""
        return self._client.request("GET", "/v1/activity-types", params=_params(activity_type=activity_type))

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
        """Your account and its limits, the trial's length and bounds included (``rate_limits``)."""
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
        """Update ``seats``, ``status``, ``start_date`` or ``end_date`` (Unix seconds). Any other
        field is refused with ``ValidationError`` code ``unsupported_field``."""
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

    def sync(
        self,
        provider: str,
        *,
        athlete_id: str,
        access_token: str,
        date_range: Optional[Dict[str, str]] = None,
        sync_types: Optional[List[str]] = None,
    ) -> IntegrationSyncResponse:
        """Fetch the activities of the intervals.icu user an access token belongs to and store each
        as an activity of your athlete.

        ``provider`` is ``"intervals_icu"``, the only one: Strava and TrainingPeaks tokens raise
        ``ValidationError`` (``invalid_provider``). Send an OAuth access token your intervals.icu app
        obtained from that user; the calls count against your app's intervals.icu limit.
        ``date_range`` is ``{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}``, both or neither; without
        it, the last 7 days. ``sync_types`` defaults to ``["activities"]``. The result is under
        ``result``.
        """
        body: Dict[str, Any] = {"athlete_id": athlete_id, "access_token": access_token, "sync_types": sync_types or ["activities"]}
        if date_range is not None:
            body["date_range"] = date_range
        return self._client.request("POST", f"/v1/integrations/{_seg(provider)}/sync", json=body)

    def status(self, provider: str, athlete_id: str) -> IntegrationStatusResponse:
        """``provider``: ``intervals_icu``, ``strava`` or ``training_peaks``."""
        return self._client.request("GET", f"/v1/integrations/{_seg(provider)}/status", params={"athlete_id": athlete_id})

    def disconnect(self, provider: str, athlete_id: str) -> IntegrationDisconnectResponse:
        """End the connection you supplied for the athlete with ``sync``: it is revoked at the
        provider and its tokens are removed. Activities already synced stay. A linked athlete's own
        connection to the provider in their Saturday account is not changed. A provider the athlete
        never connected raises ``NotFoundError`` (code ``integration_not_found``), and nothing
        reaches the provider."""
        return self._client.request("POST", f"/v1/integrations/{_seg(provider)}/disconnect", json={"athlete_id": athlete_id})


class _TestingResource:
    """Test environment only (``sk_test_`` keys). In production these routes answer 404."""

    def __init__(self, client: Saturday):
        self._client = client

    def simulate_subscription(self, athlete_id: str, *, active: bool = True) -> SimulateSubscriptionResponse:
        """Give the athlete a simulated Saturday subscription (``active=True``) or take it away.

        A key marks at most 10 athletes a UTC day (marking one already marked today again is free);
        past that it raises ``RateLimitError`` with code ``simulated_subscriber_daily_limit_reached``
        and ``resets_at``. Each simulated subscriber gets up to 100 exact answers over 3 distinct
        profiles; past either, answers are ranges with ``simulated_limit_reached``. These are the
        API's defaults.
        """
        return self._client.request(
            "POST", f"/v1/test/athletes/{_seg(athlete_id)}/simulate-subscription", json={"active": active}
        )


class _MetaResource:
    def __init__(self, client: Saturday):
        self._client = client

    def discovery(self) -> DiscoveryResponse:
        """The routes and features this key can see, and how a key is had (``get_a_key``)."""
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
