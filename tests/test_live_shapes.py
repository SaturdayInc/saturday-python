"""Shapes the deployed API returned on 2026-11-15, written out by hand with example values."""
import json

import httpx
import pytest

import saturday.types as T
from saturday import Saturday
from tests.test_contracts import matches

WEBHOOK = {
    "id": "wh_1", "partner_id": "partner_example", "url": "https://example.com/saturday",
    "events": ["athlete.created", "webhook.test"], "active": True,
    "created_at": 1794765411324, "updated_at": 1794765411324, "fail_count": 0,
}
DELIVERY = {
    "id": "dlv_1", "webhook_id": "wh_1", "partner_id": "partner_example", "event_id": "evt_1",
    "event_type": "webhook.test", "event_data": "eyJ0eXBlIjoid2ViaG9vay50ZXN0In0=",
    "url": "https://example.com/saturday", "status_code": 405, "attempts": 1, "status": "failed",
    "created_at": 1794765464844,
}
SHAPES = {
    "WebhookCreateResponse": {
        "message": "Store the secret securely: it will not be shown again.",
        "request_id": "req_0a1b2c3d4e5f",
        "webhook": {**WEBHOOK, "secret": "0" * 64},
    },
    "Webhook": WEBHOOK,
    "WebhookListResponse": {"webhooks": [WEBHOOK], "total": 1, "request_id": "req_0a1b2c3d4e60"},
    "WebhookTestResponse": {"delivery": DELIVERY, "request_id": "req_0a1b2c3d4e61"},
    "WebhookDeliveryList": {"deliveries": [DELIVERY], "total": 1, "request_id": "req_0a1b2c3d4e62"},
    "StoredPrescriptionResponse": {
        "prescription": {"calculated_at": 1794764945, "profile_complete": False, "carb_range_g_per_hr": "30-40",
                         "sodium_range_mg_per_hr": "300-400", "fluid_range_ml_per_hr": "400-500"},
        "safety": {"max_safe_fluid_ml_per_hr": 1500, "max_safe_sodium_mg_per_hr": 3000, "confidence_score": 0,
                   "requires_human_review": False, "warnings": [], "not_instructions": True},
    },
}


@pytest.mark.parametrize("model", sorted(SHAPES))
def test_live_shape_matches_typed_model(model):
    assert matches(SHAPES[model], getattr(T, model))


def mock(client, handler):
    client._client.close()
    client._client = httpx.Client(base_url=client._base_url, transport=httpx.MockTransport(handler))


def test_webhook_create_returns_the_response_with_the_secret_under_webhook():
    client = Saturday(api_key="sk_test_fixture", max_retries=0)
    mock(client, lambda request: httpx.Response(201, json=SHAPES["WebhookCreateResponse"]))
    created = client.webhooks.create("https://example.com/saturday", ["athlete.created"])
    assert created == SHAPES["WebhookCreateResponse"]
    assert len(created["webhook"]["secret"]) == 64


def test_list_deliveries_reads_the_deliveries_route():
    seen = []

    def send(request):
        seen.append(request)
        return httpx.Response(200, json=SHAPES["WebhookDeliveryList"])

    client = Saturday(api_key="sk_test_fixture", max_retries=0)
    mock(client, send)
    assert client.webhooks.list_deliveries("wh_1") == SHAPES["WebhookDeliveryList"]
    assert seen[0].method == "GET" and seen[0].url.path == "/v1/webhooks/wh_1/deliveries"


def test_athletes_list_sends_external_id():
    seen = []

    def send(request):
        seen.append(request)
        return httpx.Response(200, json={"athletes": [], "pagination": {"total": 0, "has_more": False}, "request_id": "req_1"})

    client = Saturday(api_key="sk_test_fixture", max_retries=0)
    mock(client, send)
    client.athletes.list(external_id="user 42")
    assert seen[0].url.params["external_id"] == "user 42"
    assert seen[0].url.params["limit"] == "50"
