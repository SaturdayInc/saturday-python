"""The SDK neither calls nor names routes no partner key reaches: closed to partners, retired (the
key purchase) or called with a signed-in Saturday account rather than a key (saturday.fit/api)."""

from pathlib import Path

from saturday import Saturday

HIDDEN_PATHS = ["/v1/products", "/v1/ai/", "/ai/conversations", "/gear", "/v1/signup", "/v1/account/"]


def test_calls_no_route_closed_to_partners():
    for source in (Path(__file__).parent.parent / "saturday").glob("*.py"):
        text = source.read_text()
        for path in HIDDEN_PATHS:
            assert path not in text, f"{source.name} names {path}"


def test_client_lacks_hidden_resources():
    client = Saturday(api_key="sk_test_x")
    for resource in ("products", "ai", "gear"):
        assert not hasattr(client, resource), resource
