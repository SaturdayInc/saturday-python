import json

import httpx
import pytest

from saturday import AuthenticationError, ConflictError, NotFoundError, PermissionDeniedError, RateLimitError, Saturday, SaturdayError, ValidationError


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
    "simulated_subscriber_daily_limit_reached",
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


@pytest.mark.parametrize("param, message, suggestion", [
    ("legs[1].duration_mins", '"legs[1].duration_mins" is not a field of this request, so its value would not be used. Did you mean "duration_min"? See https://docs.saturday.fit/guides/nutrition-calculation', "duration_min"),
    ("weight_kg", '"weight_kg" is not a field of this request, so its value would not be used. Send "athlete_weight_kg". See https://docs.saturday.fit/guides/nutrition-calculation', "athlete_weight_kg"),
    ("zzz", '"zzz" is not a field of this request, so its value would not be used. See https://docs.saturday.fit/guides/nutrition-calculation', None),
])
def test_unsupported_field_names_the_field_and_the_suggestion(make_client, param, message, suggestion):
    client = make_client(lambda _: httpx.Response(400, json={
        "error": {"type": "invalid_request", "code": "unsupported_field", "param": param, "message": message},
    }))
    with pytest.raises(ValidationError) as raised:
        client.nutrition.calculate(activity_type="bike", duration_min=60)
    assert (raised.value.param, raised.value.suggestion) == (param, suggestion)


def test_other_validation_errors_carry_no_suggestion(make_client):
    client = make_client(lambda _: httpx.Response(400, json={
        "error": {"type": "invalid_request", "code": "invalid_value", "param": "legs", "message": 'Send "legs" with 2 to 10 legs.'},
    }))
    with pytest.raises(ValidationError) as raised:
        client.nutrition.calculate(activity_type="brick", legs=[])
    assert raised.value.suggestion is None


def test_taken_external_id_raises_conflict_naming_the_athlete(make_client):
    calls = []
    client = make_client(lambda r: calls.append(r) or httpx.Response(409, json={"error": {
        "type": "invalid_request", "code": "athlete_exists", "athlete_id": "ath_1", "request_id": "req_1",
        "message": 'An athlete with external_id "user-42" already exists: ath_1. Nothing was created.',
    }}))
    with pytest.raises(ConflictError) as raised:
        client.athletes.create(external_id="user-42")
    assert (raised.value.status, raised.value.code, raised.value.athlete_id) == (409, "athlete_exists", "ath_1")
    assert len(calls) == 1


def test_sync_posts_to_the_intervals_icu_route_with_sync_types(make_client):
    seen = []
    body = {"result": {"provider": "intervals_icu", "status": "completed", "activities_found": 1,
                       "activities_synced": 1, "activities_skipped": 0}, "request_id": "req_1"}
    client = make_client(lambda r: seen.append(r) or httpx.Response(200, json=body))
    synced = client.integrations.sync("intervals_icu", athlete_id="ath_1", access_token="tok",
                                      date_range={"start": "2026-11-01", "end": "2026-11-07"})
    assert synced["result"]["activities_synced"] == 1
    assert seen[0].url.path == "/v1/integrations/intervals_icu/sync"
    assert json.loads(seen[0].content) == {"athlete_id": "ath_1", "access_token": "tok", "sync_types": ["activities"],
                                           "date_range": {"start": "2026-11-01", "end": "2026-11-07"}}


def test_erase_incomplete_is_raised_not_retried(make_client):
    calls = []
    client = make_client(lambda r: calls.append(r) or httpx.Response(503, json={"error": {
        "type": "api_error", "code": "provider_erasure_incomplete",
        "message": "A provider connection you supplied for this athlete could not be revoked yet, so nothing was deleted. Retry the request.",
    }}))
    with pytest.raises(Exception) as raised:
        client.athletes.erase("ath_1")
    assert (raised.value.status, raised.value.code) == (503, "provider_erasure_incomplete")
    assert len(calls) == 1


