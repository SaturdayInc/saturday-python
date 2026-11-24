import importlib
import json
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

import httpx
import pytest

from saturday import Saturday


FIXTURES = json.loads(Path(__file__).with_name("fixtures").joinpath("contracts.json").read_text())
MODELS = {
    "activity_exact": "ActivityPrescription", "activity_banded": "ActivityPrescription",
    "nutrition_exact": "NutritionCalculateResponse", "nutrition_banded": "NutritionCalculateResponse",
    "nutrition_banded_signed_in": "NutritionCalculateResponse",
    "nutrition_teaser": "NutritionCalculateResponse", "nutrition_trial": "NutritionCalculateResponse", "nutrition_zero": "NutritionCalculateResponse",
    "activity_full": "PrescriptionEnvelope", "activity_full_banded": "PrescriptionEnvelope",
    "activity_teaser": "PrescriptionEnvelope", "activity_trial": "PrescriptionEnvelope",
    "stored_exact": "StoredPrescriptionResponse", "stored_banded": "StoredPrescriptionResponse",
    "activity": "Activity", "athlete": "Athlete", "feedback": "ActivityFeedback",
    "list_athletes_next": "AthleteListResponse", "list_athletes_empty": "AthleteListResponse",
    "list_activities_next": "ActivityListResponse", "list_activities_empty": "ActivityListResponse",
    "settings_full": "AthleteSettings", "settings_empty": "AthleteSettings", "settings_updated": "AthleteSettings",
    "batch_partial": "BatchCalculateResponse", "batch_all_failed": "BatchCalculateResponse", "batch_estimate": "BatchCalculateResponse",
    "athletes_partial": "BatchAthleteResponse", "athletes_all_failed": "BatchAthleteResponse",
    "import_plain": "ActivityImportResponse", "import_calculated": "ActivityImportResponse",
    "import_calc_failed": "ActivityImportResponse", "import_all_failed": "ActivityImportResponse",
    "billing_seat_state": "CoachSeatState", "billing_seat_state_pro": "CoachSeatState",
    "billing_ledger_page": "CoachLedgerPage", "billing_ledger_empty": "CoachLedgerPage",
    "billing_tier_status": "CoachTierStatus", "billing_tier_status_empty": "CoachTierStatus",
    "billing_connect_summary": "CoachConnectSummary", "billing_connect_summary_none": "CoachConnectSummary",
    "billing_connect_earnings": "CoachConnectEarnings", "billing_connect_earnings_empty": "CoachConnectEarnings",
    "billing_connect_transactions": "CoachConnectChargesPage", "billing_connect_transactions_end": "CoachConnectChargesPage",
    "billing_connect_arrangements": "CoachConnectArrangements",
    "athlete_sharing": "Athlete",
    "fueling_profile_on": "FuelingProfile", "fueling_profile_off": "FuelingProfile", "fueling_profile_not_linked": "FuelingProfile",
    "webhook_profile_sharing_changed": "ProfileSharingChangedEvent", "webhook_fueling_profile_updated": "FuelingProfileUpdatedEvent",
    "onboarding_link": "OnboardingLink", "partner_profile": "PartnerAccount",
}


def matches(value, annotation):
    if annotation is Any:
        return True
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Union:
        return any(matches(value, item) for item in args)
    if origin is Literal:
        return value in args
    if origin is list:
        return isinstance(value, list) and all(matches(item, args[0]) for item in value)
    if origin is dict:
        return isinstance(value, dict) and all(matches(item, args[1]) for item in value.values())
    if hasattr(annotation, "__required_keys__"):
        hints = get_type_hints(annotation)
        return isinstance(value, dict) and annotation.__required_keys__ <= value.keys() and all(
            key in hints and matches(item, hints[key]) for key, item in value.items()
        )
    if annotation is float:
        return type(value) in (int, float)
    return type(value) is annotation


@pytest.mark.parametrize("name", MODELS)
def test_backend_serialization_matches_typed_models(name):
    types = importlib.import_module("saturday.types")
    model = getattr(types, MODELS[name])
    assert matches(FIXTURES[name], model)
    assert model(**FIXTURES[name]) == FIXTURES[name]
    assert type(model(**FIXTURES[name])) is dict


