# Saturday Python SDK

[![PyPI](https://img.shields.io/pypi/v/saturday)](https://pypi.org/project/saturday/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

The official Python client for the [Saturday API](https://docs.saturday.fit): carbohydrate, sodium and fluid prescriptions for endurance sessions, sized to each athlete, and product fit and prep against them.

## Install

```bash
pip install saturday
```

Python 3.9 or later. One dependency: `httpx`.

## Get a key

A key comes with any paid Saturday plan, member or coach: sign in at [saturday.fit/api](https://saturday.fit/api) to make yours. It is shown once and emailed to you. A new key covers 10 athletes; to cover more, write to [api@saturday.fit](mailto:api@saturday.fit) about what you're building. Platform partners get keys with their agreement.

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

- `precision["missing_fields"]` lists what is still unanswered, most impactful first, with how much each answer would narrow the ranges. `"required": True` marks the safety core; every listed field is needed for exact numbers, `required` or not.
- `precision["missing_profile_fields"]` names the athlete's profile answers still missing: collect them in your UI (`client.onboarding.questions()` gives the questions) or send the athlete to `precision["onboarding"]["url"]`.
- `precision["missing_session_inputs"]` names the session inputs your call left out. Send every session input on every call: `intensity_level`, `thermal_stress_level`, `meal_before_min` and `is_race`. One left out returns ranges even for a complete profile; `precision["onboarding"]` comes only when profile answers are missing.
- Per-hour figures are whole numbers, as the Saturday app's Fuel card shows them, which is not always the total divided by the session's hours. Totals are for the whole session.
- A zero may be omitted from the response, so read numbers with `.get(field, 0)`.
- A new athlete's first calculation, product fit or compare starts a trial of the full tier: 15 calls on the first day, then 5 a day, each fit and compare spending one. `trial_calls_remaining_today` and `trial_ends_at` show where it stands, and `client.partner.get()` gives the trial's length in `rate_limits["trial_days"]` and the exact answers it gives in all in `rate_limits["trial_answers"]`. Past a bound the answer is ranges with a flag and a note you can show the athlete: `trial_cap_reached` (today's calls are used), `trial_start_deferred` (your key has started its new trials for the day), `trial_profile_limit_reached` (the trial covers a set number of distinct profiles) or `trial_answers_used_up` (the trial has given all its exact answers), each with `trial_cap_note` or `trial_note`.

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

    brick_fit = client.nutrition.product_fit(
        athlete_id="ATHLETE_ID",
        product_query="maurten gel 100",
        activity_type="brick",
        meal_before_min=120,
        is_race=False,
        legs=[
            {"activity_type": "bike", "duration_min": 90, "intensity_level": 6, "thermal_stress_level": 6},
            {"activity_type": "run", "duration_min": 30, "intensity_level": 7, "thermal_stress_level": 6},
        ],
    )
    for leg in brick_fit.get("legs", []):
        print(f"{leg['activity_type']}: {leg['fit']['max_servings']} servings")
```

A stored activity uses `type` and `is_race_event`; a calculation uses `activity_type` and `is_race`. The API refuses the other spelling with a `ValidationError` whose `code` is `unsupported_field`.

When the athlete's profile or the session is missing inputs, prep, product fit and compare plan from the middle of the athlete's ranges and say so in `plan_basis`: its `source` is `profile_incomplete`, `session_incomplete` or both, `missing_profile_fields` and `missing_session_inputs` list what is missing, and `onboarding` comes only when profile answers are. A trial past today's calls or its exact answers plans from ranges too, with `source` `trial_allowance`. Show `plan_basis["message"]` with the plan. Product answers follow the athlete's Saturday subscription or trial: without one, `tier` is `"teaser"` and the response carries product categories in place of the fit.

`activities.update` with a change to the session (`type`, `legs`, `duration_min`, effort, heat, `is_race_event` or `meal_before_min`) removes the stored prescription: `get_prescription` raises `NotFoundError` (`prescription_not_found`) until you calculate the activity again. A field sent at its stored value changes nothing.

## Bricks and triathlons

A brick or a triathlon is one session with legs: send it as one call, never one per leg. Each leg carries its own effort and heat; `duration_min` is the legs' total and may be left out.

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

    # One product list per leg; send products= instead to size one list against each leg.
    prep = client.activities.prep("ATHLETE_ID", stored["id"], legs=[
        {"products": []},
        {"products": [{"product_query": "tailwind endurance fuel"}]},
        {"products": [{"product_query": "maurten gel 100", "servings": 2}]},
    ])
    for leg in prep.get("legs", []):
        print(leg["activity_type"], len(leg["products"]), leg["remaining_gap"])
```

- `legs` on an exact answer (calculate, batch, the stored prescription, import) is each leg's share, in order, as the Saturday app's leg cards show it. Answers with ranges carry no leg figures.
- A leg's sport is `activity_type` on a calculation and `type` on an activity, as for a single session.
- `activities.update` with `legs` replaces them; a brick or triathlon refuses a top-level effort or heat. Changing `type` to a single sport drops the legs.
- Prep, product fit and compare answer `legs` too: each leg's share with the products sized against it, as the Saturday app's Prep page for that leg sizes them. Fit and compare also size the whole session at the top level; prep's top level is its legs added up, each product once. A plan from ranges (`plan_basis`) carries no legs.
- `activities.prep` takes `products=`, sized against each leg with its `servings` counting per leg, or `legs=`, one product list per leg in order, never both (a `ValidationError` on `products`). Per-leg lists on a single session, or a count other than the activity's legs, raise a `ValidationError` on `legs`.
- `client.reference.activity_types()` lists the rules under `linked_session_types`.

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
| `client.integrations` | `sync` (intervals.icu), `status`, `disconnect` |
| `client.testing` | `simulate_subscription` (test keys only) |
| `client.meta` | `discovery`, `errors`, `health` |
| `client.knowledge` | `search`, `list_topics`, `get_article` (early access) |
| `client.coach` | Roster reads, alert and report configuration, coach webhooks and billing reads, with a coach key |

Every method returns the API's JSON as plain dictionaries, typed with the TypedDicts in `saturday.types`. Lists keep their array under its name (`athletes`, `activities`) with `pagination["next_cursor"]` to pass back as `cursor`. Batch responses keep request order with failed items left out; match a failure to your input by `errors[i]["index"]`.

Every timestamp a partner key receives is an integer of Unix seconds: on athletes, activities, webhooks and their deliveries, API keys, your account, `trial_ends_at`, the fueling profile's `updated_at`, the export's `exported_at` and every time in its records. Coach routes answer in Unix milliseconds.

`athletes.update_settings` replaces the whole settings object: send every setting you want kept. `athletes.delete` removes the athlete and everything stored under them in your account. `athletes.erase` is for a right-to-erasure request: it first revokes, at the provider, each connection you supplied for the athlete with `integrations.sync`, then deletes the athlete, everything stored under them and their link to a Saturday account. A linked athlete's own Saturday account is not changed. A 503 with code `provider_erasure_incomplete` means nothing was deleted yet: call `erase` again.

`integrations.sync("intervals_icu", ...)` fetches the activities of the intervals.icu user an access token belongs to, a token your intervals.icu app obtained, and stores them under your athlete; it is the only provider sync takes. Send TrainingPeaks workouts with `activities.import_activities` once the athlete agrees to share them. `integrations.disconnect` ends the connection you supplied and keeps the activities already synced; for a provider the athlete never connected it raises `NotFoundError` (`integration_not_found`).

Nutrition and knowledge sit behind [feature gates](https://docs.saturday.fit/guides/feature-gates) that Saturday opens per partner. Until a gate is open for your key, its routes answer `403` with code `feature_alpha` (`PermissionDeniedError`); ask api@saturday.fit to open one.

## Your own athlete ids

`external_id` is unique within your account. A create, batch item or update with an `external_id` another of your athletes holds changes nothing and raises `ConflictError` (409, code `athlete_exists`) whose `athlete_id` names that athlete, so a retried create is safe. `athletes.list(external_id=...)` finds the athlete too.

```python
from saturday import ConflictError, Saturday

with Saturday(api_key="sk_live_...") as client:
    try:
        athlete = client.athletes.create(external_id="user-42", name="Sam")
    except ConflictError as error:
        athlete = client.athletes.get(error.athlete_id)
    print(athlete["id"])
```

## Webhooks

`webhooks.create()` returns the new webhook under `webhook`, with `secret`, the key that signs every delivery. It is returned this once: store it before anything else. `webhooks.test()` delivers a `webhook.test` event at once and returns the delivery record with your endpoint's status code; `webhooks.list_deliveries()` returns the 50 most recent attempts. Webhook and delivery times, and each event's `created_at`, are Unix seconds, as is the signature header's `t`.

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

Every API error is a `SaturdayError` with `status`, `code`, `message`, `param`, `request_id` and `error_type`. Subclasses: `ValidationError` (400, with `suggestion` for a field the request does not take), `AuthenticationError` (401), `PermissionDeniedError` (403: `feature_alpha`; `plan_inactive` when the paid plan a key comes with has ended; `resource_limit_exceeded` when the key's athletes are at their limit), `NotFoundError` (404), `ConflictError` (409, with `athlete_id`), `RateLimitError` (429).

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
| `simulated_subscriber_daily_limit_reached` | Test environment: your key has marked its day's athletes with `testing.simulate_subscription`; athletes already marked keep their simulated subscription | Same |

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

Partner keys start `sk_live_` or `sk_test_`; coach keys start `cp_live_` or `cp_test_`. A test key reaches the test environment, where `client.testing.simulate_subscription(athlete_id)` gives an athlete the full tier: by default up to 10 athletes a key a UTC day, each with up to 100 exact answers over 3 distinct profiles, then ranges with `simulated_limit_reached`. The client holds a connection pool: use it as a context manager or call `close()`.

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
