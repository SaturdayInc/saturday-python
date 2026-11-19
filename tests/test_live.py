"""Every partner method against a real Saturday API: a local build or the test environment.

Skipped unless SATURDAY_LIVE_BASE_URL and SATURDAY_LIVE_API_KEY (an sk_test_ key) are set.
tests/LIVE.md says how to run it and what it creates.
"""

import base64
import json
import os
import re
import time
import uuid

import pytest

from saturday import ConflictError, NotFoundError, PermissionDeniedError, Saturday, ValidationError

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

# Unix seconds stay below this until the year 5138; a time in milliseconds today is about 1.8e12.
MILLISECOND_SIZED = 1e11
TIME_KEY = re.compile(r"(_at|_date|^timestamp)$")


def assert_seconds(name, value, path=""):
    """Every time a partner key receives is Unix seconds: no *_at, *_date or timestamp number at any depth is millisecond-sized."""
    if isinstance(value, list):
        for i, item in enumerate(value):
            assert_seconds(name, item, f"{path}[{i}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (int, float)) and not isinstance(item, bool) and TIME_KEY.search(key):
                assert item < MILLISECOND_SIZED, f"{name}: {path}.{key} is {item}, a time in milliseconds"
            assert_seconds(name, item, f"{path}.{key}")


def delivered_event(event_data):
    """A webhook delivery's event body, decoded from its base64 event_data."""
    return json.loads(base64.b64decode(event_data or ""))


def assert_legs_add_up(prep):
    """Prep's top level on a brick is its legs added up: each product once with its servings summed, the totals and gap the legs' sums."""
    legs = prep["legs"]
    for key in ("carb_g", "sodium_mg", "fluid_ml"):
        assert prep["totals_from_products"][key] == sum(leg["totals_from_products"][key] for leg in legs)
        assert prep["remaining_gap"][key] == sum(leg["remaining_gap"][key] for leg in legs)
    ids = [p["product_id"] for p in prep["products"]]
    assert len(set(ids)) == len(ids)
    for product in prep["products"]:
        servings = sum(p["servings"] for leg in legs for p in leg["products"] if p["product_id"] == product["product_id"])
        assert product["servings"] == pytest.approx(servings)


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
        assert_seconds(name, body)
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

    discovery = capture("discovery", "DiscoveryResponse", client.meta.discovery())
    # A key comes with a paid Saturday plan: the API names the page and no price.
    assert discovery["get_a_key"]["page"] == "https://saturday.fit/api"
    assert discovery["get_a_key"]["athletes_per_key"] > 0
    assert not re.search(r"\$\d", json.dumps(discovery))
    catalog = capture("errors", "ErrorCatalogResponse", client.meta.errors())
    codes = [e["code"] for e in catalog["errors"]]
    for code in ("unsupported_field", "athlete_exists", "plan_inactive", "simulated_subscriber_daily_limit_reached", "provider_erasure_incomplete"):
        assert code in codes, code
    assert "payment_error" not in codes
    capture("health", "HealthResponse", client.meta.health())
    types = capture("activity_types", "ActivityTypesResponse", client.reference.activity_types())
    assert [t["id"] for t in types["linked_session_types"]] == ["brick", "triathlon"]
    brick_only = capture("activity_types_filtered", "ActivityTypesResponse", client.reference.activity_types(activity_type="brick"))
    assert brick_only["activity_types"] == [] and [t["id"] for t in brick_only["linked_session_types"]] == ["brick"]
    capture("settings_schema", "SettingsSchemaResponse", client.reference.settings_schema())
    capture("onboarding_questions", "OnboardingQuestionsResponse", client.onboarding.questions())

    # Athletes
    complete = capture("athlete", "Athlete", client.athletes.create(external_id=f"{run}-a", **COMPLETE))
    assert complete["profile_complete"] is True
    partial = client.athletes.create(external_id=f"{run}-b", weight_kg=70)
    capture("athlete_list", "AthleteListResponse", client.athletes.list(external_id=f"{run}-a"))
    # One athlete per external_id: a retried create, and a PATCH onto a taken id, change nothing and name the holder.
    with pytest.raises(ConflictError) as again:
        client.athletes.create(external_id=f"{run}-a", **COMPLETE)
    assert (again.value.code, again.value.athlete_id) == ("athlete_exists", complete["id"])
    with pytest.raises(ConflictError) as taken:
        client.athletes.update(partial["id"], external_id=f"{run}-a")
    assert taken.value.athlete_id == complete["id"]
    assert [a["id"] for a in client.athletes.list(external_id=f"{run}-a")["athletes"]] == [complete["id"]]
    assert client.athletes.update(complete["id"], name="Live Suite")["name"] == "Live Suite"
    settings = client.athletes.update_settings(complete["id"], **{**COMPLETE["settings"], "sweat_level": 6})
    assert settings["sweat_level"] == 6
    capture("fueling_profile", "FuelingProfile", client.athletes.get_fueling_profile(complete["id"]))
    batch = capture("athletes_batch", "BatchAthleteResponse", client.athletes.batch_create(
        [{"external_id": f"{run}-c"}, {"sex": "female"}, {"external_id": f"{run}-a"}]))
    assert batch["errors"][0]["index"] == 1
    assert (batch["errors"][1]["index"], batch["errors"][1]["code"], batch["errors"][1]["athlete_id"]) == (2, "athlete_exists", complete["id"])
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
    assert (misnamed.value.code, misnamed.value.param, misnamed.value.suggestion) == ("unsupported_field", "is_race_event", "is_race")
    with pytest.raises(ValidationError) as typo:
        client.nutrition.calculate(athlete_id=complete["id"], activity_type="bike", duration_min=60, **SESSION, meal_before_mins=120)
    assert (typo.value.code, typo.value.param, typo.value.suggestion) == ("unsupported_field", "meal_before_mins", "meal_before_min")
    no_race = client.nutrition.calculate(
        athlete_id=complete["id"], activity_type="run", duration_min=60, intensity_level=5, thermal_stress_level=5, meal_before_min=120)
    assert no_race["precision"]["profile_complete"] is False
    assert [f["field"] for f in no_race["precision"]["missing_fields"]] == ["is_race"]
    assert "is_race" in no_race["precision"]["message"] and "onboarding" not in no_race["precision"]
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
    # A field sent at its stored value keeps the prescription; a change to the session removes it until the next calculate.
    client.activities.update(complete["id"], activity["id"], intensity_level=6, external_id=f"{run}-w1b")
    assert client.activities.get_prescription(complete["id"], activity["id"])["prescription"]["total_carb_g"] == stored["prescription"]["total_carb_g"]
    assert "prescription" not in client.activities.update(complete["id"], activity["id"], intensity_level=8)
    with pytest.raises(NotFoundError) as outdated:
        client.activities.get_prescription(complete["id"], activity["id"])
    assert outdated.value.code == "prescription_not_found"
    fresh = client.activities.calculate_prescription(complete["id"], activity["id"])
    assert client.activities.get_prescription(complete["id"], activity["id"])["prescription"]["total_carb_g"] == fresh["prescription"]["total_carb_g"]
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
    assert banded["plan_basis"]["source"] == "profile_incomplete"
    assert banded["plan_basis"]["missing_profile_fields"] and "missing_session_inputs" not in banded["plan_basis"]
    assert banded["plan_basis"]["onboarding"]["url"].startswith("https://")
    session_gaps = capture("product_fit_session_inputs", "ProductFitResponse", client.nutrition.product_fit(
        athlete_id=complete["id"], product_query="maurten gel 100", activity_type="run", duration_min=90, intensity_level=5, thermal_stress_level=5))
    assert session_gaps["plan_basis"]["source"] == "session_incomplete"
    assert session_gaps["plan_basis"]["missing_session_inputs"] == ["meal_before_min", "is_race"]
    assert "onboarding" not in session_gaps["plan_basis"]
    with pytest.raises(ValidationError) as fit_typo:
        client.nutrition.product_fit(athlete_id=complete["id"], product_query="maurten gel 100", activity_type="run", duration_min=90, **SESSION, is_rac=True)
    assert (fit_typo.value.code, fit_typo.value.suggestion) == ("unsupported_field", "is_race")
    compare = capture("product_compare", "ProductCompareResponse", client.nutrition.compare_products(
        athlete_id=complete["id"], product_a={"product_query": "maurten gel 100"}, product_b={"product_query": "tailwind endurance fuel"},
        activity_type="bike", duration_min=180, **SESSION))
    assert compare["winner"]["overall"] in ("product_a", "product_b")

    # Test environment
    assert capture("simulate_subscription", "SimulateSubscriptionResponse", client.testing.simulate_subscription(partial["id"]))["simulated_active"]
    assert not client.testing.simulate_subscription(partial["id"], active=False)["simulated_active"]

    # Partner account
    account = capture("partner", "PartnerAccount", client.partner.get())
    assert account["rate_limits"]["trial_days"] > 0
    usage = capture("usage", "UsageResponse", client.partner.usage())
    assert usage["by_endpoint"] and all(endpoint.startswith("/v1/") for endpoint in usage["by_endpoint"])
    capture("usage_daily", "DailyUsageResponse", client.partner.usage_daily())
    capture("api_keys", "ApiKeyListResponse", client.partner.list_api_keys())
    created = capture("api_key_created", "CreatedApiKey", client.partner.create_api_key(f"{run}-key"))
    rotated = capture("api_key_rotated", "RotatedApiKey", client.partner.rotate_api_key(created["id"]))
    assert rotated["rotated_from"] == created["id"]
    client.partner.revoke_api_key(rotated["id"])

    # Webhooks
    hook = capture("webhook_created", "WebhookCreateResponse", client.webhooks.create("https://example.com/saturday-live-suite", ["prescription.calculated"]))
    hook_id = hook["webhook"]["id"]
    capture("webhook_list", "WebhookListResponse", client.webhooks.list())
    capture("webhook", "Webhook", client.webhooks.get(hook_id))
    # example.com answers 405, so each delivery is recorded as failed, its event body kept in event_data.
    tested = capture("webhook_test", "WebhookTestResponse", client.webhooks.test(hook_id))
    test_event = delivered_event(tested["delivery"].get("event_data"))
    assert test_event["type"] == "webhook.test"
    assert_seconds("webhook.test event", test_event)
    assert abs(test_event["created_at"] - time.time()) < 600
    client.nutrition.calculate(athlete_id=complete["id"], activity_type="run", duration_min=60, **SESSION)
    calculated_event = None
    for _ in range(20):
        delivery = next((d for d in client.webhooks.list_deliveries(hook_id)["deliveries"] if d["event_type"] == "prescription.calculated"), None)
        if delivery and delivery.get("event_data"):
            calculated_event = delivered_event(delivery["event_data"])
            break
        time.sleep(0.5)
    assert calculated_event and calculated_event["data"]["athlete_id"] == complete["id"]
    assert_seconds("prescription.calculated event", calculated_event)
    assert abs(calculated_event["created_at"] - time.time()) < 600
    assert client.webhooks.update(hook_id, active=False)["active"] is False
    capture("webhook_deliveries", "WebhookDeliveryList", client.webhooks.list_deliveries(hook_id))
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
    exported = capture("export", "AthleteDataExport", client.athletes.export(complete["id"]))
    assert abs(exported["exported_at"] - time.time()) < 600
    for provider in ("strava", "training_peaks"):
        with pytest.raises(ValidationError) as refused_provider:
            client.integrations.sync(provider, athlete_id=complete["id"], access_token="not-a-token")
        assert refused_provider.value.code == "invalid_provider"
    status = capture("integration_status", "IntegrationStatusResponse", client.integrations.status("intervals_icu", complete["id"]))
    assert status["status"]["connected"] is False
    client.athletes.erase(partial["id"])
    with pytest.raises(NotFoundError):
        client.athletes.get(partial["id"])
    client.athletes.erase(complete["id"])


def test_linked_sessions(live):
    """A brick or triathlon is one session with legs: calculate, batch, activities, PATCH, prep, import."""
    client, capture, run = live
    # A subscribed athlete, so these calculations do not run into the trial's daily allowance.
    athlete = client.athletes.create(external_id=f"{run}-linked", **COMPLETE)
    client.testing.simulate_subscription(athlete["id"])
    aid = athlete["id"]
    brick_legs = [
        {"activity_type": "bike", "duration_min": 90, "intensity_level": 6, "thermal_stress_level": 6},
        {"activity_type": "run", "duration_min": 30, "intensity_level": 7, "thermal_stress_level": 6},
    ]
    fed = {"meal_before_min": 120, "is_race": False}
    brick = capture("calculate_brick", "NutritionCalculateResponse", client.nutrition.calculate(
        athlete_id=aid, activity_type="brick", legs=brick_legs, **fed))
    exact(brick)
    assert [leg["duration_min"] for leg in brick["legs"]] == [90, 30]
    assert abs(sum(leg["total_carb_g"] for leg in brick["legs"]) - brick["total_carb_g"]) <= len(brick["legs"])
    # A brick is one call with legs: its legs sent as separate calls answer differently.
    separate = sum(client.nutrition.calculate(athlete_id=aid, **leg, **fed).get("total_carb_g", 0) for leg in brick_legs)
    assert brick["total_carb_g"] != separate

    tri_legs = [
        {"activity_type": "swim", "duration_min": 30, "intensity_level": 7, "thermal_stress_level": 3},
        {"activity_type": "bike", "duration_min": 80, "intensity_level": 7, "thermal_stress_level": 6},
        {"activity_type": "run", "duration_min": 40, "intensity_level": 7, "thermal_stress_level": 7},
    ]
    tri_session = {"meal_before_min": 240, "is_race": True}
    triathlon = capture("calculate_triathlon", "NutritionCalculateResponse", client.nutrition.calculate(
        athlete_id=aid, activity_type="triathlon", duration_min=150, legs=tri_legs, **tri_session))
    exact(triathlon)
    assert len(triathlon["legs"]) == 3

    with pytest.raises(ValidationError) as no_legs:
        client.nutrition.calculate(athlete_id=aid, activity_type="brick", **SESSION)
    assert no_legs.value.param == "legs"
    with pytest.raises(ValidationError) as top_level:
        client.nutrition.calculate(athlete_id=aid, activity_type="brick", legs=brick_legs, intensity_level=5)
    assert top_level.value.param == "intensity_level"
    with pytest.raises(ValidationError) as leg_typo:
        client.nutrition.calculate(athlete_id=aid, activity_type="brick", **fed, legs=[
            brick_legs[0], {"activity_type": "run", "duration_mins": 30, "intensity_level": 7, "thermal_stress_level": 6}])
    assert (leg_typo.value.code, leg_typo.value.param, leg_typo.value.suggestion) == ("unsupported_field", "legs[1].duration_mins", "duration_min")

    batch = client.nutrition.batch_calculate([
        {"athlete_id": aid, "activity_type": "brick", "legs": brick_legs, **fed},
        {"athlete_id": aid, "activity_type": "bike", "duration_min": 90, **SESSION},
    ])
    assert batch["succeeded"] == 2 and batch["results"][0]["legs"] == brick["legs"]

    activity_legs = [{"type": leg["activity_type"], **{k: v for k, v in leg.items() if k != "activity_type"}} for leg in brick_legs]
    stored = capture("activity_brick", "Activity", client.activities.create(
        aid, type="brick", legs=activity_legs, meal_before_min=120, is_race_event=False, external_id=f"{run}-brick"))
    assert (stored["type"], stored["duration_min"], stored["legs"]) == ("brick", 120, activity_legs)
    assert "intensity_level" not in stored
    # Prep plans a linked activity that has not been calculated yet.
    assert client.activities.prep(aid, stored["id"], products=[{"product_query": "maurten gel 100"}])["prescription"]["carb_g"] == brick["total_carb_g"]
    calculated = capture("activity_calculate_brick", "PrescriptionEnvelope", client.activities.calculate_prescription(aid, stored["id"]))
    assert calculated["prescription"]["legs"] == brick["legs"]
    read = capture("activity_prescription_brick", "StoredPrescriptionResponse", client.activities.get_prescription(aid, stored["id"]))
    assert read["prescription"]["legs"] == brick["legs"]
    prep = capture("prep_brick", "PrepResponse", client.activities.prep(aid, stored["id"], products=[
        {"product_query": "maurten gel 100", "servings": 3}, {"product_query": "tailwind endurance fuel"}]))
    assert prep["prescription"]["carb_g"] == brick["total_carb_g"] and "plan_basis" not in prep
    # One session-wide list is sized against each leg's share, its servings counting per leg; the top level is the legs added up.
    assert [leg["activity_type"] for leg in prep["legs"]] == ["bike", "run"]
    assert [leg["prescription"]["carb_g"] for leg in prep["legs"]] == [leg["total_carb_g"] for leg in brick["legs"]]
    gel_id = next(p["product_id"] for p in prep["products"] if "Gel" in p["product_name"])
    assert all(next(p["servings"] for p in leg["products"] if p["product_id"] == gel_id) == 3 for leg in prep["legs"])
    assert_legs_add_up(prep)
    per_leg = capture("prep_brick_per_leg", "PrepResponse", client.activities.prep(aid, stored["id"], legs=[
        {"products": [{"product_query": "tailwind endurance fuel"}]},
        {"products": [{"product_query": "maurten gel 100", "servings": 2}]},
    ]))
    assert gel_id not in [p["product_id"] for p in per_leg["legs"][0]["products"]]
    assert [(p["product_id"], p["servings"]) for p in per_leg["legs"][1]["products"]] == [(gel_id, 2)]
    assert len(per_leg["products"]) == 2
    assert_legs_add_up(per_leg)
    with pytest.raises(ValidationError) as wrong_count:
        client.activities.prep(aid, stored["id"], legs=[{"products": []}])
    assert (wrong_count.value.code, wrong_count.value.param) == ("invalid_value", "legs")
    with pytest.raises(ValidationError) as both:
        client.activities.prep(aid, stored["id"], products=[{"product_query": "maurten gel 100"}], legs=[{"products": []}, {"products": []}])
    assert (both.value.code, both.value.param) == ("invalid_value", "products")

    # Fit and compare size the whole session at the top level and each leg's share under legs.
    brick_fit = capture("product_fit_brick", "ProductFitResponse", client.nutrition.product_fit(
        athlete_id=aid, product_query="maurten gel 100", activity_type="brick", legs=brick_legs, **fed))
    assert brick_fit["tier"] == "full" and "plan_basis" not in brick_fit
    assert brick_fit["prescription"]["carb_g"] == brick["total_carb_g"]
    assert [(leg["activity_type"], leg["duration_min"]) for leg in brick_fit["legs"]] == [("bike", 90), ("run", 30)]
    assert [leg["prescription"]["carb_g"] for leg in brick_fit["legs"]] == [leg["total_carb_g"] for leg in brick["legs"]]
    assert all(leg["fit"]["product_id"] == gel_id for leg in brick_fit["legs"])
    tri_fit = client.nutrition.product_fit(
        athlete_id=aid, product_query="tailwind endurance fuel", activity_type="triathlon", legs=tri_legs, duration_min=150, **tri_session)
    assert tri_fit["prescription"]["carb_g"] == triathlon["total_carb_g"]
    assert [leg["prescription"]["carb_g"] for leg in tri_fit["legs"]] == [leg["total_carb_g"] for leg in triathlon["legs"]]
    tri_compare = capture("product_compare_triathlon", "ProductCompareResponse", client.nutrition.compare_products(
        athlete_id=aid, product_a={"product_query": "maurten gel 100"}, product_b={"product_query": "tailwind endurance fuel"},
        activity_type="triathlon", legs=tri_legs, **tri_session))
    assert len(tri_compare["legs"]) == 3 and all(leg["winner"]["overall"] in ("product_a", "product_b") for leg in tri_compare["legs"])
    brick_compare = client.nutrition.compare_products(
        athlete_id=aid, product_a={"product_query": "maurten gel 100"}, product_b={"product_query": "tailwind endurance fuel"},
        activity_type="brick", legs=brick_legs, **fed)
    assert [leg["product_a"]["product_id"] for leg in brick_compare["legs"]] == [gel_id, gel_id]
    # Each refusal names its field.
    gel = {"athlete_id": aid, "product_query": "maurten gel 100"}
    for request, param in (
        ({"activity_type": "brick", "duration_min": 120, **SESSION}, "legs"),
        ({"activity_type": "run", "duration_min": 120, "legs": brick_legs, **SESSION}, "legs"),
        ({"activity_type": "brick", "legs": brick_legs, "duration_min": 100, **fed}, "duration_min"),
    ):
        with pytest.raises(ValidationError) as refused:
            client.nutrition.product_fit(**gel, **request)
        assert refused.value.param == param, request
    with pytest.raises(ValidationError) as no_sport:
        client.nutrition.compare_products(athlete_id=aid, product_a={"product_query": "maurten gel 100"},
                                          product_b={"product_query": "tailwind endurance fuel"}, duration_min=60)
    assert (no_sport.value.code, no_sport.value.param) == ("missing_field", "activity_type")

    # A brick's minutes, effort and heat live on its legs.
    with pytest.raises(ValidationError) as minutes:
        client.activities.update(aid, stored["id"], duration_min=150)
    assert minutes.value.param == "duration_min"
    longer = client.activities.update(aid, stored["id"], legs=[activity_legs[0], {**activity_legs[1], "duration_min": 45}])
    assert longer["duration_min"] == 135
    with pytest.raises(NotFoundError):
        client.activities.get_prescription(aid, stored["id"])
    assert client.activities.calculate_prescription(aid, stored["id"])["prescription"]["total_carb_g"] > brick["total_carb_g"]
    single = client.activities.update(aid, stored["id"], type="run", duration_min=60, intensity_level=5, thermal_stress_level=5)
    assert single["type"] == "run" and "legs" not in single
    with pytest.raises(ValidationError) as legs_on_single:
        client.activities.prep(aid, stored["id"], legs=[{"products": []}, {"products": []}])
    assert (legs_on_single.value.code, legs_on_single.value.param) == ("invalid_value", "legs")
    with pytest.raises(ValidationError) as needs_legs:
        client.activities.update(aid, stored["id"], type="triathlon")
    assert needs_legs.value.param == "legs"
    tri = client.activities.update(aid, stored["id"], type="triathlon", legs=[
        {"type": "swim", "duration_min": 20, "intensity_level": 6, "thermal_stress_level": 3},
        {"type": "bike", "duration_min": 40, "intensity_level": 6, "thermal_stress_level": 5},
        {"type": "run", "duration_min": 20, "intensity_level": 6, "thermal_stress_level": 5},
    ])
    assert (tri["type"], tri["duration_min"]) == ("triathlon", 80) and "intensity_level" not in tri

    imported = capture("activity_import_brick", "ActivityImportResponse", client.activities.import_activities(aid, [
        {"type": "brick", "legs": activity_legs, "meal_before_min": 120, "is_race_event": False, "external_id": f"{run}-i-brick"},
    ], calculate=True))
    assert imported["imported"][0]["legs"] == activity_legs
    assert imported["prescriptions"][0]["result"]["prescription"]["legs"] == brick["legs"]
    client.athletes.erase(aid)
