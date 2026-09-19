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
- Automatic retry with exponential backoff (429s and 5xx)
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
| `client.ai` | Conversation metadata and history; see AI writes below |
| `client.webhooks` | Webhook registration and management |
| `client.organizations` | Team/org management with members |
| `client.gear` | Athlete gear inventory |
| `client.knowledge` | Sports nutrition knowledge base search |

## AI writes

`ai.create_conversation()` and `ai.send_message()` currently do not support the API's server-sent event (SSE) responses. Conversation creation also uses an outdated request field. Use direct HTTP for these two operations while [streaming support is being aligned](https://github.com/SaturdayInc/saturday-node/issues/12). The metadata and history read methods use JSON.

For a partner with AI access enabled, this request starts a conversation and prints the complete event stream, including safety warnings and errors:

```bash
curl --no-buffer --fail-with-body https://api.saturday.fit/v1/ai/conversations \
  -H "Authorization: Bearer $SATURDAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"athlete_id":"YOUR_ATHLETE_ID","message":"Help me review my fueling plan"}'
```

The first `message_start` event supplies `conversation_id`. Send subsequent messages to `POST /v1/ai/conversations/{conversation_id}/messages` with a `message` field and consume the same SSE format. Do not parse a successful stream as JSON or discard `safety_warning` and `error` events.

## Documentation

Full API documentation: [docs.saturday.fit](https://docs.saturday.fit)

## Requirements

- Python 3.9+
- httpx 0.25+

## License

MIT
