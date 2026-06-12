"""Tests for the API_OB additions: the onboarding question-schema resource and
the ``precision`` object on calculate responses.

The HTTP layer is stubbed with ``httpx.MockTransport`` so these run offline (no
network, no API key needed) — we swap the client's underlying httpx.Client for
one backed by the mock transport after construction.
"""
import httpx

from saturday import Saturday


def _client_with(handler):
    """Build a Saturday client whose HTTP calls are served by ``handler``."""
    client = Saturday(api_key="sk_test_x")
    client._client = httpx.Client(
        base_url=client._base_url,
        transport=httpx.MockTransport(handler),
    )
    return client


def test_onboarding_questions_path_and_shape():
    """questions() GETs /v1/onboarding/questions and returns the typed schema."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json={
                "schema_version": "2026-06-12.1",
                "questions": [
                    {
                        "field": "sweat_level",
                        "type": "single_select",
                        "required": True,
                        "title_en": "How much do you sweat?",
                        "options": [
                            {"value": 1, "label_en": "Light"},
                            {"value": 5, "label_en": "Average"},
                            {"value": 9, "label_en": "Heavy"},
                        ],
                    }
                ],
                "attribution": {"text": "Powered by Saturday", "logo_url": "", "link": "", "required": True},
            },
        )

    client = _client_with(handler)
    res = client.onboarding.questions()

    assert seen["method"] == "GET"
    assert seen["path"] == "/v1/onboarding/questions"
    assert res["schema_version"] == "2026-06-12.1"
    assert res["questions"][0]["field"] == "sweat_level"
    assert res["questions"][0]["options"][0]["value"] == 1
    # Attribution is required when rendering these questions in your UI.
    assert res["attribution"]["required"] is True


def test_precision_incomplete_profile_bands():
    """An incomplete profile yields bands + missing_fields + onboarding.url."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tier": "full",
                "carb_range_g_per_hr": "60-80",
                "safety": {"confidence_score": 0.62},
                "precision": {
                    "profile_complete": False,
                    "missing_fields": [
                        {
                            "field": "sweat_level",
                            "required": True,
                            "band_impact": {
                                "carb_g_per_hr": 0.4,
                                "sodium_mg_per_hr": 86.1,
                                "fluid_ml_per_hr": 79.0,
                            },
                        }
                    ],
                    "message": "Exact numbers unavailable: critical fields missing (sweat_level).",
                    "onboarding": {"url": "https://saturday.fit/onboard?ot=abc", "message": "Answer once…"},
                },
            },
        )

    client = _client_with(handler)
    rx = client.nutrition.calculate(activity_type="run", duration_min=90)
    p = rx["precision"]

    assert p["profile_complete"] is False
    assert p["missing_fields"][0]["field"] == "sweat_level"
    assert p["missing_fields"][0]["band_impact"]["sodium_mg_per_hr"] == 86.1
    assert "ot=" in p["onboarding"]["url"]


def test_precision_complete_profile_exact():
    """A complete profile carries profile_complete:true with exact numbers."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tier": "full",
                "carb_g_per_hr": 70,
                "sodium_mg_per_hr": 900,
                "fluid_ml_per_hr": 1000,
                "safety": {"confidence_score": 1.0},
                "precision": {"profile_complete": True},
            },
        )

    client = _client_with(handler)
    rx = client.nutrition.calculate(activity_type="run", duration_min=90)

    assert rx["precision"]["profile_complete"] is True
    assert "missing_fields" not in rx["precision"]
    assert rx["carb_g_per_hr"] == 70
