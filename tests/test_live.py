"""Every partner method against a real Saturday API: a local build or the test environment.

Skipped unless SATURDAY_LIVE_BASE_URL and SATURDAY_LIVE_API_KEY (an sk_test_ key) are set.
tests/LIVE.md says how to run it and what it creates.
"""

import json
import os
import re
import uuid

import pytest

from saturday import NotFoundError, PermissionDeniedError, Saturday, ValidationError

BASE = os.environ.get("SATURDAY_LIVE_BASE_URL")
KEY = os.environ.get("SATURDAY_LIVE_API_KEY")
CAPTURE = os.environ.get("SATURDAY_LIVE_CAPTURE")

pytestmark = pytest.mark.skipif(not (BASE and KEY), reason="set SATURDAY_LIVE_BASE_URL and SATURDAY_LIVE_API_KEY to run")

COMPLETE = {
    "sex": "female",
    "year_of_birth": 1990,
    "weight_kg": 62,
    "settings": {
        "sweat_level": 5, "saltiness": 5, "satiety_level": 5, "fitness_level": 5,
        "carb_experience": "range_40_60", "usual_carb_consumption": "range_60_80",
        "performance": True, "concerns_answered": True,
    },
}
SESSION = {"intensity_level": 5, "thermal_stress_level": 5, "meal_before_min": 120, "is_race": False}


def scrub(value, key=""):
    """Keys, secrets, signed links and account details never go into the capture file."""
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, dict):
        return {k: scrub(v, k) for k, v in value.items()}
    if not isinstance(value, str):
        return value
    if key == "secret":
        return "whsec_example"
    if key == "key":
        return "sk_test_example"
    if key == "contact_email":
        return "partner@example.com"
    if key == "partner_id" or (key == "id" and value.startswith("partner_")):
        return "partner_example"
    if key == "ip_address":
        return "192.0.2.1"
    value = re.sub(r'([?&]ot=)[^&\s"]+', r"\1example", value)
    value = re.sub(r"sk_(test|live)_[A-Za-z0-9]+", r"sk_\1_example", value)
    return re.sub(r"([?&]ref=)partner_[A-Za-z0-9_]+", r"\1partner_example", value)


@pytest.fixture(scope="module")
def live():
    if not KEY.startswith("sk_test_"):
        pytest.fail("SATURDAY_LIVE_API_KEY must be a test key (sk_test_)")
    captured = {}

    def capture(name, type_name, body):
        captured[name] = {"type": type_name, "body": scrub(body)}
        return body

    with Saturday(api_key=KEY, base_url=BASE, max_retries=0, timeout=60) as client:
        yield client, capture, f"sdk-python-{uuid.uuid4().hex[:8]}"
    if CAPTURE:
        with open(CAPTURE, "w") as f:
            json.dump(captured, f, indent=2)
            f.write("\n")


def exact(plan):
    assert plan["precision"]["profile_complete"] is True
    for field in ("carb_g_per_hr", "sodium_mg_per_hr", "fluid_ml_per_hr"):
        assert float(plan.get(field, 0)).is_integer()
    assert plan["safety"]["not_instructions"] is True
    assert plan["attribution"]["required"] is True