def test_coach_reads_and_config_writes_use_the_documented_routes(make_client):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler, max_retries=0)
    client.coach.roster(window=7)
    client.coach.roster_digest(window=14)
    client.coach.fueling_rollup("ath_1", window=7, focus="worst")
    client.coach.session_detail("ath_1", "act_1")
    client.coach.get_notification_rules(scope="group", scope_id="grp_1")
    client.coach.set_notification_rules("group", {"preset": "balanced"}, scope_id="grp_1")
    client.coach.apply_preset(scope="overall", preset="balanced")
    client.coach.get_report_settings(scope="athlete", scope_id="ath_1")
    client.coach.set_report_settings("athlete", {"ai_report_window_days": 7}, scope_id="ath_1")
    client.coach.list_webhooks()
    client.coach.register_webhook("https://example.com/hook", events=["concern.detected"])
    client.coach.delete_webhook("cwh_1")
    client.coach.disable_webhook("cwh_1")
    client.coach.enable_webhook("cwh_1")

    calls = [
        (r.method, r.url.path, dict(r.url.params), json.loads(r.content) if r.content else None)
        for r in seen
    ]
    assert calls == [
        ("GET", "/v1/coach/roster", {"window": "7"}, None),
        ("GET", "/v1/coach/roster/digest", {"window": "14"}, None),
        ("GET", "/v1/coach/athletes/ath_1/fueling-rollup", {"window": "7", "focus": "worst"}, None),
        ("GET", "/v1/coach/athletes/ath_1/sessions/act_1", {}, None),
        ("GET", "/v1/coach/config/notification-rules", {"scope": "group", "scope_id": "grp_1"}, None),
        ("PUT", "/v1/coach/config/notification-rules", {},
         {"scope": "group", "scope_id": "grp_1", "rules": {"preset": "balanced"}}),
        ("POST", "/v1/coach/config/preset", {},
         {"scope": "overall", "scope_id": None, "preset": "balanced"}),
        ("GET", "/v1/coach/config/report-settings", {"scope": "athlete", "scope_id": "ath_1"}, None),
        ("PUT", "/v1/coach/config/report-settings", {},
         {"scope": "athlete", "scope_id": "ath_1", "settings": {"ai_report_window_days": 7}}),
        ("GET", "/v1/coach/webhooks", {}, None),
        ("POST", "/v1/coach/webhooks", {},
         {"url": "https://example.com/hook", "events": ["concern.detected"]}),
        ("DELETE", "/v1/coach/webhooks/cwh_1", {}, None),
        ("POST", "/v1/coach/webhooks/cwh_1/disable", {}, None),
        ("POST", "/v1/coach/webhooks/cwh_1/enable", {}, None),
    ]


def test_coach_ids_are_segment_encoded(make_client):
    seen = []

    def handler(request):
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler, max_retries=0)
    client.coach.fueling_rollup("../../partner")
    client.coach.report("a/b?x=1")
    client.coach.report_pdf("a/b")
    client.coach.session_detail("x?admin=true", "a/b")
    client.coach.delete_webhook("../billing/tier-status")
    client.coach.disable_webhook("a/b")
    client.coach.enable_webhook("a/b")
    assert seen[0].startswith("/v1/coach/athletes/..%2F..%2Fpartner/fueling-rollup")
    assert "/v1/coach/athletes/a%2Fb%3Fx%3D1/report" in seen[1]
    assert "/v1/coach/athletes/a%2Fb/report" in seen[2]
    assert "/v1/coach/athletes/x%3Fadmin%3Dtrue/sessions/a%2Fb" in seen[3]
    assert seen[4] == "/v1/coach/webhooks/..%2Fbilling%2Ftier-status"
    assert seen[5] == "/v1/coach/webhooks/a%2Fb/disable"
    assert seen[6] == "/v1/coach/webhooks/a%2Fb/enable"


@pytest.mark.parametrize("bad", [".", ".."])
def test_dot_path_segments_are_rejected(make_client, bad):
    client = make_client(lambda _: httpx.Response(200, json={}), max_retries=0)
    with pytest.raises(ValueError, match="Invalid path segment"):
        client.athletes.get(bad)
    with pytest.raises(ValueError, match="Invalid path segment"):
        client.coach.fueling_rollup(bad)
    with pytest.raises(ValueError, match="Invalid path segment"):
        client.coach.delete_webhook(bad)


def test_lowercase_post_create_is_not_retried_on_5xx(make_client, monkeypatch):
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "Try again"}})

    client = make_client(handler, max_retries=3)
    with pytest.raises(SaturdayError) as raised:
        client.request("post", "/v1/athletes", json={"external_id": "u-1"})
    assert raised.value.status == 503
    assert len(calls) == 1
    assert calls[0].method == "POST"


def test_lowercase_safe_post_is_retried_on_5xx(make_client, monkeypatch):
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: None)
    responses = iter([
        httpx.Response(503, json={"error": {"message": "Try again"}}),
        httpx.Response(200, json={"ok": True}),
    ])
    client = make_client(lambda _: next(responses), max_retries=1)
    assert client.request("post", "/v1/nutrition/calculate", json={"activity_type": "run"}) == {"ok": True}


