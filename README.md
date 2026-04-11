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

# Safety metadata is ALWAYS included — athlete safety is never paywalled
print(prescription["safety"]["warnings"])
print(f"Carbs: {prescription['carb_g_per_hr']} g/hr")
print(f"Sodium: {prescription['sodium_mg_per_hr']} mg/hr")
print(f"Fluid: {prescription['fluid_ml_per_hr']} mL/hr")
```

## Features

- Fully typed with `py.typed` marker (PEP 561)
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
| `client.nutrition` | Calculate prescriptions, batch, compare |
| `client.athletes` | Athlete CRUD, settings, batch create, GDPR export |
| `client.activities` | Activity CRUD, prescription calculation, feedback |
| `client.products` | Product search, barcode lookup, curated list |
| `client.ai` | AI coaching conversations |
| `client.webhooks` | Webhook registration and management |
| `client.organizations` | Team/org management with members |
| `client.gear` | Athlete gear inventory |
| `client.knowledge` | Sports nutrition knowledge base search |

## Documentation

Full API documentation: [docs.saturday.fit](https://docs.saturday.fit)

## Requirements

- Python 3.9+
- httpx 0.25+

## License

MIT
