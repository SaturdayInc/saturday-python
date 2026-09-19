# Contract fixtures

`contracts.json` is generated from fuel-backend's Go JSON types and its real stored-prescription, list and settings handlers, using synthetic data and in-memory services. It makes no API, Firestore, inference, auth, or trial calls. The backend commit is recorded in `_meta`.

Regenerate from a checked-out backend module, with Go 1.26+:

```bash
cd /path/to/fuel-backend
go run /path/to/saturday-python/tests/fixtures/generate.go \
  -backend-sha "$(git rev-parse HEAD)" \
  -out /path/to/saturday-python/tests/fixtures/contracts.json
```

Review generated differences before accepting them. `tests/test_contracts.py` checks payloads against TypedDict required/optional keys and value types, then exercises methods using mocked HTTP. Static examples are checked with `python -m mypy saturday tests/typecheck --check-untyped-defs --warn-unused-ignores`. This is local source-contract evidence, not a live deployed-API smoke test.
