# Saturday Python SDK

[![PyPI](https://img.shields.io/pypi/v/saturday)](https://pypi.org/project/saturday/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

The official Python client for the [Saturday API](https://docs.saturday.fit): carbohydrate, sodium and fluid prescriptions for endurance sessions, sized to each athlete, and product fit and prep against them.

## Install

```bash
pip install saturday
```

Python 3.9 or later. One dependency: `httpx`.

## Quick start

Create an athlete with a complete profile, then calculate a session for them. Use an `sk_test_` key while you build.

```python
import os

from saturday import Saturday

client = Saturday(api_key=os.environ["SATURDAY_API_KEY"])

athlete = client.athletes.create(
    external_id="user-42",
    sex="female",
    year_of_birth=1990,
    weight_kg=62,
    settings={
        "sweat_level": 5,
        "saltiness": 5,
        "satiety_level": 5,
        "fitness_level": 5,
        "carb_experience": "range_40_60",
        "usual_carb_consumption": "range_60_80",
        "concerns_answered": True,
    },
)

plan = client.nutrition.calculate(
    athlete_id=athlete["id"],
    activity_type="bike",
    duration_min=180,
    intensity_level=5,
    thermal_stress_level=7,
    meal_before_min=120,
    is_race=False,
)

if plan.get("precision", {}).get("profile_complete"):
    print(f"Carbs: {plan.get('carb_g_per_hr', 0)} g/hr")
    print(f"Sodium: {plan.get('sodium_mg_per_hr', 0)} mg/hr")
    print(f"Fluid: {plan.get('fluid_ml_per_hr', 0)} mL/hr")
else:
    print(f"Carbs: {plan['carb_range_g_per_hr']} g/hr")
    print(f"Sodium: {plan['sodium_range_mg_per_hr']} mg/hr")
    print(f"Fluid: {plan['fluid_range_ml_per_hr']} mL/hr")
for warning in plan["safety"]["warnings"] or []:
    print(warning)
client.close()
```

Show `plan["attribution"]` wherever you show the numbers, and show every safety warning.

## Exact numbers and ranges

A calculation carries exact per-hour numbers and totals only when the athlete's profile is complete and their tier is full; otherwise it carries ranges such as `"60-80"`. `precision["profile_complete"]` tells you which. `tier == "full"` alone does not mean exact.

- `precision["missing_fields"]` lists what is still unanswered, most impactful first, with how much each answer would narrow the ranges. Collect those answers in your UI (`client.onboarding.questions()` gives the questions) or send the athlete to `precision["onboarding"]["url"]`.
- Send every session input on every call: `intensity_level`, `thermal_stress_level`, `meal_before_min` and `is_race`. One left out returns ranges even for a complete profile, and `precision["message"]` names it apart from the profile answers the athlete still owes; `precision["onboarding"]` comes only with the latter.
- Per-hour figures are whole numbers. For a fasted start (`meal_before_min` over 180) the totals include a 20-minute pre-load, and the per-hour figures spread the totals over the session plus those 20 minutes.
- A zero may be omitted from the response, so read numbers with `.get(field, 0)`.
- A new athlete's first calculation starts a 30-day trial of the full tier: 15 calls on the first day, then 5 a day. `trial_calls_remaining_today` and `trial_ends_at` show where it stands.

## Prep and product fit

Store a session, calculate it, then size the products the athlete plans to carry against it.

```python
from saturday import Saturday

with Saturday(api_key="sk_test_...") as client:
    ride = client.activities.create(
        "ATHLETE_ID",
        type="bike",
        duration_min=150,
        intensity_level=6,
        thermal_stress_level=6,
        meal_before_min=120,
        is_race_event=False,
    )
    client.activities.calculate_prescription("ATHLETE_ID", ride["id"])

    prep = client.activities.prep("ATHLETE_ID", ride["id"], products=[
        {"product_query": "maurten gel 100", "servings": 2},
        {"product_query": "tailwind endurance fuel"},
    ])
    for product in prep["products"]:
        print(f"{product['servings']} x {product['product_name']}")
    print("Still needed:", prep["remaining_gap"])

    fit = client.nutrition.product_fit(
        athlete_id="ATHLETE_ID",
        product_query="maurten gel 100",
        activity_type="run",
        duration_min=90,
        intensity_level=7,
        thermal_stress_level=5,
        meal_before_min=120,
        is_race=True,
    )
    if fit["tier"] == "full":
        print(fit["fit"]["verdict"])
```

A stored activity uses `type` and `is_race_event`; a calculation uses `activity_type` and `is_race`. The API refuses the other spelling with a `ValidationError` whose `code` is `unsupported_field`.

When the athlete's profile or the session is missing inputs, prep, product fit and compare plan from the middle of the athlete's ranges and say so in `plan_basis`: its `source` is `profile_incomplete`, `session_incomplete` or both, `missing_profile_fields` and `missing_session_inputs` list what is missing, and `onboarding` comes only when profile answers are. Show `plan_basis["message"]` with the plan. Product answers follow the athlete's Saturday subscription or trial: without one, `tier` is `"teaser"` and the response carries product categories in place of the fit.

## Bricks and triathlons

A brick or a triathlon is one session with legs, calculated as the Saturday app does it, as one continuous effort: send it as one call, never one per leg. Each leg carries its own effort and heat; `duration_min` is the legs' total and may be left out.

```python
from saturday import Saturday

with Saturday(api_key="sk_test_...") as client:
    brick = client.nutrition.calculate(
        athlete_id="ATHLETE_ID",
        activity_type="brick",
        meal_before_min=120,
        is_race=False,
        legs=[
            {"activity_type": "bike", "duration_min": 90, "intensity_level": 6, "thermal_stress_level": 6},
            {"activity_type": "run", "duration_min": 30, "intensity_level": 7, "thermal_stress_level": 6},
        ],
    )
    for leg in brick.get("legs", []):
        print(f"{leg['duration_min']} min: {leg['total_carb_g']} g carbs")

    stored = client.activities.create(
        "ATHLETE_ID",
        type="triathlon",
        meal_before_min=240,
        is_race_event=True,
        legs=[
            {"type": "swim", "duration_min": 30, "intensity_level": 7, "thermal_stress_level": 3},
            {"type": "bike", "duration_min": 80, "intensity_level": 7, "thermal_stress_level": 6},
            {"type": "run", "duration_min": 40, "intensity_level": 7, "thermal_stress_level": 7},
        ],
    )
    calculated = client.activities.calculate_prescription("ATHLETE_ID", stored["id"])
    print(calculated.get("prescription", {}).get("legs"))
```

- `legs` on an exact answer (calculate, batch, the stored prescription, import) is each leg's share, in order, as the Saturday app's leg cards show it. Answers with ranges carry no leg figures.
- A leg's sport is `activity_type` on a calculation and `type` on an activity, as for a single session.
- `activities.update` with `legs` replaces them; a brick or triathlon refuses a top-level effort or heat. Changing `type` to a single sport drops the legs.
- `client.reference.activity_types()` lists the rules under `linked_session_types`. Product fit and compare size for a single sport; prep sizes a stored brick or triathlon as one session.

## Resources

| Resource | Methods |
|----------|---------|
| `client.nutrition` | `calculate`, `batch_calculate`, `product_fit`, `compare_products`, `extract` |
| `client.athletes` | `create`, `get`, `list`, `update`, `delete`, `get_settings`, `update_settings`, `get_fueling_profile`, `batch_create`, `export`, `erase`, `list_consent`, `record_consent`, `revoke_consent` |
| `client.activities` | `create`, `get`, `list`, `update`, `delete`, `calculate_prescription`, `get_prescription`, `prep`, `import_activities`, `submit_feedback` |
| `client.onboarding` | `questions` |
| `client.reference` | `activity_types`, `settings_schema` |
| `client.infer` | `activity_type`, `brick_types` |
| `client.partner` | `get`, `usage`, `usage_daily`, `list_api_keys`, `create_api_key`, `revoke_api_key`, `rotate_api_key` |
| `client.webhooks` | `create`, `list`, `get`, `update`, `delete`, `test`, `list_deliveries` |
| `client.organizations` | `create`, `list`, `get`, `update`, `add_member`, `list_members`, `remove_member`, `set_offer`, `get_offer`, `delete_offer`, `create_subscription`, `list_subscriptions`, `update_subscription`, `add_licenses`, `list_licenses`, `remove_license` |
| `client.integrations` | `sync`, `status`, `disconnect` |
| `client.testing` | `simulate_subscription` (test keys only) |
| `client.meta` | `discovery`, `errors`, `health` |
| `client.knowledge` | `search`, `list_topics`, `get_article` (early access) |
| `client.coach` | Roster reads, alert and report configuration, coach webhooks and billing reads, with a coach key |

Every method returns the API's JSON as plain dictionaries, typed with the TypedDicts in `saturday.types`. Lists keep their array under its name (`athletes`, `activities`) with `pagination["next_cursor"]` to pass back as `cursor`. Batch responses keep request order with failed items left out; match a failure to your input by `errors[i]["index"]`.

`athletes.update_settings` replaces the whole settings object: send every setting you want kept. `athletes.delete` removes the athlete and everything stored under them in your account. `athletes.erase` is for a right-to-erasure request: it also ends the athlete's connected-provider grants, erases what those providers sent, and keeps an audit record of the deletion.

Nutrition and knowledge sit behind [feature gates](https://docs.saturday.fit/guides/feature-gates) that Saturday opens per partner. Until a gate is open for your key, its routes answer `403` with code `feature_alpha` (`PermissionDeniedError`); ask api@saturday.fit to open one.

## Finding an athlete by your own id

`athletes.list(external_id=...)` returns the athletes you created with that `external_id`, newest first, in one page. The API does not deduplicate `external_id`, so look an athlete up this way before creating one when a create may have been interrupted.

```python
from saturday import Saturday

with Saturday(api_key="sk_live_...") as client:
    found = client.athletes.list(external_id="user-42")["athletes"]
    athlete = found[0] if found else client.athletes.create(external_id="user-42", name="Sam")
    print(athlete["id"])
```

## Webhooks

`webhooks.create()` returns the new webhook under `webhook`, with `secret`, the key that signs every delivery. It is returned this once: store it before anything else. `webhooks.test()` delivers a `webhook.test` event at once and returns the delivery record with your endpoint's status code; `webhooks.list_deliveries()` returns the 50 most recent attempts. Webhook timestamps are Unix milliseconds.

```python
from saturday import Saturday

with Saturday(api_key="sk_live_...") as client:
    created = client.webhooks.create("https://example.com/saturday", ["athlete.created", "prescription.calculated"])
    signing_secret = created["webhook"]["secret"]  # store it now
    delivery = client.webhooks.test(created["webhook"]["id"])["delivery"]
    print(delivery["status"], delivery["status_code"])
```

See [Webhooks](https://docs.saturday.fit/guides/webhooks) for verifying signatures.

## Coach alert rules

`coach.set_notification_rules()` replaces the whole rule set at a scope, `channel_config` included. Read the rules first and send them back with your change: a set without `channel_config` clears it at that scope, and at the overall scope that turns the coach's email and push alerts off.

```python
from saturday import Saturday

with Saturday(api_key="cp_live_...") as client:
    rules = client.coach.get_notification_rules(scope="overall")
    client.coach.set_notification_rules("overall", {**rules, "hourly_cap": {"enabled": True, "per_hour": 2}})
```

## Errors, retries and limits

Every API error is a `SaturdayError` with `status`, `code`, `message`, `param`, `request_id` and `error_type`. Subclasses: `ValidationError` (400, with `suggestion` for a field the request does not take), `AuthenticationError` (401), `PermissionDeniedError` (403), `NotFoundError` (404), `RateLimitError` (429).

```python
from saturday import RateLimitError, Saturday, ValidationError

with Saturday(api_key="sk_test_...") as client:
    try:
        client.nutrition.calculate(activity_type="run", duration_min=60)
    except RateLimitError as error:
        if error.daily_limit:
            print(f"{error.code}: resets at {error.resets_at.isoformat()}")
        else:
            print(f"{error.code}: try again in {error.retry_after} s")
    except ValidationError as error:
        if error.code == "unsupported_field":
            print(f"{error.param} is not a field of this request; send {error.suggestion or 'the documented fields'}")
        else:
            print(f"Fix {error.param}: {error}")
```

A `RateLimitError`'s `code` says which limit was hit:

| `code` | What it means | What the client does |
|--------|---------------|----------------------|
| `rate_limit_exceeded` | Short-term throttle | Waits `retry_after` seconds and retries |
| `catalog_paced` | New products are paced after a large share of the catalog in 24 hours; products already answered keep working | Retries a wait of 30 seconds or less; raises a longer one to you |
| `rate_limited` | Calculations blocked after an unusual request pattern, for `retry_after` seconds | Raises it to you |
| `daily_call_limit_reached` | Your daily call ceiling | Raises it to you, with `daily_limit` True and `resets_at` (UTC midnight) |
| `intelligence_daily_limit_reached` | Your daily ceiling on calculations, products, inference, knowledge and AI; your athletes, activities and other data keep working | Same |
| `athlete_free_daily_limit_reached` | Your daily budget of calculations sent without an `athlete_id` | Same |
| `distinct_lookup_daily_limit_reached` | Your daily budget of distinct product lookups; repeat lookups keep working | Same |

A 5xx is retried after its `Retry-After` (usually 5 seconds) or after 1 s, 2 s and 4 s, up to `max_retries` times, except on a `POST` that creates or changes a record (an athlete, an activity, an import, a webhook), since the server may have done the write; the calculation, product, inference, prep and export `POST`s are retried. The client never sleeps longer than 30 seconds inside one call. `client.partner.get()` shows your limits and `client.partner.usage()` what you have used.

## Configuration

```python
from saturday import Saturday

client = Saturday(
    api_key="sk_test_...",
    base_url="https://api.saturday.fit",  # default
    timeout=30.0,  # seconds
    max_retries=3,  # 0 disables retries
)

# An athlete's OAuth2 access token, sent in place of the API key
delegated = Saturday(api_key="sk_live_...", bearer_token="eyJ...")
```

Partner keys start `sk_live_` or `sk_test_`; coach keys start `cp_live_` or `cp_test_`. A test key reaches the test environment, where `client.testing.simulate_subscription(athlete_id)` gives an athlete the full tier. The client holds a connection pool: use it as a context manager or call `close()`.

## Athlete profile sharing

An athlete who connects their Saturday account to your athlete record can share their Saturday app answers with you. `athletes.get_fueling_profile(athlete_id)` returns a `FuelingProfile`; check `sharing` first. Only `"on"` carries `profile`; `"off"` and `"not_linked"` carry a `message`.

```python
from saturday import FuelingProfile, Saturday

with Saturday(api_key="sk_live_...") as client:
    fueling: FuelingProfile = client.athletes.get_fueling_profile("ath_123")
    if fueling["sharing"] == "on":
        sweat = fueling["profile"]["sweat_level"]
        answered = "not answered" if sweat["value"] is None else sweat["value"]
        print(f"Sweat level {answered}; calculations use {sweat['calculations_use']}")
    else:
        print(fueling["message"])
```

`value` is `None` when the athlete has not answered that question in the app. `calculations_use` says where the value Saturday's calculations use comes from: `partner` (yours), `saturday_app`, or `default`. The two sharing webhooks, typed as `ProfileSharingChangedEvent` and `FuelingProfileUpdatedEvent`, carry the athlete record with `profile_sharing` (the second adds `changed_fields`). Guide: [Reading an athlete's fueling profile](https://docs.saturday.fit/guides/fueling-profile).

## Tests

`python -m pytest` runs the unit tests with mocked HTTP. `tests/test_live.py` runs every partner method against a real API with a test key; [tests/LIVE.md](tests/LIVE.md) says how.

## Documentation

[docs.saturday.fit](https://docs.saturday.fit)

## License

MIT
