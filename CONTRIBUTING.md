# Contributing

Thank you for your interest in contributing to the Saturday SDK.

## Bug Reports

Please file an issue on this repository with:
- SDK version
- Language/runtime version
- Minimal reproduction steps
- Expected vs actual behavior

## Development

Install the package and test dependencies in a virtual environment, then run the isolated HTTP tests:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest
```

Update `saturday/` against the current [API documentation](https://docs.saturday.fit/introduction). Add regression coverage in `tests/` for behavior changes. Tests use mocked responses and do not require an API key.

## Code of Conduct

Be kind. Be constructive. We're building tools that help athletes stay safe.