@pytest.mark.parametrize("bad_path", ["https://evil.invalid/steal", "http://evil.invalid/steal", "//evil.invalid/steal"])
def test_absolute_urls_are_refused_in_request(make_client, bad_path):
    called = []

    def handler(request):
        called.append(request)
        return httpx.Response(200, json={})

    client = make_client(handler, max_retries=0)
    with pytest.raises(ValueError, match="relative URL"):
        client.request("GET", bad_path)
    assert called == []


def test_retry_after_http_date_is_parsed(make_client):
    from datetime import datetime, timedelta, timezone
    from email.utils import formatdate

    future = datetime.now(timezone.utc) + timedelta(seconds=12)
    header = formatdate(future.timestamp(), usegmt=True)
    client = make_client(
        lambda _: httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "Slow"}}, headers={"Retry-After": header}),
        max_retries=0,
    )
    with pytest.raises(RateLimitError) as raised:
        client.onboarding.questions()
    assert raised.value.retry_after is not None
    assert 9 <= raised.value.retry_after <= 13


def test_retry_after_http_date_in_past_clamps_to_zero(make_client):
    from datetime import datetime, timedelta, timezone
    from email.utils import formatdate

    past = datetime.now(timezone.utc) - timedelta(seconds=30)
    header = formatdate(past.timestamp(), usegmt=True)
    client = make_client(
        lambda _: httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "Slow"}}, headers={"Retry-After": header}),
        max_retries=0,
    )
    with pytest.raises(RateLimitError) as raised:
        client.onboarding.questions()
    assert raised.value.retry_after == 0


@pytest.mark.parametrize("header, expected", [("", None), ("   ", None), ("not-a-date", None), ("-5", 0)])
def test_retry_after_empty_and_invalid_are_absent(make_client, header, expected):
    client = make_client(
        lambda _: httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "Slow"}}, headers={"Retry-After": header}),
        max_retries=0,
    )
    with pytest.raises(RateLimitError) as raised:
        client.onboarding.questions()
    assert raised.value.retry_after == expected


