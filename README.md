# Saturday Python SDK

[![PyPI](https://img.shields.io/pypi/v/saturday)](https://pypi.org/project/saturday/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Official Python SDK for the [Saturday Nutrition Intelligence API](https://docs.saturday.fit).

Personalized fuel, hydration, and electrolyte prescriptions for endurance athletes.

## Install

```bash
pip install saturday
```

## Quick Start

```python
from saturday import Saturday

client = Saturday(api_key="sk_live_...")

# Calculate a nutrition prescription
prescription = client.nutrition.calculate(
    activity_type="bike",
    duration_min=180,
    athlete_weight_kg=75,
    thermal_stress_level=7,
    is_race=True,
)

# Safety metadata is included on every tier.
print(prescription["safety"]["warnings"])
carbs = prescription.get("carb_range_g_per_hr", prescription.get("carb_g_per_hr", 0))
sodium = prescription.get("sodium_range_mg_per_hr", prescription.get("sodium_mg_per_hr", 0))
fluid = prescription.get("fluid_range_ml_per_hr", prescription.get("fluid_ml_per_hr", 0))
print(f"Carbs: {carbs} g/hr")
print(f"Sodium: {sodium} mg/hr")
print(f"Fluid: {fluid} mL/hr")
```

Teaser responses and incomplete profiles return ranges. A `full` tier alone does not guarantee exact numbers. Exact zero values may be omitted from the response, so the example displays them as `0`. See [Athlete Onboarding](https://docs.saturday.fit/guides/onboarding).

## Features

- Type hints with a `py.typed` marker (PEP 561); resource responses are dictionaries
- Automatic retry with exponential backoff for JSON operations; AI stream writes are never replayed
- Typed errors (`AuthenticationError`, `RateLimitError`, `ValidationError`, `NotFoundError`)
- API key and OAuth2 Bearer token authentication
- Context manager support for clean connection handling
- Safety types prominently surfaced (`not_instructions` documented)

## Authentication

```python
# API key (server-to-server)
client = Saturday(api_key="sk_live_...")

# OAuth2 Bearer token (athlete-delegated access)
client = Saturday(api_key="sk_live_...", bearer_token="eyJ...")

# Context manager for automatic cleanup
with Saturday(api_key="sk_live_...") as client:
    rx = client.nutrition.calculate(activity_type="run", duration_min=60)
```

## Error Handling

```python
from saturday import Saturday, RateLimitError, ValidationError, NotFoundError

client = Saturday(api_key="sk_live_...")

try:
    rx = client.nutrition.calculate(activity_type="swim", duration_min=60)
except ValidationError as e:
    print(f"Invalid request: {e} (param: {e.param})")
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after}s")
except NotFoundError:
    print("Resource not found")
```

## Resources

| Resource | Description |
|----------|-------------|
| `client.nutrition` | Calculate prescriptions, batch calculate |
| `client.athletes` | Athlete CRUD, settings, batch create, GDPR export |
| `client.activities` | Activity CRUD, prescription calculation, feedback |
| `client.products` | Product search, barcode lookup, curated list |
| `client.ai` | Async AI event streams plus synchronous JSON metadata and history |
| `client.webhooks` | Webhook registration and management |
| `client.organizations` | Team/org management with members |
| `client.gear` | Athlete gear inventory |
| `client.knowledge` | Sports nutrition knowledge base search |

## AI writes

Use `ai.create_conversation_stream(athlete_id, message)` and `ai.send_message_stream(conversation_id, message)` with `async with`, then `async for`. These additive methods are asynchronous, even though the existing JSON SDK methods remain synchronous. Events are dictionaries with `event`, `data`, `raw_data` and optional `id`, preserving unknown event names and JSON fields.

Compatibility change: the legacy `ai.create_conversation()` and `ai.send_message()` methods now raise `AIStreamError` with code `streaming_required` locally, before any HTTP request. Migrate to the stream methods. The server never returned their promised JSON objects; the SDK does not invent metadata or timestamps to imitate them.

```python
import asyncio
from saturday import Saturday, AIStreamError

async def main():
    with Saturday(api_key="sk_live_...") as client:
        try:
            async with client.ai.create_conversation_stream(
                "YOUR_ATHLETE_ID", "Help me review my fueling plan", timeout=30.0
            ) as events:
                async for event in events:
                    # Keep warnings, errors and unknown events, not only text.
                    print(event["event"], event["data"])
        except AIStreamError as error:
            print(error.code, error.event)
            raise  # No automatic retry: the write may already be accepted.

asyncio.run(main())
```

The `message_start` event supplies `data["conversation_id"]`. Current names include `text_delta`, `safety_warning`, `error`, `tool_call`, `tool_result`, `action`, `replay` and `message_end`. `message_end` is not a success verdict: server error events are yielded, then iteration raises `stream_error` after the response finishes. Warnings, including generation-halted safety warnings, must remain visible even if no exception is raised.

AI stream writes never automatically retry, including HTTP 429/5xx, connection errors, malformed JSON/UTF-8 (`malformed_stream`), cancellation and premature EOF (`incomplete_stream`). `max_retries` does not apply. Preserve received events as partial output, not a complete answer. Inspect conversation state before deliberately submitting another message; these writes have no idempotency key.

The stream timeout is a total deadline in seconds covering acquisition, headers and the body, defaulting to the client's timeout. This is stronger than the inactivity timeout of ordinary synchronous HTTPX requests. Cancel the consuming asyncio task to interrupt a blocked read; `asyncio.CancelledError` propagates after cleanup. Exiting `async with`, including after a loop `break`, closes the response and its async HTTP client. Each stream owns these resources. Cancellation cannot undo accepted inference, and an SSE `retry` or `replay` does not repeat the POST. Python 3.9+ is supported; no new runtime dependency is required.

Redirects are refused with `AIStreamError` code `redirect`, so the SDK never forwards the POST to another URL. Connection failures use `connection_error`; HTTP failures retain the usual typed Saturday errors and parsed server details.

Persist the received events if you need an exact record. Stored conversation history is not a guaranteed replay of streamed assistant output.

## Documentation

Full API documentation: [docs.saturday.fit](https://docs.saturday.fit)

## Requirements

- Python 3.9+
- httpx 0.25+

## License

MIT
