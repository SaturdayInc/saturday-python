"""Every exported model in saturday.types has a realistic instance checked
against it.

Top-level response models are already checked in test_contracts (backend
contract samples), test_live_types (recorded live responses) and
test_live_shapes. This file covers the rest: nested models are extracted from
those same recorded or contract payloads at the path where the API puts them,
and the handful with no instance anywhere in the fixtures are built from the
field definitions in saturday/types.py and marked CONSTRUCTED. Literal
aliases check that each documented value matches and a bogus one does not.
A model added to saturday.__all__ without an instance here or in those files
fails test_every_exported_model_is_covered.
"""

import json
from pathlib import Path
from typing import Literal, get_args, get_origin

import pytest

import saturday
import saturday.types as T
from test_contracts import MODELS, matches
from test_live_shapes import SHAPES

FIXTURES = Path(__file__).with_name("fixtures")
CONTRACTS = json.loads(FIXTURES.joinpath("contracts.json").read_text())
LIVE = {name: entry["body"] for name, entry in json.loads(FIXTURES.joinpath("live.json").read_text()).items()}
LIVE_TYPES = {entry["type"] for entry in json.loads(FIXTURES.joinpath("live.json").read_text()).values()}

PROFILE = CONTRACTS["fueling_profile_on"]["profile"]
TRIAL = {k: CONTRACTS["nutrition_trial"][k] for k in ("tier_source", "trial_ends_at", "trial_calls_remaining_today")}
BATCH_SUMMARY = {k: CONTRACTS["batch_partial"][k] for k in ("total", "succeeded", "failed", "request_id", "errors")}

# model name -> a realistic instance, extracted from the fixtures above.
INSTANCES = {
    "ActivityLeg": LIVE["activity_brick"]["legs"][0],
    "ActivityTypeInfo": LIVE["activity_types"]["activity_types"][0],
    "ApiKeyInfo": LIVE["api_keys"]["api_keys"][0],
    "Attribution": CONTRACTS["activity_full"]["attribution"],
    "BandImpact": CONTRACTS["activity_full_banded"]["precision"]["missing_fields"][0]["band_impact"],
    "BatchError": CONTRACTS["batch_partial"]["errors"][0],
    "BatchSummary": BATCH_SUMMARY,
    "CoachBillingArrangement": CONTRACTS["billing_connect_arrangements"]["arrangements"][0],
    "CoachChargeBreakdown": CONTRACTS["billing_connect_earnings"]["breakdowns"][0],
    "CoachConnectAccount": CONTRACTS["billing_connect_summary"]["connect_account"],
    "CoachConnectCharge": CONTRACTS["billing_connect_transactions"]["charges"][0],
    "CoachEarningsSummary": CONTRACTS["billing_connect_earnings"]["summary"],
    "CoachLedgerEntry": CONTRACTS["billing_ledger_page"]["entries"][0],
    "CoachSubscriptionStatus": CONTRACTS["billing_tier_status"]["status"],
    "CoachTierSubscription": CONTRACTS["billing_tier_status"]["subscriptions"][0],
    "ComparisonWinner": LIVE["product_compare"]["winner"],
    "CoveragePct": LIVE["prep"]["coverage_pct"],
    "DailyUsage": LIVE["usage"]["daily"][0],
    "DiscoveryKeyInfo": LIVE["discovery"]["get_a_key"],
    "ErrorCatalogEntry": LIVE["errors"]["errors"][0],
    "FuelingConcerns": PROFILE["concerns"]["value"],
    "FuelingProfileAnswers": PROFILE,
    "FuelingProfileCarbExperience": PROFILE["carb_experience"],
    "FuelingProfileConcerns": PROFILE["concerns"],
    "FuelingProfileInt": PROFILE["age"],
    "FuelingProfileSex": PROFILE["sex"],
    "FuelingProfileUpdatedData": CONTRACTS["webhook_fueling_profile_updated"]["data"],
    "FuelingProfileUsualCarb": PROFILE["usual_carb_consumption"],
    "FuelingProfileWeight": PROFILE["athlete_weight_kg"],
    "GapAmounts": LIVE["product_fit"]["fit"]["remaining_gap"],
    "ImportPrescriptionItem": CONTRACTS["import_calculated"]["prescriptions"][0],
    "IntegrationStatusDetail": LIVE["integration_status"]["status"],
    "LegPrescription": LIVE["calculate_brick"]["legs"][0],
    "LinkedSessionTypeInfo": LIVE["activity_types"]["linked_session_types"][0],
    "MissingField": CONTRACTS["activity_full_banded"]["precision"]["missing_fields"][0],
    "NutrientAmounts": LIVE["prep"]["prescription"],
    "OnboardingInvite": CONTRACTS["activity_full_banded"]["precision"]["onboarding"],
    "OnboardingOption": LIVE["onboarding_questions"]["questions"][0]["options"][0],
    "OnboardingQuestion": LIVE["onboarding_questions"]["questions"][0],
    "PaginationMeta": CONTRACTS["list_athletes_next"]["pagination"],
    "PartnerRateLimits": LIVE["partner"]["rate_limits"],
    "PerServing": LIVE["product_fit"]["fit"]["per_serving"],
    "PlanBasis": LIVE["product_fit_plan_basis"]["plan_basis"],
    "Precision": CONTRACTS["activity_full_banded"]["precision"],
    "PrepLeg": LIVE["prep_brick"]["legs"][0],
    "PrepProduct": LIVE["prep"]["products"][0],
    "ProductCompareLeg": LIVE["product_compare_triathlon"]["legs"][0],
    "ProductFitDetail": LIVE["product_fit"]["fit"],
    "ProductFitLeg": LIVE["product_fit_brick"]["legs"][0],
    "SafetyMetadata": CONTRACTS["activity_full"]["safety"],
    "SettingsFieldSchema": LIVE["settings_schema"]["settings"][0],
    "SubscriptionCTA": CONTRACTS["nutrition_teaser"]["subscription_cta"],
    "TrialMetadata": TRIAL,
    "UsagePeriod": LIVE["usage"]["period"],
    "WebhookDelivery": LIVE["webhook_test"]["delivery"],
    "WebhookEvent": CONTRACTS["webhook_profile_sharing_changed"],
    "WebhookWithSecret": LIVE["webhook_created"]["webhook"],
    # Request-side models: the examples the README and live suite send.
    "CalculateLeg": {"activity_type": "bike", "duration_min": 90, "intensity_level": 6, "thermal_stress_level": 6},
    "ImportActivityRequest": {"type": "run", "duration_min": 45, "intensity_level": 5,
                              "meal_before_min": 120, "is_race_event": False, "external_id": "partner-act"},
    # CONSTRUCTED from saturday/types.py: no fixture in this repository
    # contains an instance (no recorded prep answer carries gear, no product
    # teaser with categories was recorded, and no sync, seat subscription or
    # license response was recorded).
    "GearItem": {"id": "gear_1", "name": "Soft flask", "type": "flask", "capacity_ml": 500,
                 "is_default": True, "created_at": 1700000000, "updated_at": 1700000000},
    "ProductCategory": {"id": "gels", "name": "Gels", "description": "Energy gels"},
    "License": {"email": "sam@example.com", "added_at": 1700000000, "active": True, "athlete_id": "ath_1", "name": "Sam"},
    "LicenseListResponse": {"licenses": [{"email": "sam@example.com", "added_at": 1700000000, "active": True}],
                            "total": 1, "request_id": "req_lic"},
    "OrganizationSubscription": {"id": "sub_1", "org_id": "org_1", "partner_id": "partner_example", "type": "team",
                                 "seats": 10, "used_seats": 3, "status": "active", "start_date": 1700000000,
                                 "end_date": 1730000000, "created_at": 1700000000},
    "IntegrationSyncResult": {"provider": "intervals_icu", "status": "completed", "activities_found": 2,
                              "activities_synced": 2, "activities_skipped": 0, "prescription_tier": "full"},
    "IntegrationSyncResponse": {"result": {"provider": "intervals_icu", "status": "completed", "activities_found": 2,
                                           "activities_synced": 2, "activities_skipped": 0}, "request_id": "req_sync"},
    "IntegrationDisconnectResponse": {"message": "Successfully disconnected intervals_icu",
                                      "provider": "intervals_icu", "request_id": "req_disc"},
}

