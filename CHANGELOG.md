# Changelog

## Unreleased

- Add async context-managed `ai.create_conversation_stream` and `ai.send_message_stream` for the existing SSE API. Preserve warnings, errors and unknown events; provide total deadlines, asyncio cancellation and early-exit cleanup. AI writes never automatically retry.
- Compatibility: legacy synchronous `ai.create_conversation` and `ai.send_message` now raise `streaming_required` before sending any request. Migrate to `async with` / `async for`. Existing JSON read methods stay synchronous and unchanged. No metadata/timestamps are fabricated. Source change only, not a package publication.

## 0.6.0

- `reports.pdf` returns the PDF bytes and raises the SDK's own error types (`NotFoundError` and siblings) on failure, through the same handler as every other call. Previously it raised `httpx.HTTPStatusError`. Callers catching that exception around a report download need to catch the SDK errors instead.
- Rate-limit errors expose the server's `Retry-After` value; the daily ceiling sends none, in which case the value reported is a fallback, not the true wait.

## 0.5.0

Initial public release.
