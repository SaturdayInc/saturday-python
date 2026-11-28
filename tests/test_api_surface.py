"""Every public resource method against a mocked HTTP layer (no network).

Each case checks the request the method builds (method, path, query, body and
headers) and that a realistic response is returned untouched, as a plain dict
matching the TypedDict the method is annotated with. Response payloads come
from the recorded API responses in tests/fixtures/live.json and the backend
contract samples in tests/fixtures/contracts.json where one exists for the
method. Payloads marked CONSTRUCTED have no recorded or contract sample in
this repository: they are built from the field definitions in
saturday/types.py (or, for the untyped Dict returns, from the words of the
method's docstring), so for those the SDK-observable contract checked here is
the request shape plus dict passthrough.
"""

import json
from pathlib import Path

import httpx
import pytest

import saturday.types as T
from saturday import Saturday, ValidationError
from saturday.client import SDK_VERSION
from test_contracts import matches

FIXTURES = Path(__file__).with_name("fixtures")
LIVE = {name: entry["body"] for name, entry in json.loads(FIXTURES.joinpath("live.json").read_text()).items()}
CONTRACTS = json.loads(FIXTURES.joinpath("contracts.json").read_text())

# CONSTRUCTED from OrganizationSubscription in saturday/types.py (the live
# suite only records the 403 for create_subscription without an allowance).
ORG_SUBSCRIPTION = {
    "id": "sub_1", "org_id": "org_1", "partner_id": "partner_example", "type": "team",
    "seats": 10, "used_seats": 3, "status": "active",
    "start_date": 1700000000, "end_date": 1730000000, "created_at": 1700000000,
}
# CONSTRUCTED from LicenseListResponse / License in saturday/types.py.
LICENSES = {
    "licenses": [{"email": "sam@example.com", "added_at": 1700000000, "active": True, "athlete_id": "ath_1", "name": "Sam"}],
    "total": 1, "request_id": "req_lic",
}
# CONSTRUCTED from IntegrationSyncResponse in saturday/types.py.
SYNCED = {
    "result": {"provider": "intervals_icu", "status": "completed", "activities_found": 2,
               "activities_synced": 2, "activities_skipped": 0, "prescription_tier": "full"},
    "request_id": "req_sync",
}
# CONSTRUCTED from IntegrationDisconnectResponse (its docstring gives the message).
DISCONNECTED = {"message": "Successfully disconnected intervals_icu", "provider": "intervals_icu", "request_id": "req_disc"}
# CONSTRUCTED: nutrition.extract, infer.* and knowledge.* return Dict and no
# response shape for them exists in this repository's docs, types or fixtures.
EXTRACTED = {"product_name": "Example Gel", "per_serving": {"carb_g": 25.0, "sodium_mg": 50.0, "fluid_ml": 0.0}}
INFERRED_TYPE = {"activity_type": "bike"}
INFERRED_BRICK = {"legs": [{"activity_type": "bike", "duration_min": 90}, {"activity_type": "run", "duration_min": 30}]}
KNOWLEDGE_SEARCH = {"results": [{"id": "art_1", "title": "Sodium basics"}]}
KNOWLEDGE_TOPICS = {"topics": [{"id": "hydration", "name": "Hydration"}]}
KNOWLEDGE_ARTICLE = {"id": "art_1", "title": "Sodium basics", "body": "Drink to thirst."}
# CONSTRUCTED coach payloads: the coach reads return Dict; shapes follow the
# keys and words of their docstrings in saturday/client.py.
COACH_ROSTER = {"athletes": [{"athlete_uid": "ath_1", "needs_attention": True}]}
COACH_DIGEST = {"athletes": [{"athlete_uid": "ath_1", "needs_attention": True}]}
COACH_ROLLUP = {"athlete_uid": "ath_1", "window": 7, "concerns": []}
COACH_REPORT = {"narrative": "Fueling is on plan.", "athlete_uid": "ath_1"}
COACH_SESSION = {"athlete_uid": "ath_1", "activity_id": "act_1"}
COACH_RULES = {
    "notification_rules": {"under_fuel": {"enabled": True, "channels": ["email"], "cadence": "daily", "urgent_threshold": 0.8}},
    "hourly_cap": {"enabled": True, "per_hour": 1},
    "preset": "balanced",
    "channel_config": {"email": "coach@example.com"},
}
COACH_REPORT_SETTINGS = {"ai_report_window_days": 7, "ai_report_focus": "worst", "concern_carb_cutoff": 0.8}
COACH_WEBHOOKS = {"webhooks": [{"id": "cwh_1", "url": "https://example.com/hook", "events": ["concern.detected"], "active": True}]}
COACH_WEBHOOK_CREATED = {"id": "cwh_1", "url": "https://example.com/hook", "events": [], "secret": "cwhsec_example"}

