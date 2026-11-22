import json

import httpx

from saturday import Saturday


def _client(send):
    client = Saturday(api_key="sk_test_fake", max_retries=0)
    client._client.close()
    client._client = httpx.Client(base_url=client._base_url, transport=httpx.MockTransport(send))
    return client


def test_organizations_list_sends_limit_and_cursor_and_nothing_when_left_out():
    seen = []

    def send(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"organizations": [], "pagination": {"total": 0, "has_more": False}, "request_id": "req_1"})

    with _client(send) as client:
        client.organizations.list(limit=200, cursor="1700000000")
        client.organizations.list()
    assert seen == [{"limit": "200", "cursor": "1700000000"}, {}]


def test_batch_calculate_sends_estimate_only_only_when_asked():
    bodies = []

    def send(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [], "total": 1, "succeeded": 0, "failed": 0, "estimated_ms": 100, "elapsed_ms": 0, "request_id": "req_1"})

    scenarios = [{"activity_type": "bike", "duration_min": 120}]
    with _client(send) as client:
        client.nutrition.batch_calculate(scenarios, estimate_only=True)
        client.nutrition.batch_calculate(scenarios)
    assert bodies == [{"scenarios": scenarios, "estimate_only": True}, {"scenarios": scenarios}]


def test_activities_list_leaves_the_page_size_to_the_api():
    seen = []

    def send(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"activities": [], "pagination": {"total": 0, "has_more": False}, "request_id": "req_1"})

    with _client(send) as client:
        client.activities.list("ath_1")
        client.activities.list("ath_1", limit=10)
    assert seen == [{}, {"limit": "10"}]