@pytest.mark.parametrize("name", [name for name in MODELS if (name.startswith(("nutrition_", "activity_", "stored_", "batch_", "athletes_")) or name == "feedback") and name not in ("activity_exact", "activity_banded")])
def test_raw_responses_stay_dictionaries(name):
    payload = {**FIXTURES[name], "future_field": {"preserved": True}}
    client = Saturday(api_key="sk_test_fixture", max_retries=0)
    client._client.close()
    client._client = httpx.Client(base_url=client._base_url, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    with client:
        if name.startswith("nutrition_"):
            result = client.nutrition.calculate(activity_type="bike", duration_min=120)
        elif name.startswith("activity_"):
            result = client.activities.calculate_prescription("ath_1", "act_1")
        elif name.startswith("stored_"):
            result = client.activities.get_prescription("ath_1", "act_1")
        elif name.startswith("batch_"):
            result = client.nutrition.batch_calculate([{"activity_type": "bike", "duration_min": 120}])
        elif name == "feedback":
            result = client.activities.submit_feedback("ath_1", "act_1", rating=4)
        else:
            result = client.athletes.batch_create([{"name": "Fixture"}])
    assert type(result) is dict
    assert result == payload


@pytest.mark.parametrize("name", ["import_plain", "import_calculated", "import_calc_failed", "import_all_failed"])
@pytest.mark.parametrize("calculate", [None, False, True])
def test_activity_import_flags_and_raw_results(name, calculate):
    activities = [{"type": "bike", "duration_min": 120, "external_id": "partner-act", "calculate": True}]

    def send(request):
        expected = {"activities": activities}
        if calculate is not None:
            expected["calculate"] = calculate
        assert request.url.path == "/v1/athletes/ath_1/activities/import"
        assert json.loads(request.content) == expected
        return httpx.Response(200, json=FIXTURES[name])

    client = Saturday(api_key="sk_test_fixture", max_retries=0)
    client._client.close()
    client._client = httpx.Client(base_url=client._base_url, transport=httpx.MockTransport(send))
    with client:
        result = client.activities.import_activities("ath_1", activities, calculate=calculate)
    assert type(result) is dict
    assert result == FIXTURES[name]


def test_calculating_is_not_the_import_default():
    def send(request):
        assert json.loads(request.content) == {"activities": [{"type": "bike", "duration_min": 120}]}
        return httpx.Response(200, json=FIXTURES["import_plain"])

    client = Saturday(api_key="sk_test_fixture", max_retries=0)
    client._client.close()
    client._client = httpx.Client(base_url=client._base_url, transport=httpx.MockTransport(send))
    with client:
        client.activities.import_activities("ath_1", [{"type": "bike", "duration_min": 120}])


@pytest.mark.parametrize("name", ["list_athletes_next", "list_athletes_empty", "list_activities_next", "list_activities_empty"])
@pytest.mark.parametrize("options", [{}, {"limit": 1, "cursor": "1700000000"}])
def test_pagination_and_query_defaults_are_preserved(name, options):
    payload = {**FIXTURES[name], "future_field": True}
    athletes = name.startswith("list_athletes")

    def send(request):
        assert request.method == "GET"
        assert request.url.path == ("/v1/athletes" if athletes else "/v1/athletes/ath_1/activities")
        assert dict(request.url.params) == {key: str(value) for key, value in (options or ({"limit": 50} if athletes else {})).items()}
        return httpx.Response(200, json=payload)

    client = Saturday(api_key="sk_test_fixture", max_retries=0)
    client._client.close()
    client._client = httpx.Client(base_url=client._base_url, transport=httpx.MockTransport(send))
    with client:
        result = client.athletes.list(**options) if athletes else client.activities.list("ath_1", **options)
    assert type(result) is dict
    assert result == payload


@pytest.mark.parametrize("name", ["settings_full", "settings_empty", "settings_updated"])
def test_flat_settings_payload_and_raw_return_are_preserved(name):
    payload = {**FIXTURES[name], "future_field": True}
    methods = []

    def send(request):
        methods.append(request.method)
        assert request.url.path == "/v1/athletes/ath_1/settings"
        if request.method == "PATCH":
            assert json.loads(request.content) == {"sweat_level": 5, "gut_distress": False}
        return httpx.Response(200, json=payload)

    client = Saturday(api_key="sk_test_fixture", max_retries=0)
    client._client.close()
    client._client = httpx.Client(base_url=client._base_url, transport=httpx.MockTransport(send))
    with client:
        assert client.athletes.get_settings("ath_1") == payload
        result = client.athletes.update_settings("ath_1", sweat_level=5, gut_distress=False)
    assert type(result) is dict
    assert result == payload
    assert methods == ["GET", "PATCH"]


@pytest.mark.parametrize("name, method, kwargs, path, query", [
    ("billing_seat_state", "seat_state", {}, "/v1/coach/billing/seat-state", {}),
    ("billing_seat_state", "seat_state", {"org_id": "org_1"}, "/v1/coach/billing/seat-state", {"org_id": "org_1"}),
    ("billing_ledger_page", "ledger", {"view": "inflows", "limit": 50, "cursor": "1749480000000"}, "/v1/coach/billing/ledger", {"view": "inflows", "limit": "50", "cursor": "1749480000000"}),
    ("billing_ledger_empty", "ledger", {}, "/v1/coach/billing/ledger", {}),
    ("billing_tier_status", "tier_status", {}, "/v1/coach/billing/tier-status", {}),
    ("billing_connect_summary_none", "connect_summary", {}, "/v1/coach/billing/connect/summary", {}),
    ("billing_connect_earnings", "connect_earnings", {}, "/v1/coach/billing/connect/earnings", {}),
    ("billing_connect_transactions", "connect_transactions", {"limit": 20, "cursor": "1749480000000"}, "/v1/coach/billing/connect/transactions", {"limit": "20", "cursor": "1749480000000"}),
    ("billing_connect_arrangements", "connect_arrangements", {}, "/v1/coach/billing/connect/arrangements", {}),
])
def test_coach_billing_reads_are_gets_that_keep_the_raw_payload(name, method, kwargs, path, query):
    payload = {**FIXTURES[name], "future_field": True}

    def send(request):
        assert request.method == "GET"
        assert request.url.path == path
        assert dict(request.url.params) == query
        return httpx.Response(200, json=payload)

    client = Saturday(api_key="cp_test_fixture", max_retries=0)
    client._client.close()
    client._client = httpx.Client(base_url=client._base_url, transport=httpx.MockTransport(send))
    with client:
        result = getattr(client.coach, method)(**kwargs)
    assert type(result) is dict
    assert result == payload


@pytest.mark.parametrize("name", ["fueling_profile_on", "fueling_profile_off", "fueling_profile_not_linked"])
def test_get_fueling_profile_reads_the_route_and_keeps_the_raw_payload(name):
    payload = {**FIXTURES[name], "future_field": True}

    def send(request):
        assert request.method == "GET"
        assert request.url.path == "/v1/athletes/ath_1/fueling-profile"
        assert request.content == b""
        return httpx.Response(200, json=payload)

    client = Saturday(api_key="sk_test_fixture", max_retries=0)
    client._client.close()
    client._client = httpx.Client(base_url=client._base_url, transport=httpx.MockTransport(send))
    with client:
        result = client.athletes.get_fueling_profile("ath_1")
    assert type(result) is dict
    assert result == payload


def test_shared_profile_carries_every_answer_and_unshared_carries_none():
    from saturday.types import FuelingProfileAnswers, FuelingProfileFieldName

    shared = FIXTURES["fueling_profile_on"]
    assert set(shared["profile"]) == set(FuelingProfileAnswers.__annotations__) == set(get_args(FuelingProfileFieldName))
    for name in ("fueling_profile_off", "fueling_profile_not_linked"):
        assert "profile" not in FIXTURES[name] and "updated_at" not in FIXTURES[name]
        assert isinstance(FIXTURES[name]["message"], str)


@pytest.mark.parametrize("call, method, path, body", [
    (lambda c: c.nutrition.extract(image_base64="AA=="),
     "POST", "/v1/nutrition/extract", {"image_base64": "AA=="}),
    (lambda c: c.infer.activity_type(activity_name="Morning Ride", tags=["bike"]),
     "POST", "/v1/infer/activity-type", {"activity_name": "Morning Ride", "tags": ["bike"]}),
    (lambda c: c.infer.brick_types(activity_name="Brick session"),
     "POST", "/v1/infer/brick-types", {"activity_name": "Brick session"}),
    (lambda c: c.integrations.disconnect("intervals_icu", "ath_1"),
     "POST", "/v1/integrations/intervals_icu/disconnect", {"athlete_id": "ath_1"}),
    (lambda c: c.organizations.update_subscription("org_1", "sub_1", seats=10),
     "PATCH", "/v1/organizations/org_1/subscriptions/sub_1", {"seats": 10}),
    (lambda c: c.organizations.add_licenses("org_1", "sub_1", [{"athlete_id": "ath_1"}]),
     "POST", "/v1/organizations/org_1/subscriptions/sub_1/licenses",
     {"licenses": [{"athlete_id": "ath_1"}]}),
    (lambda c: c.organizations.list_licenses("org_1", "sub_1"),
     "GET", "/v1/organizations/org_1/subscriptions/sub_1/licenses", None),
    (lambda c: c.organizations.remove_license("org_1", "sub_1", "ath_1"),
     "DELETE", "/v1/organizations/org_1/subscriptions/sub_1/licenses/ath_1", None),
    (lambda c: c.knowledge.list_topics(), "GET", "/v1/knowledge/topics", None),
    (lambda c: c.knowledge.get_article("art_1"), "GET", "/v1/knowledge/articles/art_1", None),
    (lambda c: c.activities.get("ath_1", "act_1"),
     "GET", "/v1/athletes/ath_1/activities/act_1", None),
    (lambda c: c.organizations.get("org_1"), "GET", "/v1/organizations/org_1", None),
    (lambda c: c.organizations.update("org_1", description="Weekend riders"),
     "PATCH", "/v1/organizations/org_1", {"description": "Weekend riders"}),
    (lambda c: c.organizations.get_offer("org_1"), "GET", "/v1/organizations/org_1/offer", None),
])
def test_untested_methods_send_the_documented_request(call, method, path, body):
    def send(request):
        assert request.method == method
        assert request.url.path == path
        assert (json.loads(request.content) if request.content else None) == body
        return httpx.Response(200, json={"ok": True})

    client = Saturday(api_key="sk_test_fixture", max_retries=0)
    client._client.close()
    client._client = httpx.Client(
        base_url=client._base_url, transport=httpx.MockTransport(send))
    with client:
        call(client)


@pytest.mark.parametrize("call, method, path, params, body", [
    (lambda c: c.nutrition.compare_products(athlete_id="ath_1", activity_type="run", duration_min=60, product_a={"product_id": "p1"}, product_b={"product_query": "gel"}),
     "POST", "/v1/nutrition/products/compare", {},
     {"athlete_id": "ath_1", "activity_type": "run", "duration_min": 60, "product_a": {"product_id": "p1"}, "product_b": {"product_query": "gel"}}),
    (lambda c: c.athletes.get("ath_1"), "GET", "/v1/athletes/ath_1", {}, None),
    (lambda c: c.athletes.update("ath_1", name="Jo", weight_kg=62),
     "PATCH", "/v1/athletes/ath_1", {}, {"name": "Jo", "weight_kg": 62}),
    (lambda c: c.athletes.export("ath_1"), "POST", "/v1/athletes/ath_1/export", {}, None),
    (lambda c: c.athletes.list_consent("ath_1"), "GET", "/v1/athletes/ath_1/consent", {}, None),
    (lambda c: c.athletes.record_consent("ath_1", consent_type="marketing", granted=True),
     "POST", "/v1/athletes/ath_1/consent", {}, {"consent_type": "marketing", "granted": True}),
    (lambda c: c.athletes.revoke_consent("ath_1", "con_1"),
     "DELETE", "/v1/athletes/ath_1/consent/con_1", {}, None),
    (lambda c: c.activities.create("ath_1", type="run", duration_min=60),
     "POST", "/v1/athletes/ath_1/activities", {}, {"type": "run", "duration_min": 60}),
    (lambda c: c.activities.update("ath_1", "act_1", duration_min=90),
     "PATCH", "/v1/athletes/ath_1/activities/act_1", {}, {"duration_min": 90}),
    (lambda c: c.activities.delete("ath_1", "act_1"),
     "DELETE", "/v1/athletes/ath_1/activities/act_1", {}, None),
    (lambda c: c.reference.settings_schema(), "GET", "/v1/settings/schema", {}, None),
    (lambda c: c.reference.activity_types(activity_type="brick"),
     "GET", "/v1/activity-types", {"activity_type": "brick"}, None),
    (lambda c: c.partner.get(), "GET", "/v1/partner", {}, None),
    (lambda c: c.partner.usage(from_date="2026-11-01", to_date="2026-11-07"),
     "GET", "/v1/partner/usage", {"from": "2026-11-01", "to": "2026-11-07"}, None),
    (lambda c: c.partner.usage(), "GET", "/v1/partner/usage", {}, None),
    (lambda c: c.partner.usage_daily(from_date="2026-11-01", to_date="2026-11-07"),
     "GET", "/v1/partner/usage/daily", {"from": "2026-11-01", "to": "2026-11-07"}, None),
    (lambda c: c.partner.list_api_keys(), "GET", "/v1/partner/api-keys", {}, None),
    (lambda c: c.partner.create_api_key("ci", scopes=["read"]),
     "POST", "/v1/partner/api-keys", {}, {"name": "ci", "scopes": ["read"]}),
    (lambda c: c.partner.create_api_key("ci"),
     "POST", "/v1/partner/api-keys", {}, {"name": "ci"}),
    (lambda c: c.partner.revoke_api_key("key_1"), "DELETE", "/v1/partner/api-keys/key_1", {}, None),
    (lambda c: c.partner.rotate_api_key("key_1"), "POST", "/v1/partner/api-keys/key_1/rotate", {}, None),
    (lambda c: c.webhooks.list(), "GET", "/v1/webhooks", {}, None),
    (lambda c: c.webhooks.get("wh_1"), "GET", "/v1/webhooks/wh_1", {}, None),
], ids=[
    "compare", "athlete-get", "athlete-update", "export", "consent-list", "consent-record",
    "consent-revoke", "activity-create", "activity-update", "activity-delete",
    "settings-schema", "activity-types-filter", "partner-get", "usage-dates", "usage-default",
    "usage-daily", "key-list", "key-create-scopes", "key-create-plain", "key-revoke",
    "key-rotate", "webhook-list", "webhook-get",
])
def test_live_only_reads_send_the_documented_request(call, method, path, params, body):
    def send(request):
        assert request.method == method
        assert request.url.path == path
        assert dict(request.url.params) == params
        assert (json.loads(request.content) if request.content else None) == body
        return httpx.Response(200, json={"ok": True})

    client = Saturday(api_key="sk_test_fixture", max_retries=0)
    client._client.close()
    client._client = httpx.Client(
        base_url=client._base_url, transport=httpx.MockTransport(send))
    with client:
        call(client)


@pytest.mark.parametrize("call, method, path, params, body", [
    (lambda c: c.webhooks.update("wh_1", url="https://example.com/h", events=["athlete.created"], active=True),
     "PATCH", "/v1/webhooks/wh_1", {}, {"url": "https://example.com/h", "events": ["athlete.created"], "active": True}),
    (lambda c: c.webhooks.update("wh_1", active=False),
     "PATCH", "/v1/webhooks/wh_1", {}, {"active": False}),
    (lambda c: c.webhooks.delete("wh_1"), "DELETE", "/v1/webhooks/wh_1", {}, None),
    (lambda c: c.webhooks.test("wh_1"), "POST", "/v1/webhooks/wh_1/test", {}, None),
    (lambda c: c.organizations.create("Riders", description="Weekend", sport="cycling"),
     "POST", "/v1/organizations", {}, {"display_name": "Riders", "description": "Weekend", "sport": "cycling"}),
    (lambda c: c.organizations.create("Riders"),
     "POST", "/v1/organizations", {}, {"display_name": "Riders"}),
    (lambda c: c.organizations.add_member("org_1", "a@example.com", role="admin", athlete_id="ath_1"),
     "POST", "/v1/organizations/org_1/members", {}, {"email": "a@example.com", "role": "admin", "athlete_id": "ath_1"}),
    (lambda c: c.organizations.add_member("org_1", "a@example.com"),
     "POST", "/v1/organizations/org_1/members", {}, {"email": "a@example.com", "role": "member"}),
    (lambda c: c.organizations.list_members("org_1"), "GET", "/v1/organizations/org_1/members", {}, None),
    (lambda c: c.organizations.remove_member("org_1", "mem_1"),
     "DELETE", "/v1/organizations/org_1/members/mem_1", {}, None),
    (lambda c: c.organizations.set_offer("org_1", discount_percent=20, applies_to_plan="12_month"),
     "PUT", "/v1/organizations/org_1/offer", {}, {"discount_percent": 20, "applies_to_plan": "12_month"}),
    (lambda c: c.organizations.delete_offer("org_1"), "DELETE", "/v1/organizations/org_1/offer", {}, None),
    (lambda c: c.organizations.create_subscription("org_1", type="team", seats=10, start_date=1700000000, end_date=1730000000),
     "POST", "/v1/organizations/org_1/subscriptions", {},
     {"type": "team", "seats": 10, "start_date": 1700000000, "end_date": 1730000000}),
    (lambda c: c.organizations.list_subscriptions("org_1"), "GET", "/v1/organizations/org_1/subscriptions", {}, None),
    (lambda c: c.integrations.status("intervals_icu", "ath_1"),
     "GET", "/v1/integrations/intervals_icu/status", {"athlete_id": "ath_1"}, None),
    (lambda c: c.testing.simulate_subscription("ath_1"),
     "POST", "/v1/test/athletes/ath_1/simulate-subscription", {}, {"active": True}),
    (lambda c: c.testing.simulate_subscription("ath_1", active=False),
     "POST", "/v1/test/athletes/ath_1/simulate-subscription", {}, {"active": False}),
    (lambda c: c.meta.discovery(), "GET", "/v1/", {}, None),
    (lambda c: c.meta.errors(), "GET", "/v1/errors", {}, None),
    (lambda c: c.meta.health(), "GET", "/v1/health", {}, None),
    (lambda c: c.knowledge.search("sodium", limit=5, category="hydration"),
     "POST", "/v1/knowledge/search", {}, {"query": "sodium", "limit": 5, "category": "hydration"}),
    (lambda c: c.knowledge.search("sodium"),
     "POST", "/v1/knowledge/search", {}, {"query": "sodium"}),
], ids=[
    "webhook-update-full", "webhook-update-partial", "webhook-delete", "webhook-test",
    "org-create-full", "org-create-minimal", "org-add-member-full", "org-add-member-default",
    "org-list-members", "org-remove-member", "org-set-offer", "org-delete-offer",
    "org-create-subscription", "org-list-subscriptions", "integration-status",
    "simulate-on", "simulate-off", "discovery", "error-catalog", "health",
    "knowledge-full", "knowledge-plain",
])
def test_live_only_writes_send_the_documented_request(call, method, path, params, body):
    def send(request):
        assert request.method == method
        assert request.url.path == path
        assert dict(request.url.params) == params
        assert (json.loads(request.content) if request.content else None) == body
        return httpx.Response(200, json={"ok": True})

    client = Saturday(api_key="sk_test_fixture", max_retries=0)
    client._client.close()
    client._client = httpx.Client(
        base_url=client._base_url, transport=httpx.MockTransport(send))
    with client:
        call(client)