SESSION = {"intensity_level": 5, "thermal_stress_level": 5, "meal_before_min": 120, "is_race": False}
BRICK_LEGS = [
    {"activity_type": "bike", "duration_min": 90, "intensity_level": 6, "thermal_stress_level": 6},
    {"activity_type": "run", "duration_min": 30, "intensity_level": 7, "thermal_stress_level": 6},
]

# (id, call, method, path, query, json body, status, response, model name or None)
CASES = [
    # nutrition
    ("calculate", lambda c: c.nutrition.calculate(athlete_id="ath_1", activity_type="run", duration_min=60, **SESSION),
     "POST", "/v1/nutrition/calculate", {}, {"athlete_id": "ath_1", "activity_type": "run", "duration_min": 60, **SESSION},
     200, LIVE["calculate_exact"], "NutritionCalculateResponse"),
    ("calculate-brick", lambda c: c.nutrition.calculate(athlete_id="ath_1", activity_type="brick", legs=BRICK_LEGS, meal_before_min=120, is_race=False),
     "POST", "/v1/nutrition/calculate", {}, {"athlete_id": "ath_1", "activity_type": "brick", "legs": BRICK_LEGS, "meal_before_min": 120, "is_race": False},
     200, LIVE["calculate_brick"], "NutritionCalculateResponse"),
    ("batch-calculate", lambda c: c.nutrition.batch_calculate([{"activity_type": "bike", "duration_min": 90}]),
     "POST", "/v1/nutrition/calculate/batch", {}, {"scenarios": [{"activity_type": "bike", "duration_min": 90}]},
     200, LIVE["calculate_batch"], "BatchCalculateResponse"),
    ("batch-estimate", lambda c: c.nutrition.batch_calculate([{"activity_type": "bike", "duration_min": 90}], estimate_only=True),
     "POST", "/v1/nutrition/calculate/batch", {}, {"scenarios": [{"activity_type": "bike", "duration_min": 90}], "estimate_only": True},
     200, CONTRACTS["batch_estimate"], "BatchCalculateResponse"),
    ("product-fit", lambda c: c.nutrition.product_fit(athlete_id="ath_1", product_query="maurten gel 100", activity_type="run", duration_min=90, **SESSION),
     "POST", "/v1/nutrition/products/fit", {}, {"athlete_id": "ath_1", "product_query": "maurten gel 100", "activity_type": "run", "duration_min": 90, **SESSION},
     200, LIVE["product_fit"], "ProductFitResponse"),
    ("product-fit-brick", lambda c: c.nutrition.product_fit(athlete_id="ath_1", product_query="maurten gel 100", activity_type="brick", legs=BRICK_LEGS, meal_before_min=120, is_race=False),
     "POST", "/v1/nutrition/products/fit", {}, {"athlete_id": "ath_1", "product_query": "maurten gel 100", "activity_type": "brick", "legs": BRICK_LEGS, "meal_before_min": 120, "is_race": False},
     200, LIVE["product_fit_brick"], "ProductFitResponse"),
    ("compare-products", lambda c: c.nutrition.compare_products(athlete_id="ath_1", product_a={"product_query": "maurten gel 100"}, product_b={"product_query": "tailwind endurance fuel"}, activity_type="bike", duration_min=180, **SESSION),
     "POST", "/v1/nutrition/products/compare", {}, {"athlete_id": "ath_1", "product_a": {"product_query": "maurten gel 100"}, "product_b": {"product_query": "tailwind endurance fuel"}, "activity_type": "bike", "duration_min": 180, **SESSION},
     200, LIVE["product_compare"], "ProductCompareResponse"),
    ("extract", lambda c: c.nutrition.extract(image_base64="AA=="),
     "POST", "/v1/nutrition/extract", {}, {"image_base64": "AA=="}, 200, EXTRACTED, None),
    # athletes
    ("athletes-create", lambda c: c.athletes.create(external_id="user-42", sex="female", year_of_birth=1990, weight_kg=62),
     "POST", "/v1/athletes", {}, {"external_id": "user-42", "sex": "female", "year_of_birth": 1990, "weight_kg": 62},
     201, LIVE["athlete"], "Athlete"),
    ("athletes-get", lambda c: c.athletes.get("ath_1"),
     "GET", "/v1/athletes/ath_1", {}, None, 200, CONTRACTS["athlete_sharing"], "Athlete"),
    ("athletes-list", lambda c: c.athletes.list(),
     "GET", "/v1/athletes", {"limit": "50"}, None, 200, LIVE["athlete_list"], "AthleteListResponse"),
    ("athletes-update", lambda c: c.athletes.update("ath_1", name="Jo"),
     "PATCH", "/v1/athletes/ath_1", {}, {"name": "Jo"}, 200, LIVE["athlete"], "Athlete"),
    ("athletes-delete", lambda c: c.athletes.delete("ath_1"),
     "DELETE", "/v1/athletes/ath_1", {}, None, 204, None, None),
    ("athletes-get-settings", lambda c: c.athletes.get_settings("ath_1"),
     "GET", "/v1/athletes/ath_1/settings", {}, None, 200, CONTRACTS["settings_full"], "AthleteSettings"),
    ("athletes-update-settings", lambda c: c.athletes.update_settings("ath_1", sweat_level=7),
     "PATCH", "/v1/athletes/ath_1/settings", {}, {"sweat_level": 7}, 200, CONTRACTS["settings_updated"], "AthleteSettings"),
    ("athletes-get-fueling-profile", lambda c: c.athletes.get_fueling_profile("ath_1"),
     "GET", "/v1/athletes/ath_1/fueling-profile", {}, None, 200, CONTRACTS["fueling_profile_on"], "FuelingProfile"),
    ("athletes-create-onboarding-link", lambda c: c.athletes.create_onboarding_link("ath_1", locale="de"),
     "POST", "/v1/athletes/ath_1/onboarding-link", {}, {"locale": "de"}, 200, CONTRACTS["onboarding_link"], "OnboardingLink"),
    ("athletes-batch-create", lambda c: c.athletes.batch_create([{"external_id": "u-1"}]),
     "POST", "/v1/athletes/batch", {}, {"athletes": [{"external_id": "u-1"}]}, 200, LIVE["athletes_batch"], "BatchAthleteResponse"),
    ("athletes-export", lambda c: c.athletes.export("ath_1"),
     "POST", "/v1/athletes/ath_1/export", {}, None, 200, LIVE["export"], "AthleteDataExport"),
    ("athletes-erase", lambda c: c.athletes.erase("ath_1"),
     "POST", "/v1/athletes/ath_1/delete", {}, None, 204, None, None),
    ("athletes-list-consent", lambda c: c.athletes.list_consent("ath_1"),
     "GET", "/v1/athletes/ath_1/consent", {}, None, 200, LIVE["consent_list"], "ConsentListResponse"),
    ("athletes-record-consent", lambda c: c.athletes.record_consent("ath_1", consent_type="analytics", granted=True),
     "POST", "/v1/athletes/ath_1/consent", {}, {"consent_type": "analytics", "granted": True}, 200, LIVE["consent"], "ConsentRecord"),
    ("athletes-revoke-consent", lambda c: c.athletes.revoke_consent("ath_1", "con_1"),
     "DELETE", "/v1/athletes/ath_1/consent/con_1", {}, None, 204, None, None),
    # activities
    ("activities-create", lambda c: c.activities.create("ath_1", type="bike", duration_min=150, intensity_level=6, thermal_stress_level=6, meal_before_min=120, is_race_event=False),
     "POST", "/v1/athletes/ath_1/activities", {}, {"type": "bike", "duration_min": 150, "intensity_level": 6, "thermal_stress_level": 6, "meal_before_min": 120, "is_race_event": False},
     201, LIVE["activity"], "Activity"),
    ("activities-create-brick", lambda c: c.activities.create("ath_1", type="brick", legs=[{"type": "bike", "duration_min": 90, "intensity_level": 6, "thermal_stress_level": 6}, {"type": "run", "duration_min": 30, "intensity_level": 7, "thermal_stress_level": 6}], meal_before_min=120, is_race_event=False),
     "POST", "/v1/athletes/ath_1/activities", {}, {"type": "brick", "legs": [{"type": "bike", "duration_min": 90, "intensity_level": 6, "thermal_stress_level": 6}, {"type": "run", "duration_min": 30, "intensity_level": 7, "thermal_stress_level": 6}], "meal_before_min": 120, "is_race_event": False},
     201, LIVE["activity_brick"], "Activity"),
    ("activities-get", lambda c: c.activities.get("ath_1", "act_1"),
     "GET", "/v1/athletes/ath_1/activities/act_1", {}, None, 200, LIVE["activity"], "Activity"),
    ("activities-list", lambda c: c.activities.list("ath_1"),
     "GET", "/v1/athletes/ath_1/activities", {}, None, 200, LIVE["activity_list"], "ActivityListResponse"),
    ("activities-update", lambda c: c.activities.update("ath_1", "act_1", duration_min=160),
     "PATCH", "/v1/athletes/ath_1/activities/act_1", {}, {"duration_min": 160}, 200, LIVE["activity"], "Activity"),
    ("activities-delete", lambda c: c.activities.delete("ath_1", "act_1"),
     "DELETE", "/v1/athletes/ath_1/activities/act_1", {}, None, 204, None, None),
    ("activities-calculate-prescription", lambda c: c.activities.calculate_prescription("ath_1", "act_1"),
     "POST", "/v1/athletes/ath_1/activities/act_1/calculate", {}, None, 200, LIVE["activity_calculate"], "PrescriptionEnvelope"),
    ("activities-get-prescription", lambda c: c.activities.get_prescription("ath_1", "act_1"),
     "GET", "/v1/athletes/ath_1/activities/act_1/prescription", {}, None, 200, LIVE["activity_prescription"], "StoredPrescriptionResponse"),
    ("activities-prep-products", lambda c: c.activities.prep("ath_1", "act_1", products=[{"product_query": "maurten gel 100", "servings": 2}]),
     "POST", "/v1/athletes/ath_1/activities/act_1/prep", {}, {"products": [{"product_query": "maurten gel 100", "servings": 2}]},
     200, LIVE["prep"], "PrepResponse"),
    ("activities-prep-legs", lambda c: c.activities.prep("ath_1", "act_1", legs=[{"products": []}, {"products": [{"product_query": "maurten gel 100"}]}]),
     "POST", "/v1/athletes/ath_1/activities/act_1/prep", {}, {"legs": [{"products": []}, {"products": [{"product_query": "maurten gel 100"}]}]},
     200, LIVE["prep_brick_per_leg"], "PrepResponse"),
    ("activities-prep-neither", lambda c: c.activities.prep("ath_1", "act_1"),
     "POST", "/v1/athletes/ath_1/activities/act_1/prep", {}, {"products": []}, 200, LIVE["prep"], "PrepResponse"),
    ("activities-import-activities", lambda c: c.activities.import_activities("ath_1", [{"type": "run", "duration_min": 45}], calculate=True),
     "POST", "/v1/athletes/ath_1/activities/import", {}, {"activities": [{"type": "run", "duration_min": 45}], "calculate": True},
     200, LIVE["activity_import"], "ActivityImportResponse"),
    ("activities-submit-feedback-notes", lambda c: c.activities.submit_feedback("ath_1", "act_1", rating=4, notes="felt strong"),
     "POST", "/v1/athletes/ath_1/activities/act_1/feedback", {}, {"rating": 4, "notes": "felt strong"},
     200, LIVE["feedback"], "ActivityFeedback"),
    # onboarding, reference, infer
    ("onboarding-questions", lambda c: c.onboarding.questions(),
     "GET", "/v1/onboarding/questions", {}, None, 200, LIVE["onboarding_questions"], "OnboardingQuestionsResponse"),
    ("reference-activity-types", lambda c: c.reference.activity_types(),
     "GET", "/v1/activity-types", {}, None, 200, LIVE["activity_types"], "ActivityTypesResponse"),
    ("reference-activity-types-filtered", lambda c: c.reference.activity_types(activity_type="brick"),
     "GET", "/v1/activity-types", {"activity_type": "brick"}, None, 200, LIVE["activity_types_filtered"], "ActivityTypesResponse"),
    ("reference-settings-schema", lambda c: c.reference.settings_schema(),
     "GET", "/v1/settings/schema", {}, None, 200, LIVE["settings_schema"], "SettingsSchemaResponse"),
    ("infer-activity-type", lambda c: c.infer.activity_type(activity_name="Morning Ride", device="Garmin Edge 1040"),
     "POST", "/v1/infer/activity-type", {}, {"activity_name": "Morning Ride", "device": "Garmin Edge 1040"}, 200, INFERRED_TYPE, None),
    ("infer-brick-types", lambda c: c.infer.brick_types(activity_name="Brick session"),
     "POST", "/v1/infer/brick-types", {}, {"activity_name": "Brick session"}, 200, INFERRED_BRICK, None),
    # partner
    ("partner-get", lambda c: c.partner.get(),
     "GET", "/v1/partner", {}, None, 200, LIVE["partner"], "PartnerAccount"),
    ("partner-usage", lambda c: c.partner.usage(from_date="2026-11-01", to_date="2026-11-07"),
     "GET", "/v1/partner/usage", {"from": "2026-11-01", "to": "2026-11-07"}, None, 200, LIVE["usage"], "UsageResponse"),
    ("partner-usage-daily", lambda c: c.partner.usage_daily(from_date="2026-11-01", to_date="2026-11-07"),
     "GET", "/v1/partner/usage/daily", {"from": "2026-11-01", "to": "2026-11-07"}, None, 200, LIVE["usage_daily"], "DailyUsageResponse"),
    ("partner-list-api-keys", lambda c: c.partner.list_api_keys(),
     "GET", "/v1/partner/api-keys", {}, None, 200, LIVE["api_keys"], "ApiKeyListResponse"),
    ("partner-create-api-key", lambda c: c.partner.create_api_key("ci"),
     "POST", "/v1/partner/api-keys", {}, {"name": "ci"}, 201, LIVE["api_key_created"], "CreatedApiKey"),
    ("partner-revoke-api-key", lambda c: c.partner.revoke_api_key("key_1"),
     "DELETE", "/v1/partner/api-keys/key_1", {}, None, 204, None, None),
    ("partner-rotate-api-key", lambda c: c.partner.rotate_api_key("key_1"),
     "POST", "/v1/partner/api-keys/key_1/rotate", {}, None, 200, LIVE["api_key_rotated"], "RotatedApiKey"),
    # webhooks
    ("webhooks-create", lambda c: c.webhooks.create("https://example.com/saturday", ["athlete.created"]),
     "POST", "/v1/webhooks", {}, {"url": "https://example.com/saturday", "events": ["athlete.created"]},
     201, LIVE["webhook_created"], "WebhookCreateResponse"),
    ("webhooks-list", lambda c: c.webhooks.list(),
     "GET", "/v1/webhooks", {}, None, 200, LIVE["webhook_list"], "WebhookListResponse"),
    ("webhooks-get", lambda c: c.webhooks.get("wh_1"),
     "GET", "/v1/webhooks/wh_1", {}, None, 200, LIVE["webhook"], "Webhook"),
    ("webhooks-update", lambda c: c.webhooks.update("wh_1", active=False),
     "PATCH", "/v1/webhooks/wh_1", {}, {"active": False}, 200, LIVE["webhook"], "Webhook"),
    ("webhooks-delete", lambda c: c.webhooks.delete("wh_1"),
     "DELETE", "/v1/webhooks/wh_1", {}, None, 204, None, None),
    ("webhooks-test", lambda c: c.webhooks.test("wh_1"),
     "POST", "/v1/webhooks/wh_1/test", {}, None, 200, LIVE["webhook_test"], "WebhookTestResponse"),
    ("webhooks-list-deliveries", lambda c: c.webhooks.list_deliveries("wh_1"),
     "GET", "/v1/webhooks/wh_1/deliveries", {}, None, 200, LIVE["webhook_deliveries"], "WebhookDeliveryList"),
    # organizations
    ("organizations-create", lambda c: c.organizations.create("Riders", sport="triathlon"),
     "POST", "/v1/organizations", {}, {"display_name": "Riders", "sport": "triathlon"}, 201, LIVE["organization"], "Organization"),
    ("organizations-list", lambda c: c.organizations.list(),
     "GET", "/v1/organizations", {}, None, 200, LIVE["organization_list"], "OrganizationListResponse"),
    ("organizations-get", lambda c: c.organizations.get("org_1"),
     "GET", "/v1/organizations/org_1", {}, None, 200, LIVE["organization"], "Organization"),
    ("organizations-update", lambda c: c.organizations.update("org_1", description="Weekend riders"),
     "PATCH", "/v1/organizations/org_1", {}, {"description": "Weekend riders"}, 200, LIVE["organization"], "Organization"),
    ("organizations-add-member", lambda c: c.organizations.add_member("org_1", "sam@example.com", athlete_id="ath_1"),
     "POST", "/v1/organizations/org_1/members", {}, {"email": "sam@example.com", "role": "member", "athlete_id": "ath_1"},
     201, LIVE["organization_member"], "OrganizationMember"),
    ("organizations-list-members", lambda c: c.organizations.list_members("org_1"),
     "GET", "/v1/organizations/org_1/members", {}, None, 200, LIVE["organization_members"], "OrganizationMembersResponse"),
    ("organizations-remove-member", lambda c: c.organizations.remove_member("org_1", "mem_1"),
     "DELETE", "/v1/organizations/org_1/members/mem_1", {}, None, 204, None, None),
    ("organizations-set-offer", lambda c: c.organizations.set_offer("org_1", discount_percent=10),
     "PUT", "/v1/organizations/org_1/offer", {}, {"discount_percent": 10}, 200, LIVE["organization_offer"], "OrganizationOffer"),
    ("organizations-get-offer", lambda c: c.organizations.get_offer("org_1"),
     "GET", "/v1/organizations/org_1/offer", {}, None, 200, LIVE["organization_offer"], "OrganizationOffer"),
    ("organizations-delete-offer", lambda c: c.organizations.delete_offer("org_1"),
     "DELETE", "/v1/organizations/org_1/offer", {}, None, 204, None, None),
    ("organizations-create-subscription", lambda c: c.organizations.create_subscription("org_1", type="team", seats=10, start_date=1700000000, end_date=1730000000),
     "POST", "/v1/organizations/org_1/subscriptions", {}, {"type": "team", "seats": 10, "start_date": 1700000000, "end_date": 1730000000},
     201, ORG_SUBSCRIPTION, "OrganizationSubscription"),
    ("organizations-list-subscriptions", lambda c: c.organizations.list_subscriptions("org_1"),
     "GET", "/v1/organizations/org_1/subscriptions", {}, None, 200, LIVE["organization_subscriptions"], "OrganizationSubscriptionListResponse"),
    ("organizations-update-subscription", lambda c: c.organizations.update_subscription("org_1", "sub_1", seats=12),
     "PATCH", "/v1/organizations/org_1/subscriptions/sub_1", {}, {"seats": 12}, 200, ORG_SUBSCRIPTION, "OrganizationSubscription"),
    ("organizations-add-licenses", lambda c: c.organizations.add_licenses("org_1", "sub_1", [{"athlete_id": "ath_1", "email": "sam@example.com"}]),
     "POST", "/v1/organizations/org_1/subscriptions/sub_1/licenses", {}, {"licenses": [{"athlete_id": "ath_1", "email": "sam@example.com"}]},
     200, LICENSES, "LicenseListResponse"),
    ("organizations-list-licenses", lambda c: c.organizations.list_licenses("org_1", "sub_1"),
     "GET", "/v1/organizations/org_1/subscriptions/sub_1/licenses", {}, None, 200, LICENSES, "LicenseListResponse"),
    ("organizations-remove-license", lambda c: c.organizations.remove_license("org_1", "sub_1", "ath_1"),
     "DELETE", "/v1/organizations/org_1/subscriptions/sub_1/licenses/ath_1", {}, None, 204, None, None),
    # integrations, testing, meta, knowledge
    ("integrations-sync", lambda c: c.integrations.sync("intervals_icu", athlete_id="ath_1", access_token="tok"),
     "POST", "/v1/integrations/intervals_icu/sync", {}, {"athlete_id": "ath_1", "access_token": "tok", "sync_types": ["activities"]},
     200, SYNCED, "IntegrationSyncResponse"),
    ("integrations-status", lambda c: c.integrations.status("intervals_icu", "ath_1"),
     "GET", "/v1/integrations/intervals_icu/status", {"athlete_id": "ath_1"}, None, 200, LIVE["integration_status"], "IntegrationStatusResponse"),
    ("integrations-disconnect", lambda c: c.integrations.disconnect("intervals_icu", "ath_1"),
     "POST", "/v1/integrations/intervals_icu/disconnect", {}, {"athlete_id": "ath_1"}, 200, DISCONNECTED, "IntegrationDisconnectResponse"),
    ("testing-simulate-subscription", lambda c: c.testing.simulate_subscription("ath_1"),
     "POST", "/v1/test/athletes/ath_1/simulate-subscription", {}, {"active": True}, 200, LIVE["simulate_subscription"], "SimulateSubscriptionResponse"),
    ("meta-discovery", lambda c: c.meta.discovery(),
     "GET", "/v1/", {}, None, 200, LIVE["discovery"], "DiscoveryResponse"),
    ("meta-errors", lambda c: c.meta.errors(),
     "GET", "/v1/errors", {}, None, 200, LIVE["errors"], "ErrorCatalogResponse"),
    ("meta-health", lambda c: c.meta.health(),
     "GET", "/v1/health", {}, None, 200, LIVE["health"], "HealthResponse"),
    ("knowledge-search", lambda c: c.knowledge.search("sodium", limit=5, category="hydration"),
     "POST", "/v1/knowledge/search", {}, {"query": "sodium", "limit": 5, "category": "hydration"}, 200, KNOWLEDGE_SEARCH, None),
    ("knowledge-list-topics", lambda c: c.knowledge.list_topics(),
     "GET", "/v1/knowledge/topics", {}, None, 200, KNOWLEDGE_TOPICS, None),
    ("knowledge-get-article", lambda c: c.knowledge.get_article("art_1"),
     "GET", "/v1/knowledge/articles/art_1", {}, None, 200, KNOWLEDGE_ARTICLE, None),
    # coach reads and config
    ("coach-roster", lambda c: c.coach.roster(window=7),
     "GET", "/v1/coach/roster", {"window": "7"}, None, 200, COACH_ROSTER, None),
    ("coach-roster-digest", lambda c: c.coach.roster_digest(window=7),
     "GET", "/v1/coach/roster/digest", {"window": "7"}, None, 200, COACH_DIGEST, None),
    ("coach-fueling-rollup", lambda c: c.coach.fueling_rollup("ath_1", window=7, focus="worst"),
     "GET", "/v1/coach/athletes/ath_1/fueling-rollup", {"window": "7", "focus": "worst"}, None, 200, COACH_ROLLUP, None),
    ("coach-report", lambda c: c.coach.report("ath_1", window=14, focus="rolling", refresh=True),
     "GET", "/v1/coach/athletes/ath_1/report", {"window": "14", "focus": "rolling", "refresh": "true"}, None, 200, COACH_REPORT, None),
    ("coach-session-detail", lambda c: c.coach.session_detail("ath_1", "act_1"),
     "GET", "/v1/coach/athletes/ath_1/sessions/act_1", {}, None, 200, COACH_SESSION, None),
    ("coach-get-notification-rules", lambda c: c.coach.get_notification_rules(scope="overall"),
     "GET", "/v1/coach/config/notification-rules", {"scope": "overall"}, None, 200, COACH_RULES, None),
    ("coach-set-notification-rules", lambda c: c.coach.set_notification_rules("overall", COACH_RULES),
     "PUT", "/v1/coach/config/notification-rules", {}, {"scope": "overall", "scope_id": None, "rules": COACH_RULES}, 200, COACH_RULES, None),
    ("coach-apply-preset", lambda c: c.coach.apply_preset(scope="overall", preset="balanced"),
     "POST", "/v1/coach/config/preset", {}, {"scope": "overall", "scope_id": None, "preset": "balanced"}, 200, COACH_RULES, None),
    ("coach-get-report-settings", lambda c: c.coach.get_report_settings(scope="overall"),
     "GET", "/v1/coach/config/report-settings", {"scope": "overall"}, None, 200, COACH_REPORT_SETTINGS, None),
    ("coach-set-report-settings", lambda c: c.coach.set_report_settings("overall", COACH_REPORT_SETTINGS),
     "PUT", "/v1/coach/config/report-settings", {}, {"scope": "overall", "scope_id": None, "settings": COACH_REPORT_SETTINGS}, 200, COACH_REPORT_SETTINGS, None),
    ("coach-list-webhooks", lambda c: c.coach.list_webhooks(),
     "GET", "/v1/coach/webhooks", {}, None, 200, COACH_WEBHOOKS, None),
    ("coach-register-webhook", lambda c: c.coach.register_webhook("https://example.com/hook"),
     "POST", "/v1/coach/webhooks", {}, {"url": "https://example.com/hook", "events": []}, 201, COACH_WEBHOOK_CREATED, None),
    ("coach-delete-webhook", lambda c: c.coach.delete_webhook("cwh_1"),
     "DELETE", "/v1/coach/webhooks/cwh_1", {}, None, 200, {"deleted": True}, None),
    ("coach-disable-webhook", lambda c: c.coach.disable_webhook("cwh_1"),
     "POST", "/v1/coach/webhooks/cwh_1/disable", {}, None, 200, {"id": "cwh_1", "active": False}, None),
    ("coach-enable-webhook", lambda c: c.coach.enable_webhook("cwh_1"),
     "POST", "/v1/coach/webhooks/cwh_1/enable", {}, None, 200, {"id": "cwh_1", "active": True}, None),
    # coach billing (contract samples)
    ("coach-seat-state", lambda c: c.coach.seat_state(),
     "GET", "/v1/coach/billing/seat-state", {}, None, 200, CONTRACTS["billing_seat_state"], "CoachSeatState"),
    ("coach-seat-state-pro", lambda c: c.coach.seat_state(org_id="org_1"),
     "GET", "/v1/coach/billing/seat-state", {"org_id": "org_1"}, None, 200, CONTRACTS["billing_seat_state_pro"], "CoachSeatState"),
    ("coach-ledger", lambda c: c.coach.ledger(view="inflows", limit=50, cursor="1749480000000"),
     "GET", "/v1/coach/billing/ledger", {"view": "inflows", "limit": "50", "cursor": "1749480000000"}, None, 200, CONTRACTS["billing_ledger_page"], "CoachLedgerPage"),
    ("coach-ledger-empty", lambda c: c.coach.ledger(),
     "GET", "/v1/coach/billing/ledger", {}, None, 200, CONTRACTS["billing_ledger_empty"], "CoachLedgerPage"),
    ("coach-tier-status", lambda c: c.coach.tier_status(),
     "GET", "/v1/coach/billing/tier-status", {}, None, 200, CONTRACTS["billing_tier_status"], "CoachTierStatus"),
    ("coach-tier-status-empty", lambda c: c.coach.tier_status(),
     "GET", "/v1/coach/billing/tier-status", {}, None, 200, CONTRACTS["billing_tier_status_empty"], "CoachTierStatus"),
    ("coach-connect-summary", lambda c: c.coach.connect_summary(),
     "GET", "/v1/coach/billing/connect/summary", {}, None, 200, CONTRACTS["billing_connect_summary"], "CoachConnectSummary"),
    ("coach-connect-summary-none", lambda c: c.coach.connect_summary(),
     "GET", "/v1/coach/billing/connect/summary", {}, None, 200, CONTRACTS["billing_connect_summary_none"], "CoachConnectSummary"),
    ("coach-connect-earnings", lambda c: c.coach.connect_earnings(),
     "GET", "/v1/coach/billing/connect/earnings", {}, None, 200, CONTRACTS["billing_connect_earnings"], "CoachConnectEarnings"),
    ("coach-connect-earnings-empty", lambda c: c.coach.connect_earnings(),
     "GET", "/v1/coach/billing/connect/earnings", {}, None, 200, CONTRACTS["billing_connect_earnings_empty"], "CoachConnectEarnings"),
    ("coach-connect-transactions", lambda c: c.coach.connect_transactions(limit=20, cursor="1749480000000"),
     "GET", "/v1/coach/billing/connect/transactions", {"limit": "20", "cursor": "1749480000000"}, None, 200, CONTRACTS["billing_connect_transactions"], "CoachConnectChargesPage"),
    ("coach-connect-transactions-end", lambda c: c.coach.connect_transactions(),
     "GET", "/v1/coach/billing/connect/transactions", {}, None, 200, CONTRACTS["billing_connect_transactions_end"], "CoachConnectChargesPage"),
    ("coach-connect-arrangements", lambda c: c.coach.connect_arrangements(),
     "GET", "/v1/coach/billing/connect/arrangements", {}, None, 200, CONTRACTS["billing_connect_arrangements"], "CoachConnectArrangements"),
]


