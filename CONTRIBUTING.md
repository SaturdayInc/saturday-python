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

Update `saturday/` against the current [API documentation](https://docs.saturday.fit/introduction). Add regression coverage in `tests/` for behavior changes. Tests use mocked responses and need no API key.

## Code of conduct

Be kind and constructive.
