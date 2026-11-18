"""The SDK neither calls nor names routes no partner key reaches."""

from pathlib import Path

from saturday import Saturday

HIDDEN_PATHS = ["/v1/products", "/v1/ai/", "/ai/conversations", "/gear"]


def test_calls_no_route_closed_to_partners():
    for source in (Path(__file__).parent.parent / "saturday").glob("*.py"):
        text = source.read_text()
        for path in HIDDEN_PATHS:
            assert path not in text, f"{source.name} names {path}"


def test_has_no_products_ai_or_gear_resource():
    client = Saturday(api_key="sk_test_hidden")
    for resource in ("products", "ai", "gear"):
        assert not hasattr(client, resource), resource
