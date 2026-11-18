import httpx
import pytest

from saturday import NotFoundError, PermissionDeniedError, RateLimitError, Saturday


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


@pytest.mark.parametrize("header, expected", [(None, None), ("invalid", None), ("-1", 0)])
def test_rate_limit_retry_after_parsing(make_client, header, expected):
    headers = {} if header is None else {"Retry-After": header}
    client = make_client(lambda _: httpx.Response(429, json={
        "error": {"message": "Slow down"},
    }, headers=headers), max_retries=0)
    with pytest.raises(RateLimitError) as raised:
        client.onboarding.questions()
    assert raised.value.retry_after == expected
    assert raised.value.daily_limit is (expected is None)


def test_waits_retry_after_then_retries(make_client, monkeypatch):
    sleeps = []
    monkeypatch.setattr("saturday.client.time.sleep", sleeps.append)
    responses = iter([
        httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "Retry after 2 seconds."}}, headers={"Retry-After": "2"}),
        httpx.Response(200, json={"activity_types": [], "total": 0, "request_id": "req_1"}),
    ])
    client = make_client(lambda _: next(responses))
    assert client.reference.activity_types()["total"] == 0
    assert sleeps == [2]


def test_daily_ceiling_raises_at_once(make_client, monkeypatch):
    calls = []
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: pytest.fail("a daily ceiling must not be retried"))

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={"error": {"type": "rate_limit_error", "code": "rate_limit_exceeded",
                                                   "message": "Daily call limit reached (2000/day)."}})

    client = make_client(handler)
    with pytest.raises(RateLimitError) as raised:
        client.nutrition.calculate(activity_type="run", duration_min=60)
    assert raised.value.daily_limit
    assert len(calls) == 1


def test_long_retry_after_is_raised_not_waited(make_client, monkeypatch):
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: pytest.fail("a 17-minute wait must not be slept"))
    client = make_client(lambda _: httpx.Response(429, json={
        "error": {"code": "rate_limited", "message": "New products resume in 17 minutes."},
    }, headers={"Retry-After": "1020"}))
    with pytest.raises(RateLimitError) as raised:
        client.nutrition.product_fit(athlete_id="ath_1", product_query="maurten gel 100", activity_type="run", duration_min=60)
    assert raised.value.retry_after == 1020
    assert not raised.value.daily_limit


def test_403_is_permission_denied(make_client):
    client = make_client(lambda _: httpx.Response(403, json={
        "error": {"type": "authorization_error", "code": "feature_alpha", "message": "The knowledge feature is in alpha."},
    }))
    with pytest.raises(PermissionDeniedError) as raised:
        client.knowledge.search("sodium")
    assert raised.value.code == "feature_alpha"


def test_empty_response(make_client):
    client = make_client(lambda _: httpx.Response(204))
    assert client.athletes.delete("athlete_123") is None


def test_create_is_not_retried_on_5xx(make_client, monkeypatch):
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: pytest.fail("a create must not be retried"))
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "Try again"}})

    client = make_client(handler)
    with pytest.raises(Exception) as raised:
        client.athletes.create(external_id="u-1")
    assert raised.value.status == 503
    assert len(calls) == 1


@pytest.mark.parametrize("call", [
    lambda c: c.nutrition.calculate(activity_type="run", duration_min=60),
    lambda c: c.activities.calculate_prescription("ath_1", "act_1"),
    lambda c: c.activities.prep("ath_1", "act_1"),
])
def test_compute_posts_are_retried_on_5xx(make_client, monkeypatch, call):
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: None)
    responses = iter([httpx.Response(503, json={"error": {"message": "Try again"}}), httpx.Response(200, json={"tier": "teaser"})])
    client = make_client(lambda _: next(responses))
    assert call(client) == {"tier": "teaser"}


def test_31_second_retry_after_is_raised(make_client, monkeypatch):
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: pytest.fail("must not wait 31 s"))
    client = make_client(lambda _: httpx.Response(429, json={"error": {"message": "Slow down"}}, headers={"Retry-After": "31"}))
    with pytest.raises(RateLimitError) as raised:
        client.onboarding.questions()
    assert raised.value.retry_after == 31


def _too_many(code, headers=None):
    return httpx.Response(429, json={"error": {"type": "rate_limit_error", "code": code, "message": code}}, headers=headers or {})


@pytest.mark.parametrize("code", [
    "daily_call_limit_reached", "intelligence_daily_limit_reached",
    "athlete_free_daily_limit_reached", "distinct_lookup_daily_limit_reached",
])
def test_daily_codes_are_never_retried_and_carry_the_reset(make_client, monkeypatch, code):
    from datetime import datetime, timezone
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: pytest.fail("a daily ceiling must not be slept on"))
    calls = []
    client = make_client(lambda r: calls.append(r) or _too_many(code, {"Retry-After": "20"}))
    before = datetime.now(timezone.utc)
    with pytest.raises(RateLimitError) as raised:
        client.nutrition.calculate(activity_type="run", duration_min=60)
    assert raised.value.daily_limit and not raised.value.retryable
    assert (raised.value.resets_at - before).total_seconds() >= 19
    assert len(calls) == 1


def test_older_daily_ceiling_resets_at_next_utc_midnight():
    from datetime import datetime, timezone
    error = RateLimitError("Daily call limit reached", status=429, code="rate_limit_exceeded",
                           now=datetime(2026, 11, 18, 22, 30, tzinfo=timezone.utc))
    assert error.daily_limit
    assert error.resets_at == datetime(2026, 11, 19, tzinfo=timezone.utc)


@pytest.mark.parametrize("code, wait, calls", [
    ("rate_limit_exceeded", "2", 2),
    ("catalog_paced", "20", 2),
    ("catalog_paced", "900", 1),
    ("rate_limited", "5", 1),
])
def test_codes_decide_the_retry(make_client, monkeypatch, code, wait, calls):
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: None)
    sent = []
    responses = iter([_too_many(code, {"Retry-After": wait}), httpx.Response(200, json={"activity_types": [], "total": 0, "request_id": "r"})])

    def handler(request):
        sent.append(request)
        return next(responses)

    client = make_client(handler)
    try:
        client.reference.activity_types()
    except RateLimitError as error:
        assert error.retry_after == int(wait)
    assert len(sent) == calls


def test_503_retry_after_is_the_wait(make_client, monkeypatch):
    sleeps = []
    monkeypatch.setattr("saturday.client.time.sleep", sleeps.append)
    responses = iter([
        httpx.Response(503, json={"error": {"type": "api_error", "code": "service_unavailable", "message": "Try again"}}, headers={"Retry-After": "5"}),
        httpx.Response(200, json={"activity_types": [], "total": 0, "request_id": "r"}),
    ])
    client = make_client(lambda _: next(responses))
    assert client.reference.activity_types()["total"] == 0
    assert sleeps == [5]