def test_main_flows(live):
    client, capture, run = live

    capture("discovery", "Dict", client.meta.discovery())
    catalog = capture("errors", "ErrorCatalogResponse", client.meta.errors())
    assert "unsupported_field" in [e["code"] for e in catalog["errors"]]
    capture("health", "HealthResponse", client.meta.health())
    capture("activity_types", "ActivityTypesResponse", client.reference.activity_types())
    capture("settings_schema", "SettingsSchemaResponse", client.reference.settings_schema())
    capture("onboarding_questions", "OnboardingQuestionsResponse", client.onboarding.questions())

    # Athletes
    complete = capture("athlete", "Athlete", client.athletes.create(external_id=f"{run}-a", **COMPLETE))
    assert complete["profile_complete"] is True
    partial = client.athletes.create(external_id=f"{run}-b", weight_kg=70)
    capture("athlete_list", "AthleteListResponse", client.athletes.list(external_id=f"{run}-a"))
    assert client.athletes.update(complete["id"], name="Live Suite")["name"] == "Live Suite"
    settings = client.athletes.update_settings(complete["id"], **{**COMPLETE["settings"], "sweat_level": 6})
    assert settings["sweat_level"] == 6
    capture("fueling_profile", "FuelingProfile", client.athletes.get_fueling_profile(complete["id"]))
    batch = capture("athletes_batch", "BatchAthleteResponse", client.athletes.batch_create([{"external_id": f"{run}-c"}, {"sex": "female"}]))
    assert batch["errors"][0]["index"] == 1
    client.athletes.erase(batch["created"][0]["id"])

    # Calculation
    fed = capture("calculate_exact", "NutritionCalculateResponse", client.nutrition.calculate(
        athlete_id=complete["id"], activity_type="run", duration_min=60, **SESSION))
    exact(fed)
    fasted = client.nutrition.calculate(athlete_id=complete["id"], activity_type="run", duration_min=60, **{**SESSION, "meal_before_min": 240})
    exact(fasted)
    assert abs(fasted["carb_g_per_hr"] - fasted["total_carb_g"] * 60 / 80) <= 1
    exact(client.nutrition.calculate(athlete_id=complete["id"], activity_type="bike", duration_min=120, **{**SESSION, "intensity_level": 4, "is_race": True}))
    ranges = capture("calculate_ranges", "NutritionCalculateResponse", client.nutrition.calculate(
        athlete_id=partial["id"], activity_type="bike", duration_min=120, **SESSION))
    assert ranges["precision"]["profile_complete"] is False
    assert ranges["precision"]["missing_fields"][0]["band_impact"]
    capture("calculate_teaser", "NutritionCalculateResponse", client.nutrition.calculate(activity_type="bike", duration_min=120))
    with pytest.raises(ValidationError) as misnamed:
        client.nutrition.calculate(athlete_id=complete["id"], activity_type="bike", duration_min=60, is_race_event=True)
    assert (misnamed.value.code, misnamed.value.param) == ("unsupported_field", "is_race_event")
    calc_batch = capture("calculate_batch", "BatchCalculateResponse", client.nutrition.batch_calculate([
        {"athlete_id": complete["id"], "activity_type": "bike", "duration_min": 90, **SESSION},
        {"activity_type": "nope", "duration_min": 5},
    ]))
    assert calc_batch["errors"][0]["index"] == 1

    # Activities, prescriptions and prep
    with pytest.raises(ValidationError):
        client.activities.create(complete["id"], activity_type="bike", duration_min=60)
    activity = capture("activity", "Activity", client.activities.create(
        complete["id"], type="bike", duration_min=150, intensity_level=6, thermal_stress_level=6,
        is_race_event=False, meal_before_min=120, external_id=f"{run}-w1"))
    capture("activity_list", "ActivityListResponse", client.activities.list(complete["id"], limit=10))
    assert client.activities.update(complete["id"], activity["id"], duration_min=160)["duration_min"] == 160
    with pytest.raises(NotFoundError):
        client.activities.get_prescription(complete["id"], activity["id"])
    calculated = capture("activity_calculate", "PrescriptionEnvelope", client.activities.calculate_prescription(complete["id"], activity["id"]))
    stored = capture("activity_prescription", "StoredPrescriptionResponse", client.activities.get_prescription(complete["id"], activity["id"]))
    assert stored["prescription"]["total_carb_g"] == calculated["prescription"]["total_carb_g"]
    prep = capture("prep", "PrepResponse", client.activities.prep(complete["id"], activity["id"], products=[
        {"product_query": "maurten gel 100", "servings": 2}, {"product_query": "tailwind endurance fuel"},
    ]))
    assert prep["prescription"]["carb_g"] == stored["prescription"]["total_carb_g"]
    capture("feedback", "ActivityFeedback", client.activities.submit_feedback(complete["id"], activity["id"], rating=4, notes="live suite"))
    imported = capture("activity_import", "ActivityImportResponse", client.activities.import_activities(complete["id"], [
        {"type": "run", "duration_min": 45, "intensity_level": 5, "meal_before_min": 120, "is_race_event": False, "external_id": f"{run}-i1"},
    ], calculate=True))
    assert imported["prescriptions"][0]["result"]["tier"] == "full"
    client.activities.delete(complete["id"], activity["id"])

    # Product fit and compare
    fit = capture("product_fit", "ProductFitResponse", client.nutrition.product_fit(
        athlete_id=complete["id"], product_query="maurten gel 100", activity_type="run", duration_min=90, **SESSION))
    assert fit["tier"] == "full" and "plan_basis" not in fit
    banded = capture("product_fit_plan_basis", "ProductFitResponse", client.nutrition.product_fit(
        athlete_id=partial["id"], product_query="tailwind endurance fuel", activity_type="bike", duration_min=120, **SESSION))
    assert banded["plan_basis"]["source"] == "range_midpoint"
    compare = capture("product_compare", "ProductCompareResponse", client.nutrition.compare_products(
        athlete_id=complete["id"], product_a={"product_query": "maurten gel 100"}, product_b={"product_query": "tailwind endurance fuel"},
        activity_type="bike", duration_min=180, **SESSION))
    assert compare["winner"]["overall"] in ("product_a", "product_b")

    # Test environment
    assert capture("simulate_subscription", "SimulateSubscriptionResponse", client.testing.simulate_subscription(partial["id"]))["simulated_active"]
    assert not client.testing.simulate_subscription(partial["id"], active=False)["simulated_active"]

    # Partner account
    capture("partner", "PartnerAccount", client.partner.get())
    capture("usage", "UsageResponse", client.partner.usage())
    capture("usage_daily", "DailyUsageResponse", client.partner.usage_daily())
    capture("api_keys", "ApiKeyListResponse", client.partner.list_api_keys())
    created = capture("api_key_created", "CreatedApiKey", client.partner.create_api_key(f"{run}-key"))
    rotated = capture("api_key_rotated", "RotatedApiKey", client.partner.rotate_api_key(created["id"]))
    assert rotated["rotated_from"] == created["id"]
    client.partner.revoke_api_key(rotated["id"])

    # Webhooks
    hook = capture("webhook_created", "CreateWebhookResponse", client.webhooks.create("https://example.com/saturday-live-suite", ["prescription.calculated"]))
    hook_id = hook["webhook"]["id"]
    capture("webhook_list", "WebhookListResponse", client.webhooks.list())
    capture("webhook", "Webhook", client.webhooks.get(hook_id))
    assert client.webhooks.update(hook_id, active=False)["active"] is False
    capture("webhook_deliveries", "WebhookDeliveriesResponse", client.webhooks.deliveries(hook_id))
    client.webhooks.delete(hook_id)

    # Organizations
    org = capture("organization", "Organization", client.organizations.create(f"{run} team", sport="triathlon"))
    capture("organization_list", "OrganizationListResponse", client.organizations.list())
    member = capture("organization_member", "OrganizationMember", client.organizations.add_member(org["id"], f"{run}@example.com", athlete_id=complete["id"]))
    capture("organization_members", "OrganizationMembersResponse", client.organizations.list_members(org["id"]))
    client.organizations.remove_member(org["id"], member["id"])
    capture("organization_offer", "OrganizationOffer", client.organizations.set_offer(org["id"], discount_percent=10))
    client.organizations.delete_offer(org["id"])
    capture("organization_subscriptions", "OrganizationSubscriptionListResponse", client.organizations.list_subscriptions(org["id"]))
    with pytest.raises(PermissionDeniedError) as restricted:
        client.organizations.create_subscription(org["id"], type="team", seats=5, start_date=1, end_date=2)
    assert restricted.value.code == "organization_subscription_restricted"

    # Privacy and integrations
    consent = capture("consent", "ConsentRecord", client.athletes.record_consent(complete["id"], consent_type="analytics", granted=True))
    capture("consent_list", "ConsentListResponse", client.athletes.list_consent(complete["id"]))
    client.athletes.revoke_consent(complete["id"], consent["id"])
    capture("export", "AthleteDataExport", client.athletes.export(complete["id"]))
    capture("integration_status", "IntegrationStatusResponse", client.integrations.status("strava", complete["id"]))
    client.athletes.erase(partial["id"])
    with pytest.raises(NotFoundError):
        client.athletes.get(partial["id"])
    client.athletes.erase(complete["id"])
