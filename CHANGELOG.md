# Changelog

## Unreleased

- Add `athletes.get_fueling_profile(athlete_id)` for `GET /v1/athletes/{id}/fueling-profile`: the athlete's Saturday app answers while they share them with you, typed as `FuelingProfile`. `profile` (`FuelingProfileAnswers`, each answer with `value` and `calculations_use`) and `updated_at` are present only when `sharing` is `"on"`; `"off"` and `"not_linked"` carry `message`. `Athlete` gains the optional `profile_sharing` (`ProfileSharing`: `on`, `off` or `not_linked`), returned by `athletes.get`.
- Add webhook body types: `WebhookEvent`, `WebhookEventType` (the names registration accepts), and `ProfileSharingChangedEvent` and `FuelingProfileUpdatedEvent` for `athlete.profile_sharing_changed` and `athlete.fueling_profile_updated`, whose data is the athlete record (the second adds `changed_fields`, typed `FuelingProfileFieldName`).
- `set_notification_rules` documents `hourly_cap` (`enabled`, `per_hour` 1 to 12), the limit on the emails, and separately the pushes, one athlete's alerts send the coach in any 60 minutes. With no scope setting it, the cap is on at 1 per hour; leaving it out of the rules clears it at that scope.
- `CoachConnectCharge` gains the optional `stripe_fee_paid_by` (`coach` or `saturday`) and `platform_fee_returned_cents` the transactions endpoint returns. `CoachChargeBreakdown` gains `stripe_fee_paid_by`, `refunded_cents`, `platform_fee_returned_cents`, `disputes_cents` and `dispute_costs_recovered_cents`, and `CoachEarningsSummary` their `total_` sums, which the earnings endpoint returns. `CoachConnectSummary` gains the fee terms the summary endpoint returns: `platform_fee_minimum_cents`, `coach_pays_stripe_fees_from` and Stripe's rates (`stripe_fee_domestic_bps`, `stripe_fee_international_bps`, `stripe_fee_fixed_cents`).
- `CoachSeatState` gains `pending_coach_paid_count`: coach-paid athletes whose seat starts billing when the time they paid for on their own Monthly plan runs out. They are not in `coach_paid_count` until then.

## 0.7.0

- Add the read-only coach billing reads: `coach.seat_state`, `coach.ledger`, `coach.tier_status`, `coach.connect_summary`, `coach.connect_earnings`, `coach.connect_transactions` and `coach.connect_arrangements`, typed as TypedDicts (`CoachSeatState`, `CoachLedgerPage`, `CoachTierStatus`, `CoachConnectSummary`, `CoachConnectEarnings`, `CoachConnectChargesPage`, `CoachConnectArrangements`). They need a coach API key carrying the new `billing:read` scope; amounts are integer cents and timestamps Unix milliseconds, as the portal shows them.

## 0.6.1

- An AI stream deadline defaults to 60 s, matching the API's request cap, when the client has no `timeout` configured. An explicit client `timeout` or per-call `timeout` still applies.
- AI stream events carry `id` only when that event's block included an SSE `id:` line, instead of repeating the last id seen.

## 0.6.0

- Add async context-managed `ai.create_conversation_stream` and `ai.send_message_stream` for the existing SSE API. Preserve warnings, errors and unknown events; provide total deadlines, asyncio cancellation and early-exit cleanup. AI writes never automatically retry.
- Compatibility: legacy synchronous `ai.create_conversation` and `ai.send_message` now raise `streaming_required` before sending any request. Migrate to `async with` / `async for`. Existing JSON read methods stay synchronous and unchanged. No metadata/timestamps are fabricated.

- Add standard-library TypedDict models for nutrition, activity prescriptions, feedback, and batch responses. Values remain ordinary dictionaries; no runtime model dependency or validation is added.
- Describe nullable warnings, numeric timestamps, trial metadata, full-tier ranges, and separate indexed batch errors accurately. Static type checking may now flag access to nonexistent fields.
- Add `activities.import_activities`, with calculation opt-in.
- Correct athlete/activity list types and documentation to nested `pagination` with `next_cursor`. Request query defaults and raw responses are unchanged.
- Type athlete/settings reads and writes, describe flat concern flags and full-replacement semantics, and disclose that legacy `search` does not filter results.
- TypedDict returns no longer type-check as `Dict[str, Any]` helper arguments; use a read-only `Mapping[str, object]` or an explicit `dict(response)` copy as appropriate.
- `coach.report_pdf` returns the PDF bytes and raises the SDK's own error types (`NotFoundError` and siblings) on failure, through the same handler as every other call. Previously it raised `httpx.HTTPStatusError`. Callers catching that exception around a report download need to catch the SDK errors instead.
- Rate-limit errors expose the server's `Retry-After` value; the daily ceiling sends none, in which case the value reported is a fallback, not the true wait.

## 0.5.0

Initial public release.
