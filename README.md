# Saturday Python SDK

[![PyPI](https://img.shields.io/pypi/v/saturday)](https://pypi.org/project/saturday/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Official Python SDK for the [Saturday Nutrition Intelligence API](https://docs.saturday.fit).

Personalized fuel, hydration, and electrolyte prescriptions for endurance athletes.

## Install

```bash
pip install saturday
```

## Quick start

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

Teaser-tier responses and incomplete profiles return ranges rather than exact numbers, and the `full` tier alone does not guarantee exact values. A zero value may be omitted from the response, so the example prints `0` for it. See [Athlete Onboarding](https://docs.saturday.fit/guides/onboarding).

## Features

- Type hints with a `py.typed` marker (PEP 561); resource responses are dictionaries
- Automatic retry on `429` and `5xx` responses: up to 3 retries, with 1 s, 2 s, and 4 s backoff
- Typed errors: `AuthenticationError`, `RateLimitError`, `ValidationError`, `NotFoundError`
- API key and OAuth2 Bearer token authentication
- Context manager and `close()` for connection cleanup
- `safety` object with `not_instructions` on every prescription

## Configuration

```python
from saturday import Saturday

client = Saturday(
    api_key="sk_test_...",
    base_url="https://api.saturday.fit",  # default
    timeout=30.0,  # seconds, per connect, read, and write; default 30
    max_retries=3,  # default; 0 disables retries
)
client.close()
```

## Authentication

```python
# Partner API key (server-to-server)
client = Saturday(api_key="sk_live_...")

# OAuth2 Bearer token (athlete-delegated access); it takes precedence over the API key
client = Saturday(api_key="sk_live_...", bearer_token="eyJ...")

# Coach API key, for the coach resource
client = Saturday(api_key="cp_live_...")

# Context manager for automatic cleanup
with Saturday(api_key="sk_live_...") as client:
    rx = client.nutrition.calculate(activity_type="run", duration_min=60)
```

Partner keys carry the `sk_live_` or `sk_test_` prefix; coach keys carry `cp_live_` or `cp_test_`.

## Error handling

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

`retry_after` is the server's `Retry-After` value in seconds, or 60 when the response carries none.

## Resources

| Resource | Description |
|----------|-------------|
| `client.nutrition` | Calculate prescriptions, batch calculate |
| `client.athletes` | Athlete CRUD, settings, batch create, GDPR data export |
| `client.activities` | Activity CRUD, prescription calculation, feedback |
| `client.products` | Product search, barcode lookup, curated list, categories |
| `client.ai` | Conversation metadata, history, listing, and deletion; see AI conversations below |
| `client.webhooks` | Webhook registration and management |
| `client.organizations` | Team and organization management with members |
| `client.gear` | Athlete gear inventory |
| `client.knowledge` | Sports nutrition knowledge base search |
| `client.onboarding` | The versioned onboarding question schema, for collecting an athlete's profile in your UI |
| `client.coach` | Roster fueling reads and the coach's alert and report configuration, with a coach key |

## AI conversations

`POST /v1/ai/conversations` and `POST /v1/ai/conversations/{conversation_id}/messages` answer with a server-sent event (SSE) stream. Call them over HTTP directly; the SDK's `ai` resource covers the JSON reads: conversation metadata, message history, listing, and deletion.

For a partner with AI access enabled, this request starts a conversation and prints the complete event stream, including safety warnings and errors:

```bash
curl --no-buffer --fail-with-body https://api.saturday.fit/v1/ai/conversations \
  -H "Authorization: Bearer $SATURDAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"athlete_id":"YOUR_ATHLETE_ID","message":"Help me review my fueling plan"}'
```

The first `message_start` event supplies `conversation_id`. Send later messages to `POST /v1/ai/conversations/{conversation_id}/messages` with a `message` field and read the same SSE format. Do not parse a successful stream as JSON, and do not discard `safety_warning` and `error` events.

## Documentation

Full API reference: [docs.saturday.fit](https://docs.saturday.fit)

## Requirements

- Python 3.9+
- httpx 0.25+

## License

MIT