def test_retry_after_http_date_drives_503_wait(make_client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from email.utils import formatdate

    sleeps = []
    monkeypatch.setattr("saturday.client.time.sleep", sleeps.append)
    future = datetime.now(timezone.utc) + timedelta(seconds=5)
    header = formatdate(future.timestamp(), usegmt=True)
    responses = iter([
        httpx.Response(503, json={"error": {"message": "Try again"}}, headers={"Retry-After": header}),
        httpx.Response(200, json={"activity_types": [], "total": 0, "request_id": "r"}),
    ])
    client = make_client(lambda _: next(responses))
    assert client.reference.activity_types()["total"] == 0
    assert len(sleeps) == 1
    assert 3 <= sleeps[0] <= 6


@pytest.mark.parametrize("body", [b"null", b'"oops"', b"[1,2]", b"123"])
def test_non_object_error_bodies_become_saturday_error(make_client, body):
    client = make_client(
        lambda _: httpx.Response(500, content=body, headers={"Content-Type": "application/json"}),
        max_retries=0,
    )
    with pytest.raises(SaturdayError) as raised:
        client.onboarding.questions()
    assert raised.value.status == 500
    assert raised.value.code == "unknown"
    assert raised.value.message == "HTTP 500"


def test_nested_null_error_becomes_saturday_error(make_client):
    client = make_client(lambda _: httpx.Response(500, json={"error": None}), max_retries=0)
    with pytest.raises(SaturdayError) as raised:
        client.onboarding.questions()
    assert raised.value.status == 500
    assert raised.value.code == "unknown"


def test_nested_string_error_becomes_saturday_error(make_client):
    client = make_client(lambda _: httpx.Response(404, json={"error": "missing"}), max_retries=0)
    with pytest.raises(NotFoundError) as raised:
        client.onboarding.questions()
    assert raised.value.status == 404
    assert raised.value.code == "unknown"


def test_non_json_error_body_is_truncated(make_client):
    big = ("x" * 5000).encode()
    client = make_client(lambda _: httpx.Response(502, content=big), max_retries=0)
    with pytest.raises(SaturdayError) as raised:
        client.onboarding.questions()
    assert raised.value.status == 502
    assert raised.value.code == "unknown"
    assert len(raised.value.message) == 200


@pytest.mark.parametrize("kwargs, option", [
    ({"api_key": ""}, "api_key"),
    ({"api_key": "sk_test\r\nInjected: 1"}, "api_key"),
    ({"api_key": "sk_test\x00bad"}, "api_key"),
    ({"timeout": 0}, "timeout"),
    ({"timeout": -5}, "timeout"),
    ({"timeout": float("inf")}, "timeout"),
    ({"timeout": float("nan")}, "timeout"),
    ({"max_retries": -1}, "max_retries"),
    ({"max_retries": 1.5}, "max_retries"),
    ({"max_retries": "3"}, "max_retries"),
])
def test_constructor_validates_options(kwargs, option):
    if "api_key" in kwargs:
        with pytest.raises(ValueError, match=option):
            Saturday(**kwargs)
    else:
        with pytest.raises(ValueError, match=option):
            Saturday(api_key="sk_test_fake", **kwargs)


def test_bearer_token_client_may_leave_api_key_empty():
    client = Saturday(api_key="", bearer_token="eyJ.test.token")
    assert client._client.headers["Authorization"] == "Bearer eyJ.test.token"
    client.close()
    with pytest.raises(ValueError, match="bearer_token"):
        Saturday(api_key="", bearer_token="eyJ\r\nX-Evil: 1")


def test_computed_backoff_is_capped_at_max_retry_wait(make_client, monkeypatch):
    sleeps = []
    monkeypatch.setattr("saturday.client.time.sleep", sleeps.append)
    client = make_client(lambda _: httpx.Response(503, json={"error": {"message": "Try again"}}), max_retries=7)
    with pytest.raises(SaturdayError) as raised:
        client.reference.activity_types()
    assert raised.value.status == 503
    assert sleeps == [1, 2, 4, 8, 16, 30, 30]


def test_read_timeout_raises_the_sdk_timeout_once(make_client):
    sent = []

    def handler(request):
        sent.append(request)
        raise httpx.ReadTimeout("read timed out", request=request)

    client = make_client(handler)
    with pytest.raises(SaturdayError) as raised:
        client.onboarding.questions()
    assert (raised.value.status, raised.value.code) == (0, "timeout")
    assert "30" in raised.value.message
    assert len(sent) == 1


@pytest.mark.parametrize("error_type", [httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout])
def test_timeout_variants_raise_the_sdk_timeout_once(make_client, error_type):
    sent = []

    def handler(request):
        sent.append(request)
        raise error_type("timed out", request=request)

    client = make_client(handler)
    with pytest.raises(SaturdayError) as raised:
        client.onboarding.questions()
    assert (raised.value.status, raised.value.code) == (0, "timeout")
    assert len(sent) == 1


def test_connection_failure_raises_connection_error_once(make_client):
    sent = []

    def handler(request):
        sent.append(request)
        raise httpx.ConnectError("connection refused", request=request)

    client = make_client(handler)
    with pytest.raises(SaturdayError) as raised:
        client.onboarding.questions()
    assert (raised.value.status, raised.value.code) == (0, "connection_error")
    assert len(sent) == 1


@pytest.mark.parametrize("error_type, message", [
    (httpx.ReadError, "read error"),
    (httpx.RemoteProtocolError, "protocol error"),
])
def test_other_transport_failures_raise_connection_error_once(make_client, error_type, message):
    sent = []

    def handler(request):
        sent.append(request)
        raise error_type(message, request=request)

    client = make_client(handler)
    with pytest.raises(SaturdayError) as raised:
        client.onboarding.questions()
    assert (raised.value.status, raised.value.code) == (0, "connection_error")
    assert raised.value.message == message
    assert len(sent) == 1


def test_timeout_message_names_the_configured_timeout(make_client):
    def handler(request):
        raise httpx.ReadTimeout("read timed out", request=request)

    client = make_client(handler, timeout=7)
    with pytest.raises(SaturdayError) as raised:
        client.onboarding.questions()
    assert (raised.value.status, raised.value.code) == (0, "timeout")
    assert raised.value.message == "Request timed out after 7s"


@pytest.mark.parametrize("given, expected", [(None, 30.0), (7, 7), (2.5, 2.5)])
def test_timeout_is_wired_to_the_httpx_client(given, expected):
    options = {} if given is None else {"timeout": given}
    client = Saturday(api_key="sk_test_fake", **options)
    try:
        timeout = client._client.timeout
        assert timeout.connect == expected
        assert timeout.read == expected
        assert timeout.write == expected
        assert timeout.pool == expected
    finally:
        client.close()


@pytest.mark.parametrize("status, klass, code", [
    (401, AuthenticationError, "invalid_api_key"),
    (422, ValidationError, "invalid_value"),
])
def test_status_maps_to_the_documented_error_class(make_client, status, klass, code):
    client = make_client(lambda _: httpx.Response(status, json={"error": {
        "type": "invalid_request", "code": code, "param": "duration_min",
        "message": "Refused", "request_id": "req_9",
    }}), max_retries=0)
    with pytest.raises(klass) as raised:
        client.nutrition.calculate(activity_type="run", duration_min=60)
    assert (raised.value.status, raised.value.code, raised.value.request_id) == (status, code, "req_9")
    assert raised.value.param == "duration_min"
    assert raised.value.message == "Refused"
    assert raised.value.error_type == "invalid_request"


@pytest.mark.parametrize("body, code, message", [
    ({"code": "plain_code", "message": "Plain", "param": "p1", "request_id": "req_u"}, "plain_code", "Plain"),
    ({}, "unknown", "HTTP 404"),
    ({"error": {}}, "unknown", "HTTP 404"),
    ({"error": {"message": "Only message"}}, "unknown", "Only message"),
    ({"error": {"code": "only_code"}}, "only_code", "HTTP 404"),
])
def test_error_detail_falls_back_when_fields_are_missing_or_unwrapped(make_client, body, code, message):
    client = make_client(lambda _: httpx.Response(404, json=body), max_retries=0)
    with pytest.raises(NotFoundError) as raised:
        client.onboarding.questions()
    assert (raised.value.status, raised.value.code, raised.value.message) == (404, code, message)


def test_non_json_error_body_becomes_unknown_with_the_body_text(make_client):
    client = make_client(
        lambda _: httpx.Response(502, content=b"<html>Bad Gateway</html>"), max_retries=0)
    with pytest.raises(SaturdayError) as raised:
        client.onboarding.questions()
    assert raised.value.status == 502
    assert raised.value.code == "unknown"
    assert "Bad Gateway" in raised.value.message


def test_non_json_404_body_still_maps_to_not_found(make_client):
    client = make_client(lambda _: httpx.Response(404, content=b"plain not found"), max_retries=0)
    with pytest.raises(NotFoundError) as raised:
        client.onboarding.questions()
    assert (raised.value.status, raised.value.code) == (404, "unknown")
    assert raised.value.message == "plain not found"


@pytest.mark.xfail(reason="200 with a non-JSON or empty body raises JSONDecodeError, not SaturdayError", strict=True)
@pytest.mark.parametrize("body", [b"not JSON", b""])
def test_non_json_success_body_should_raise_saturday_error(make_client, body):
    client = make_client(lambda _: httpx.Response(200, content=body), max_retries=0)
    with pytest.raises(SaturdayError):
        client.onboarding.questions()


@pytest.mark.parametrize("status", [500, 502, 504])
def test_5xx_json_errors_keep_their_code_and_retry_after(make_client, status):
    client = make_client(lambda _: httpx.Response(status, json={"error": {
        "type": "api_error", "code": "service_unavailable", "message": "Try again",
        "request_id": "req_5xx",
    }}, headers={"Retry-After": "9"}), max_retries=0)
    with pytest.raises(SaturdayError) as raised:
        client.onboarding.questions()
    assert type(raised.value) is SaturdayError
    assert (raised.value.status, raised.value.code, raised.value.request_id) == (status, "service_unavailable", "req_5xx")
    assert raised.value.retry_after == 9


@pytest.mark.parametrize("call, calls", [
    (lambda c: c.nutrition.batch_calculate([{"activity_type": "run", "duration_min": 60}]), 2),
    (lambda c: c.nutrition.product_fit(athlete_id="ath_1", activity_type="run", duration_min=60, product_id="p1"), 2),
    (lambda c: c.nutrition.compare_products(athlete_id="ath_1", activity_type="run", duration_min=60, product_a={"product_id": "p1"}, product_b={"product_id": "p2"}), 2),
    (lambda c: c.nutrition.extract(image_base64="AA=="), 2),
    (lambda c: c.infer.activity_type(activity_name="Morning Ride"), 2),
    (lambda c: c.infer.brick_types(activity_name="Brick session"), 2),
    (lambda c: c.athletes.export("ath_1"), 2),
    (lambda c: c.athletes.create_onboarding_link("ath_1"), 2),
    (lambda c: c.webhooks.create("https://example.com/hook", ["athlete.created"]), 1),
    (lambda c: c.partner.create_api_key("ci"), 1),
    (lambda c: c.partner.rotate_api_key("key_1"), 1),
    (lambda c: c.organizations.add_licenses("org_1", "sub_1", [{"athlete_id": "ath_1"}]), 1),
    (lambda c: c.activities.create("ath_1", type="run", duration_min=60), 1),
    (lambda c: c.activities.import_activities("ath_1", [{"type": "run", "duration_min": 60}]), 1),
    (lambda c: c.integrations.sync("intervals_icu", athlete_id="ath_1", access_token="tok"), 1),
    (lambda c: c.knowledge.search("sodium"), 1),
    (lambda c: c.coach.apply_preset(scope="overall", preset="balanced"), 1),
    (lambda c: c.coach.register_webhook("https://example.com/hook"), 1),
    (lambda c: c.coach.set_notification_rules("overall", {"preset": "balanced"}), 2),
    (lambda c: c.athletes.update("ath_1", name="Jo"), 2),
    (lambda c: c.organizations.update_subscription("org_1", "sub_1", seats=10), 2),
    (lambda c: c.webhooks.delete("wh_1"), 2),
    (lambda c: c.coach.delete_webhook("cwh_1"), 2),
], ids=[
    "batch", "product-fit", "compare", "extract", "infer-activity", "infer-brick",
    "export", "onboarding-link", "webhook-create", "key-create", "key-rotate",
    "license-grant", "activity-create", "activity-import", "sync", "knowledge-search",
    "preset", "coach-webhook-register", "put-rules", "patch-athlete",
    "patch-subscription", "delete-webhook", "delete-coach-webhook",
])
def test_5xx_retry_decision_follows_the_call(make_client, monkeypatch, call, calls):
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: None)
    sent = []
    responses = iter([
        httpx.Response(503, json={"error": {"message": "Try again"}}),
        httpx.Response(200, json={"ok": True}),
    ])

    def handler(request):
        sent.append(request)
        return next(responses)

    client = make_client(handler, max_retries=1)
    try:
        call(client)
    except Exception as error:
        assert error.status == 503
    assert len(sent) == calls


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_statuses_are_retried_on_a_read(make_client, monkeypatch, status):
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: None)
    responses = iter([
        httpx.Response(status, json={"error": {"message": "Try again"}}),
        httpx.Response(200, json={"ok": True}),
    ])
    client = make_client(lambda _: next(responses), max_retries=1)
    assert client.reference.activity_types() == {"ok": True}


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_5xx_statuses_are_never_retried_on_a_create(make_client, monkeypatch, status):
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: None)
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(status, json={"error": {"message": "Try again"}})

    client = make_client(handler, max_retries=3)
    with pytest.raises(SaturdayError) as raised:
        client.athletes.create(external_id="u-1")
    assert raised.value.status == status
    assert len(sent) == 1


