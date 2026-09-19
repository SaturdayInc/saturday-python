import httpx
import pytest

from saturday import NotFoundError, RateLimitError, Saturday


@pytest.fixture
def make_client(monkeypatch):
    clients = []

    def make(handler, **options):
        client = Saturday(api_key="cp_test_placeholder", **options)
        headers = client._client.headers
        client._client.close()
        client._client = httpx.Client(
            base_url=client._base_url,
            headers=headers,
            transport=httpx.MockTransport(handler),
        )
        clients.append(client)
        return client

    monkeypatch.setattr("saturday.client.time.sleep", lambda _: None)
    yield make
    for client in clients:
        client.close()


def test_report_pdf_bytes_and_options(make_client):
    pdf = b"%PDF-1.7\n\x00\xffreport"

    def handler(request):
        assert request.method == "GET"
        assert request.url.path == "/v1/coach/athletes/athlete_123/report"
        assert dict(request.url.params) == {"format": "pdf", "window": "14", "focus": "rolling"}
        assert request.headers["Authorization"] == "Bearer cp_test_placeholder"
        return httpx.Response(200, content=pdf, headers={"Content-Type": "application/pdf"})

    client = make_client(handler)
    assert client.coach.report_pdf("athlete_123", window=14, focus="rolling") == pdf


def test_report_pdf_maps_not_found(make_client):
    client = make_client(lambda _: httpx.Response(404, json={
        "error": {"type": "resource_not_found", "code": "resource_not_found", "message": "Not found"},
    }))
    with pytest.raises(NotFoundError):
        client.coach.report_pdf("athlete_123")


def test_report_pdf_retries_temporary_errors(make_client):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": {"message": "Try again"}})
        return httpx.Response(200, content=b"%PDF-1.7")

    client = make_client(handler, max_retries=1)
    assert client.coach.report_pdf("athlete_123") == b"%PDF-1.7"
    assert len(calls) == 2


def test_report_stays_json(make_client):
    client = make_client(lambda _: httpx.Response(200, json={"narrative": "Report"}))
    assert client.coach.report("athlete_123") == {"narrative": "Report"}


def test_rate_limit_preserves_retry_after(make_client):
    client = make_client(lambda _: httpx.Response(429, json={
        "error": {"type": "rate_limit_error", "code": "rate_limit_exceeded", "message": "Slow down"},
    }, headers={"Retry-After": "17"}), max_retries=0)
    with pytest.raises(RateLimitError) as raised:
        client.onboarding.questions()
    assert raised.value.retry_after == 17


def test_empty_response(make_client):
    client = make_client(lambda _: httpx.Response(204))
    assert client.athletes.delete("athlete_123") is None
