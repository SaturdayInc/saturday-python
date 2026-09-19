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

- TypedDict responses with a `py.typed` marker (PEP 561); values stay ordinary dictionaries
- Automatic retry on `429` and `5xx` responses for JSON operations: up to 3 retries, with 1 s, 2 s, and 4 s backoff. AI stream writes are never replayed
- Typed errors: `AuthenticationError`, `RateLimitError`, `ValidationError`, `NotFoundError`, `AIStreamError`
- API key and OAuth2 Bearer token authentication
- Context manager and `close()` for connection cleanup
- `safety` object with `not_instructions` on every prescription

## Configuration

```python
from saturday import Saturday

client = Saturday(
    api_key="sk_test_...",
    base_url="https://api.saturday.fit",  # default
    timeout=30.0,  # seconds, per connect, read, and write on JSON requests; default 30
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
| `client.activities` | Activity CRUD, prescription calculation, import, feedback |
| `client.products` | Product search, barcode lookup, curated list, categories |
| `client.ai` | Async AI event streams, plus synchronous JSON conversation metadata, history, listing, and deletion; see AI writes below |
| `client.webhooks` | Webhook registration and management |
| `client.organizations` | Team and organization management with members |
| `client.gear` | Athlete gear inventory |
| `client.knowledge` | Sports nutrition knowledge base search |
| `client.onboarding` | The versioned onboarding question schema, for collecting an athlete's profile in your UI |
| `client.coach` | Roster fueling reads, the coach's alert and report configuration, coach webhooks, and read-only billing (`seat_state`, `ledger`, `tier_status`, `connect_summary`, `connect_earnings`, `connect_transactions`, `connect_arrangements`; the key must carry `billing:read`), with a coach key |

## Prescription and batch responses

The exported types in `saturday.types` describe the existing wire dictionaries; they do not validate, filter, or convert responses. `nutrition.calculate()` returns flat nutrition fields. `activities.calculate_prescription()` returns a `PrescriptionEnvelope`: full-tier results are under `prescription`, while teaser ranges are at the top level. Full-tier prescriptions can also contain ranges when inputs are incomplete.

`activities.get_prescription()` returns `{ "prescription": ..., "safety": ... }`, with no `tier` field. Activity timestamps, including `calculated_at`, use epoch seconds; `trial_ends_at` uses epoch milliseconds. Safety warnings may be `None`.

```python
from saturday import Saturday, StoredPrescriptionResponse

with Saturday(api_key="sk_live_...") as client:
    stored: StoredPrescriptionResponse = client.activities.get_prescription("ath_123", "act_123")
    prescription = stored["prescription"]
    carbs = prescription.get("carb_range_g_per_hr", prescription["carb_g_per_hr"])
    print(f"Carbs: {carbs} g/hr")
    for warning in stored["safety"]["warnings"] or []:
        print(warning)
```

Batch calculations return flat `results[]`, not indexed prescription wrappers. Athlete batches return `created[]`. Success arrays preserve input order with failed items omitted; `errors[]` contains each failed item's original `index`, `code`, and `message`.

`activities.import_activities(athlete_id, activities, calculate=True)` creates activities and optionally calculates prescriptions. Omit `calculate` to avoid global calculation; individual activities may explicitly set `calculate=True`. A global `False` does not override a per-activity `True`. Calculation outcomes appear in `prescriptions[]`; a failed calculation does not undo an imported activity. Each batch/import item counts toward the applicable quota; requested calculations may also consume trial calls.

Static type checking may now flag access to fields the server never returned. TypedDict values also cannot be passed directly to helpers annotated `Dict[str, Any]`: use `Mapping[str, object]` for read-only helpers, or `dict(response)` when you intentionally need a mutable dictionary copy. Dictionary indexing and existing runtime values are unchanged.

Athlete and activity list responses keep the resource array under `athletes` or `activities`. Pagination is nested: check `page["pagination"]["has_more"]` and pass `page["pagination"].get("next_cursor")` as the next request's `cursor` argument. `page["pagination"]["total"]` counts records on that page, not the entire collection.

The legacy athlete-list `search` argument is currently ignored by the backend. It remains accepted for source compatibility, but does not filter results.

Athlete settings use flat concern flags, such as `sweat_level=5, gut_distress=True`, not a nested `concerns` object. `athletes.update_settings()` replaces the complete settings for a partner-managed athlete; omitted settings reset. Send the complete intended settings, including values you want to preserve. The SDK does not fetch or merge settings implicitly.

## AI writes

Use `ai.create_conversation_stream(athlete_id, message)` and `ai.send_message_stream(conversation_id, message)` with `async with`, then `async for`. These additive methods are asynchronous, even though the existing JSON SDK methods remain synchronous. Events are dictionaries with `event`, `data`, `raw_data` and optional `id`, preserving unknown event names and JSON fields. `id` is present only when the server sent an SSE `id:` line for that event; the server sends none today.

Compatibility change: the legacy `ai.create_conversation()` and `ai.send_message()` methods now raise `AIStreamError` with code `streaming_required` locally, before any HTTP request. Migrate to the stream methods. The server never returned their promised JSON objects; the SDK does not invent metadata or timestamps to imitate them.

```python
import asyncio
from saturday import Saturday, AIStreamError

async def main():
    with Saturday(api_key="sk_live_...") as client:
        try:
            async with client.ai.create_conversation_stream(
                "YOUR_ATHLETE_ID", "Help me review my fueling plan", timeout=60.0
            ) as events:
                async for event in events:
                    # Keep warnings, errors and unknown events, not only text.
                    print(event["event"], event["data"])
        except AIStreamError as error:
            print(error.code, error.event)
            raise  # No automatic retry: the server may have accepted the write.

asyncio.run(main())
```

The `message_start` event supplies `data["conversation_id"]`. Current names include `text_delta`, `safety_warning`, `error`, `tool_call`, `tool_result`, `action`, `replay` and `message_end`. `message_end` is not a success verdict: server error events are yielded, then iteration raises `stream_error` after the response finishes. Warnings, including generation-halted safety warnings, must remain visible even if no exception is raised.

AI stream writes never automatically retry, including HTTP 429/5xx, connection errors, malformed JSON/UTF-8 (`malformed_stream`), cancellation and premature EOF (`incomplete_stream`). `max_retries` does not apply. Preserve received events as partial output, not a complete answer. Inspect conversation state before deliberately submitting another message; these writes have no idempotency key.

The stream timeout is a total deadline in seconds covering acquisition, headers and the body. It defaults to the client `timeout` when one is configured, else 60 s: a turn with tool calls can run up to the API's 60 s request cap. This is stronger than the inactivity timeout of ordinary synchronous HTTPX requests. Cancel the consuming asyncio task to interrupt a blocked read; `asyncio.CancelledError` propagates after cleanup. Exiting `async with`, including after a loop `break`, closes the response and its async HTTP client. Each stream owns these resources. Cancellation cannot undo accepted inference, and an SSE `retry` or `replay` does not repeat the POST.

Redirects are refused with `AIStreamError` code `redirect`, so the SDK never forwards the POST to another URL. Connection failures use `connection_error`; HTTP failures retain the usual typed Saturday errors and parsed server details.

Persist the received events if you need an exact record. Stored conversation history is not a guaranteed replay of streamed assistant output.

## Documentation

Full API reference: [docs.saturday.fit](https://docs.saturday.fit)

## Requirements

- Python 3.9+
- httpx 0.25+

## License

MIT