def test_retries_run_out_after_1_2_and_4_second_waits(make_client, monkeypatch):
    sleeps = []
    monkeypatch.setattr("saturday.client.time.sleep", sleeps.append)
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(503, json={"error": {"message": "Try again"}})

    client = make_client(handler)
    with pytest.raises(Exception) as raised:
        client.reference.activity_types()
    assert raised.value.status == 503
    assert len(sent) == 4
    assert sleeps == [1, 2, 4]


def test_long_503_retry_after_is_raised_not_waited(make_client, monkeypatch):
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: pytest.fail("must not wait 900 s"))
    client = make_client(lambda _: httpx.Response(
        503, json={"error": {"message": "Try again"}}, headers={"Retry-After": "900"}))
    with pytest.raises(Exception) as raised:
        client.reference.activity_types()
    assert (raised.value.status, raised.value.retry_after) == (503, 900)


@pytest.mark.parametrize("wait, calls, sleeps", [
    ("30", 2, [30]),
    ("31", 1, []),
], ids=["thirty-retries", "thirty-one-raises"])
def test_503_retry_after_boundary(make_client, monkeypatch, wait, calls, sleeps):
    recorded = []
    monkeypatch.setattr("saturday.client.time.sleep", recorded.append)
    sent = []
    responses = iter([
        httpx.Response(503, json={"error": {"message": "Try again"}}, headers={"Retry-After": wait}),
        httpx.Response(200, json={"ok": True}),
    ])

    def handler(request):
        sent.append(request)
        return next(responses)

    client = make_client(handler, max_retries=1)
    try:
        client.reference.activity_types()
    except SaturdayError as error:
        assert (error.status, error.retry_after) == (503, 31)
    assert len(sent) == calls
    assert recorded == sleeps


