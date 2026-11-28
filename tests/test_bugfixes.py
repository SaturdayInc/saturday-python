"""Regression tests for bugs found by auditing the client against its docs.

Each test here failed against the code as found; the paired fix keeps the
public API unchanged. The bug each test pins is stated in its docstring.
"""

import re
from pathlib import Path

import httpx
import pytest

from saturday import (
    AuthenticationError, ConflictError, NotFoundError, PermissionDeniedError,
    RateLimitError, Saturday, SaturdayError, ValidationError,
)


def _client(handler, **options):
    client = Saturday(api_key="sk_test_fake", **options)
    headers = client._client.headers
    client._client.close()
    client._client = httpx.Client(base_url=client._base_url, headers=headers,
                                  transport=httpx.MockTransport(handler))
    return client


@pytest.mark.parametrize("body", [b"not JSON", b""])
def test_non_json_success_body_raises_saturday_error(body):
    """Bug: a 200 whose body is not JSON (or is empty) raised
    json.JSONDecodeError out of request(), not a SaturdayError, so callers
    catching the SDK's documented error type missed it."""
    client = _client(lambda _: httpx.Response(200, content=body), max_retries=0)
    with pytest.raises(SaturdayError) as raised:
        client.onboarding.questions()
    assert (raised.value.status, raised.value.code) == (200, "invalid_response")


def test_raw_success_body_is_returned_without_json_parsing():
    """The raw path (coach.report_pdf) keeps returning bytes untouched."""
    client = _client(lambda _: httpx.Response(200, content=b"not JSON"), max_retries=0)
    assert client.request("GET", "/v1/health", raw=True) == b"not JSON"


@pytest.mark.parametrize("status, klass", [
    (400, ValidationError), (401, AuthenticationError), (403, PermissionDeniedError),
    (404, NotFoundError), (409, ConflictError), (422, ValidationError),
])
def test_retry_after_is_kept_on_typed_errors(status, klass):
    """Bug: SaturdayError.from_response computed Retry-After for every status
    but passed it only to RateLimitError and the untyped 5xx class, so a typed
    4xx that carried the header reported retry_after None. The changelog
    promises retry_after "from Retry-After on any error that carries one"."""
    client = _client(lambda _: httpx.Response(status, json={"error": {"message": "Refused"}},
                                              headers={"Retry-After": "9"}), max_retries=0)
    with pytest.raises(klass) as raised:
        client.onboarding.questions()
    assert raised.value.retry_after == 9


@pytest.mark.parametrize("call", [
    lambda c: c.athletes.get(""),
    lambda c: c.activities.get("ath_1", ""),
    lambda c: c.knowledge.get_article(""),
    lambda c: c.coach.delete_webhook(""),
    lambda c: c.integrations.status("", "ath_1"),
])
def test_empty_path_segment_is_rejected_before_any_request(call):
    """Bug: _seg rejected "." and ".." for reaching another route but encoded
    "" to "", so athletes.get("") requested GET /v1/athletes/ (the collection
    route) instead of failing locally like its dot-segment siblings."""
    client = _client(lambda _: pytest.fail("no request should be sent"), max_retries=0)
    with pytest.raises(ValueError, match="Invalid path segment"):
        call(client)


def test_permission_denial_on_subscription_and_knowledge():
    """The 403 class is PermissionDeniedError on these routes too (their
    docstrings once named the builtin PermissionError instead)."""
    forbidden = lambda _: httpx.Response(  # noqa: E731
        403, json={"error": {"type": "authorization_error", "code": "feature_alpha", "message": "Closed."}})
    client = _client(forbidden, max_retries=0)
    with pytest.raises(PermissionDeniedError):
        client.knowledge.list_topics()
    restricted = lambda _: httpx.Response(  # noqa: E731
        403, json={"error": {"type": "authorization_error", "code": "organization_subscription_restricted",
                             "message": "Seat subscriptions are set up with Saturday."}})
    client = _client(restricted, max_retries=0)
    with pytest.raises(PermissionDeniedError) as raised:
        client.organizations.create_subscription("org_1", type="team", seats=5, start_date=1, end_date=2)
    assert raised.value.code == "organization_subscription_restricted"


def test_docstrings_name_permission_denied_error():
    """Bug: organizations.create_subscription and the knowledge resource
    docstrings said the refusal raises PermissionError. Nothing in the SDK
    raises the builtin; a caller catching it would never see the 403."""
    for source in (Path(__file__).parent.parent / "saturday").glob("*.py"):
        assert "PermissionError" not in source.read_text(), source.name


def test_readme_resource_table_lists_every_method():
    """Bug: the README's athlete row omitted create_onboarding_link, a public
    method added in 0.9.0. Every non-coach row must name exactly the
    resource's public methods (the coach row is a prose summary)."""
    import inspect

    readme = (Path(__file__).parent.parent / "README.md").read_text()
    rows = {}
    for line in readme.splitlines():
        match = re.match(r"\| `client\.(\w+)` \| (.*) \|$", line)
        if match:
            rows[match.group(1)] = set(re.findall(r"`([a-z_]+)`", match.group(2)))
    client = Saturday(api_key="sk_test_fake")
    try:
        for name in ("nutrition", "athletes", "activities", "onboarding", "reference", "infer", "partner",
                     "webhooks", "organizations", "integrations", "testing", "meta", "knowledge"):
            actual = {m for m, _ in inspect.getmembers(getattr(client, name), predicate=inspect.ismethod)
                      if not m.startswith("_")}
            assert rows[name] == actual, f"README row for {name}: table {sorted(rows[name])} != client {sorted(actual)}"
    finally:
        client.close()


@pytest.mark.parametrize("timeout", ["30", True])
def test_timeout_must_be_a_number(timeout):
    """A timeout of the wrong type raises the same ValueError as an
    out-of-range one (the type branch of the constructor check)."""
    with pytest.raises(ValueError, match="timeout"):
        Saturday(api_key="sk_test_fake", timeout=timeout)


def test_retry_after_date_parser_returning_none_is_absent(monkeypatch):
    """parsedate_to_datetime raises on unparseable dates since Python 3.10,
    so from_response's None guard is unreachable with the stdlib parser on
    supported interpreters. Patch the parser to return None and check the
    guard still reports no wait rather than crashing."""
    monkeypatch.setattr("saturday.errors.parsedate_to_datetime", lambda _: None)
    error = SaturdayError.from_response(
        429, {"error": {"code": "rate_limit_exceeded", "message": "Slow"}}, "whenever")
    assert error.retry_after is None


def test_retry_after_http_date_without_timezone_is_read_as_utc():
    """An HTTP-date Retry-After with the -0000 zone parses to a naive
    datetime; the parser reads it as UTC rather than dropping it."""
    client = _client(lambda _: httpx.Response(429, json={"error": {"code": "rate_limited", "message": "Wait"}},
                                              headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00 -0000"}), max_retries=0)
    with pytest.raises(RateLimitError) as raised:
        client.onboarding.questions()
    assert raised.value.retry_after is not None and raised.value.retry_after > 0