NON_MODELS = {
    "Saturday", "SaturdayError", "AuthenticationError", "PermissionDeniedError", "RateLimitError",
    "ValidationError", "NotFoundError", "ConflictError", "DAILY_LIMIT_CODES", "MAX_RETRY_WAIT_SECONDS",
}
EXPORTED_MODELS = [name for name in saturday.__all__ if name not in NON_MODELS]
LITERALS = [name for name in EXPORTED_MODELS if get_origin(getattr(T, name)) is Literal]
TYPED_DICTS = [name for name in EXPORTED_MODELS if name not in LITERALS]
ALREADY_CHECKED = set(MODELS.values()) | LIVE_TYPES | set(SHAPES)


def test_every_exported_model_is_covered():
    covered = ALREADY_CHECKED | set(INSTANCES) | set(LITERALS)
    assert set(EXPORTED_MODELS) <= covered, f"no instance checked for: {sorted(set(EXPORTED_MODELS) - covered)}"
    assert set(INSTANCES) <= set(EXPORTED_MODELS), f"instances for unexported names: {sorted(set(INSTANCES) - set(EXPORTED_MODELS))}"


@pytest.mark.parametrize("name", sorted(INSTANCES))
def test_model_instance_matches_its_typed_dict(name):
    model = getattr(T, name)
    instance = INSTANCES[name]
    assert isinstance(instance, dict) and instance, name
    assert matches(instance, model), f"{name} instance does not match its TypedDict"
    assert model(**instance) == instance
    assert type(model(**instance)) is dict


@pytest.mark.parametrize("name", sorted(LITERALS))
def test_literal_alias_takes_its_documented_values_only(name):
    alias = getattr(T, name)
    for value in get_args(alias):
        assert matches(value, alias), f"{name} should take {value!r}"
    assert not matches("__bogus__", alias), f"{name} should refuse a bogus value"


def test_exported_models_are_typed_dicts_or_literals():
    for name in TYPED_DICTS:
        assert hasattr(getattr(T, name), "__required_keys__"), f"{name} is neither a TypedDict nor a Literal alias"