def test_429_then_5xx_retries_both(make_client, monkeypatch):
    sleeps = []
    monkeypatch.setattr("saturday.client.time.sleep", sleeps.append)
    responses = iter([
        httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "Slow"}}, headers={"Retry-After": "2"}),
        httpx.Response(503, json={"error": {"message": "Try again"}}),
        httpx.Response(200, json={"ok": True}),
    ])
    client = make_client(lambda _: next(responses), max_retries=3)
    assert client.reference.activity_types() == {"ok": True}
    assert sleeps == [2, 2]


def test_5xx_then_429_retries_both(make_client, monkeypatch):
    sleeps = []
    monkeypatch.setattr("saturday.client.time.sleep", sleeps.append)
    responses = iter([
        httpx.Response(503, json={"error": {"message": "Try again"}}),
        httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "Slow"}}, headers={"Retry-After": "3"}),
        httpx.Response(200, json={"ok": True}),
    ])
    client = make_client(lambda _: next(responses), max_retries=3)
    assert client.reference.activity_types() == {"ok": True}
    assert sleeps == [1, 3]


def test_429_retries_run_out(make_client, monkeypatch):
    sleeps = []
    monkeypatch.setattr("saturday.client.time.sleep", sleeps.append)
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "Slow"}}, headers={"Retry-After": "1"})

    client = make_client(handler)
    with pytest.raises(RateLimitError) as raised:
        client.reference.activity_types()
    assert raised.value.retry_after == 1
    assert len(sent) == 4
    assert sleeps == [1, 1, 1]


