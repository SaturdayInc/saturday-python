# Contributing

## Bug reports

File an issue on this repository with:
- SDK version
- Python version
- Minimal reproduction steps
- Expected and actual behavior

## Development

Install the package and test dependencies in a virtual environment, then run the tests:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest
```

Every pull request runs the tests and the mypy check in `tests/fixtures/README.md` (`.github/workflows/test.yml`).

Update `saturday/` against the current [API documentation](https://docs.saturday.fit/introduction) and add coverage in `tests/` for behavior changes. `python -m pytest` uses mocked responses and recorded API responses and needs no API key. The live suite runs every method against a real API with a test key: see [tests/LIVE.md](tests/LIVE.md). After a change to the API, run it with `SATURDAY_LIVE_CAPTURE=tests/fixtures/live.json` and commit the new recording with the type changes.

## Code of conduct

Be kind and constructive.
