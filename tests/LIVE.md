# Live suite

`tests/test_live.py` calls every partner method against a running Saturday API and checks what comes back. `python -m pytest` skips it unless both variables below are set.

```bash
SATURDAY_LIVE_BASE_URL=https://... \
SATURDAY_LIVE_API_KEY=sk_test_... \
python -m pytest tests/test_live.py
```

- The key must be a test key (`sk_test_`); the suite refuses a live key.
- One run makes about 65 calls, of which about 15 are calculations, and creates 3 athletes, 2 activities, an organization, an API key and a webhook pointed at `https://example.com`. It erases the athletes and deletes the activity, key and webhook it created; the organization stays.
- The catalog products it sizes are Maurten Gel 100 and Tailwind Endurance Fuel.
- `athletes.erase` and `testing.simulate_subscription` need the test environment.

Set `SATURDAY_LIVE_CAPTURE=tests/fixtures/live.json` to record every response. Keys, secrets, signed links and account details are replaced with placeholders before they are written. `tests/test_live_types.py`, part of the normal test run, checks every recorded response against the TypedDict its method returns: every required key, no undeclared key, every value of its declared type, so a field the API adds, drops or renames fails the suite until the types match.
