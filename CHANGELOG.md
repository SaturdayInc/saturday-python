# Changelog

## Unreleased

- Add standard-library TypedDict models for nutrition, activity prescriptions, feedback, and batch responses. Values remain ordinary dictionaries; no runtime model dependency or validation is added.
- Describe nullable warnings, numeric timestamps, trial metadata, full-tier ranges, and separate indexed batch errors accurately. Static type checking may now flag access to nonexistent fields.
- Add `activities.import_activities`, with calculation opt-in. No package version bump in this change.

## 0.6.0

- `coach.report_pdf` returns the PDF bytes and raises the SDK's own error types (`NotFoundError` and siblings) on failure, through the same handler as every other call. Previously it raised `httpx.HTTPStatusError`. Callers catching that exception around a report download need to catch the SDK errors instead.
- Rate-limit errors expose the server's `Retry-After` value; the daily ceiling sends none, in which case the value reported is a fallback, not the true wait.

## 0.5.0

Initial public release.
