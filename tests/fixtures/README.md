# Contract fixtures

`contracts.json` holds sample API responses that fuel-backend builds (`pkg/sdkcontracts`) from its Go response types and its real stored-prescription, list and settings handlers, with synthetic data and in-memory services. It makes no API, Firestore, inference, auth, or trial calls. `_meta.backend_sha` is the backend commit that last changed the samples.

The backend fails a test when its copy of the samples no longer matches what its types and handlers produce. Once the regenerated samples are on the backend's main, `scripts/sdk-contracts-sync.sh --pr` in fuel-backend opens a pull request here carrying them, and the test run on that pull request shows whether the SDK types still match. Fix the types on that branch when it fails.

`tests/test_contracts.py` checks payloads against TypedDict required/optional keys and value types, then exercises methods using mocked HTTP. Static examples are checked with `python -m mypy saturday tests/typecheck --check-untyped-defs --warn-unused-ignores`. This is local source-contract evidence, not a live deployed-API smoke test.