def test_429_throttle_retries_even_a_create(make_client, monkeypatch):
    sleeps = []
    monkeypatch.setattr("saturday.client.time.sleep", sleeps.append)
    responses = iter([
        httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "message": "Slow"}}, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"ok": True}),
    ])
    sent = []

    def handler(request):
        sent.append(request)
        return next(responses)

    client = make_client(handler, max_retries=1)
    assert client.athletes.create(external_id="u-1") == {"ok": True}
    assert len(sent) == 2
    assert sleeps == [0]


def test_max_retries_zero_disables_5xx_retry_on_a_read(make_client, monkeypatch):
    monkeypatch.setattr("saturday.client.time.sleep", lambda _: pytest.fail("max_retries=0 must not sleep"))
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(503, json={"error": {"message": "Try again"}})

    client = make_client(handler, max_retries=0)
    with pytest.raises(SaturdayError) as raised:
        client.reference.activity_types()
    assert raised.value.status == 503
    assert len(sent) == 1


def test_coach_calls_without_optional_arguments_send_no_query_and_empty_events(make_client):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler, max_retries=0)
    client.coach.roster()
    client.coach.roster_digest()
    client.coach.get_notification_rules()
    client.coach.get_report_settings()
    client.coach.register_webhook("https://example.com/hook")
    client.coach.report("ath_1")
    client.coach.report("ath_1", window=7, refresh=True)

    calls = [
        (r.method, r.url.path, dict(r.url.params), json.loads(r.content) if r.content else None)
        for r in seen
    ]
    assert calls == [
        ("GET", "/v1/coach/roster", {}, None),
        ("GET", "/v1/coach/roster/digest", {}, None),
        ("GET", "/v1/coach/config/notification-rules", {}, None),
        ("GET", "/v1/coach/config/report-settings", {}, None),
        ("POST", "/v1/coach/webhooks", {}, {"url": "https://example.com/hook", "events": []}),
        ("GET", "/v1/coach/athletes/ath_1/report", {}, None),
        ("GET", "/v1/coach/athletes/ath_1/report", {"window": "7", "refresh": "true"}, None),
    ]


def test_two_page_walk_feeds_the_first_next_cursor_to_the_second_call(make_client):
    sent = []
    pages = iter([
        {"athletes": [{"id": "ath_1"}], "pagination": {"total": 2, "has_more": True, "next_cursor": "1700000001"}, "request_id": "r1"},
        {"athletes": [{"id": "ath_2"}], "pagination": {"total": 2, "has_more": False, "next_cursor": None}, "request_id": "r2"},
    ])

    def handler(request):
        sent.append(dict(request.url.params))
        return httpx.Response(200, json=next(pages))

    client = make_client(handler, max_retries=0)
    first = client.athletes.list(limit=1)
    second = client.athletes.list(limit=1, cursor=first["pagination"]["next_cursor"])
    assert first["pagination"]["has_more"] is True
    assert second["pagination"]["has_more"] is False
    assert sent == [{"limit": "1"}, {"limit": "1", "cursor": "1700000001"}]


def test_ledger_walk_feeds_the_first_next_cursor_to_the_second_call(make_client):
    sent = []
    pages = iter([
        {"entries": [{"id": "e1"}], "next_cursor": "1749480000000", "request_id": "r1"},
        {"entries": [], "next_cursor": None, "request_id": "r2"},
    ])

    def handler(request):
        sent.append(dict(request.url.params))
        return httpx.Response(200, json=next(pages))

    client = make_client(handler, max_retries=0)
    first = client.coach.ledger(view="inflows", limit=1)
    client.coach.ledger(view="inflows", limit=1, cursor=first["next_cursor"])
    assert sent == [
        {"view": "inflows", "limit": "1"},
        {"view": "inflows", "limit": "1", "cursor": "1749480000000"},
    ]