def _client(handler):
    client = Saturday(api_key="sk_test_fake", max_retries=0)
    headers = client._client.headers
    client._client.close()
    client._client = httpx.Client(base_url=client._base_url, headers=headers, transport=httpx.MockTransport(handler))
    return client


@pytest.mark.parametrize("case_id, call, method, path, query, body, status, response, model",
                         CASES, ids=[case[0] for case in CASES])
def test_method_builds_request_and_parses_response(case_id, call, method, path, query, body, status, response, model):
    seen = []

    def handler(request):
        seen.append(request)
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json=response)

    with _client(handler) as client:
        result = call(client)

    assert len(seen) == 1
    (request,) = seen
    assert request.method == method
    assert request.url.path == path
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    assert request.headers["Authorization"] == "Bearer " + "sk_test_fake"
    assert request.headers["User-Agent"] == f"saturday-python/{SDK_VERSION}"
    assert request.headers["X-SDK-Version"] == SDK_VERSION
    assert request.headers["Content-Type"] == "application/json"

    if status == 204:
        assert result is None
        return
    assert type(result) is dict
    assert result == response
    if model is not None:
        assert matches(result, getattr(T, model)), f"{case_id} response does not match {model}"


def test_case_table_covers_every_resource_method():
    """The case ids name every public resource method: a method added to the
    client without a case here fails this test."""
    import inspect

    client = Saturday(api_key="sk_test_fake")
    try:
        resources = {
            "nutrition": client.nutrition, "athletes": client.athletes, "activities": client.activities,
            "onboarding": client.onboarding, "reference": client.reference, "infer": client.infer,
            "partner": client.partner, "webhooks": client.webhooks, "organizations": client.organizations,
            "integrations": client.integrations, "testing": client.testing, "meta": client.meta,
            "knowledge": client.knowledge, "coach": client.coach,
        }
        # coach.report_pdf returns bytes: its case is the separate test below.
        covered = {case[0] for case in CASES} | {"coach-report-pdf"}
        missing = []
        for resource_name, resource in resources.items():
            for name, member in inspect.getmembers(resource, predicate=inspect.ismethod):
                if name.startswith("_"):
                    continue
                # A method is covered when some case id ends with its name in
                # kebab form (variants share the method's id as a prefix).
                kebab = name.replace("_", "-")
                if not any(cid == f"{resource_name}-{kebab}" or cid.startswith(f"{resource_name}-{kebab}-")
                           or cid == kebab or cid.startswith(f"{kebab}-") for cid in covered):
                    missing.append(f"{resource_name}.{name}")
        assert missing == [], f"no surface case for: {missing}"
    finally:
        client.close()


def test_prep_with_both_products_and_legs_sends_both_and_surfaces_the_refusal():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(400, json={"error": {"type": "invalid_request", "code": "invalid_value",
                                                    "param": "products", "message": "Send only one of products and legs."}})

    with _client(handler) as client:
        with pytest.raises(ValidationError) as raised:
            client.activities.prep("ath_1", "act_1", products=[{"product_id": "p1"}], legs=[{"products": []}])
    assert (raised.value.code, raised.value.param) == ("invalid_value", "products")
    assert json.loads(seen[0].content) == {"legs": [{"products": []}], "products": [{"product_id": "p1"}]}


def test_report_pdf_sends_format_and_returns_bytes():
    pdf = b"%PDF-1.7\nreport"
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=pdf, headers={"Content-Type": "application/pdf"})

    with _client(handler) as client:
        assert client.coach.report_pdf("ath_1", window=7, focus="worst") == pdf
    assert seen[0].method == "GET"
    assert seen[0].url.path == "/v1/coach/athletes/ath_1/report"
    assert dict(seen[0].url.params) == {"window": "7", "focus": "worst", "format": "pdf"}
    assert seen[0].headers["Authorization"] == "Bearer " + "sk_test_fake"

