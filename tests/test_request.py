import json

import httpx
import pytest

from saturday import ConflictError, NotFoundError, PermissionDeniedError, RateLimitError, Saturday, SaturdayError, ValidationError


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


def test_computed_backoff_is_capped_at_max_retry_wait(make_client, monkeypatch):
    sleeps = []
    monkeypatch.setattr("saturday.client.time.sleep", sleeps.append)
    client = make_client(lambda _: httpx.Response(503, json={"error": {"message": "Try again"}}), max_retries=7)
    with pytest.raises(SaturdayError) as raised:
        client.reference.activity_types()
    assert raised.value.status == 503
    assert sleeps == [1, 2, 4, 8, 16, 30, 30]