@pytest.mark.parametrize("given, sent_value", [
    (True, "true"),
    (False, "false"),
    (None, None),
], ids=["true", "false", "omitted"])
def test_athletes_list_profile_complete_filter(make_client, given, sent_value):
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"athletes": [], "pagination": {"total": 0, "has_more": False}, "request_id": "r"})

    client = make_client(handler, max_retries=0)
    client.athletes.list(profile_complete=given)
    if sent_value is None:
        assert seen == [{"limit": "50"}]
    else:
        assert seen == [{"limit": "50", "profile_complete": sent_value}]


def test_bad_cursor_is_sent_verbatim_and_its_error_maps(make_client):
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(400, json={"error": {
            "type": "invalid_request", "code": "invalid_value", "param": "cursor",
            "message": "Bad cursor", "request_id": "req_bad",
        }})

    client = make_client(handler, max_retries=0)
    with pytest.raises(ValidationError) as raised:
        client.athletes.list(cursor="not-a-cursor")
    assert (raised.value.code, raised.value.param, raised.value.request_id) == ("invalid_value", "cursor", "req_bad")
    assert seen == [{"limit": "50", "cursor": "not-a-cursor"}]


def test_sdk_headers_are_sent_on_every_request(make_client):
    from saturday.client import SDK_VERSION

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler, max_retries=0)
    client.onboarding.questions()
    assert seen[0].headers["User-Agent"] == f"saturday-python/{SDK_VERSION}"
    assert seen[0].headers["X-SDK-Version"] == SDK_VERSION
    assert seen[0].headers["Content-Type"] == "application/json"
    assert seen[0].headers["Authorization"].startswith("Bearer ")


def test_trailing_slash_on_base_url_hits_the_same_route():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    client = Saturday(api_key="sk_test_fake", base_url="https://api.saturday.fit///", max_retries=0)
    headers = client._client.headers
    client._client.close()
    client._client = httpx.Client(base_url=client._base_url, headers=headers, transport=httpx.MockTransport(handler))
    try:
        assert client._base_url == "https://api.saturday.fit"
        assert client.onboarding.questions() == {"ok": True}
        assert str(seen[0].url) == "https://api.saturday.fit/v1/onboarding/questions"
    finally:
        client.close()


@pytest.mark.parametrize("call, raw_path", [
    (lambda c: c.athletes.get("a/b c"), "/v1/athletes/a%2Fb%20c"),
    (lambda c: c.activities.get("ath 1", "act/1"), "/v1/athletes/ath%201/activities/act%2F1"),
    (lambda c: c.webhooks.get("wh/1"), "/v1/webhooks/wh%2F1"),
    (lambda c: c.partner.revoke_api_key("key/1"), "/v1/partner/api-keys/key%2F1"),
    (lambda c: c.organizations.get("org/1"), "/v1/organizations/org%2F1"),
    (lambda c: c.knowledge.get_article("art/1?x=2"), "/v1/knowledge/articles/art%2F1%3Fx%3D2"),
], ids=["athlete", "activity", "webhook", "api-key", "organization", "article"])
def test_path_segments_are_encoded_across_resources(make_client, call, raw_path):
    seen = []

    def handler(request):
        seen.append(request.url.raw_path.decode())
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler, max_retries=0)
    call(client)
    assert seen == [raw_path]


def test_direct_request_sends_params_json_and_raw(make_client):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/v1/empty":
            return httpx.Response(204)
        if request.url.path == "/v1/raw":
            return httpx.Response(200, content=b"rawbytes")
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler, max_retries=0)
    assert client.request("GET", "/v1/health", params={"verbose": "1"}) == {"ok": True}
    assert client.request("POST", "/v1/health", json={"x": 1}) == {"ok": True}
    assert client.request("GET", "/v1/raw", raw=True) == b"rawbytes"
    assert client.request("GET", "/v1/empty", raw=True) is None
    assert client.request("get", "/v1/health") == {"ok": True}
    assert seen[0].method == "GET" and dict(seen[0].url.params) == {"verbose": "1"}
    assert seen[1].method == "POST" and json.loads(seen[1].content) == {"x": 1}
    assert seen[4].method == "GET"


def test_close_is_idempotent_and_later_calls_fail(make_client):
    client = make_client(lambda _: httpx.Response(200, json={"ok": True}), max_retries=0)
    assert client.onboarding.questions() == {"ok": True}
    client.close()
    client.close()
    with pytest.raises(RuntimeError, match="client has been closed"):
        client.onboarding.questions()


def test_context_manager_closes_on_exit():
    client = Saturday(api_key="sk_test_fake", max_retries=0)
    client._client.close()
    client._client = httpx.Client(
        base_url=client._base_url,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True})),
    )
    with client as entered:
        assert entered is client
        assert entered.onboarding.questions() == {"ok": True}
    with pytest.raises(RuntimeError, match="client has been closed"):
        client.onboarding.questions()
