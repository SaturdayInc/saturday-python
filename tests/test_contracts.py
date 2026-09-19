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
        assert dict(request.url.params) == {key: str(value) for key, value in (options or {"limit": 50 if athletes else 20}).items()}
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
