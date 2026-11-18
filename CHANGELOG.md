# Changelog

## 0.8.0 (unreleased)

Breaking changes:

- `products`, `gear` and `ai` are removed, with their types, `AIStreamError` and `AIStreamEvent`. Those routes are not open to partner keys.
- `webhooks.create(url, events)` returns `WebhookCreateResponse`: the webhook, with its signing secret, is under `webhook`; read `response["webhook"]["secret"]`. `webhooks.list()`, `get()`, `update()` and `test()` are typed (`WebhookListResponse`, `Webhook`, `WebhookTestResponse`). The `description` argument is gone; the API does not take one.
- `webhooks.update` takes `url`, `events` and `active` as keyword arguments; `organizations.add_member` takes `role` and `athlete_id` as keyword arguments; `activities.submit_feedback` takes `rating` and `notes`.
- `athletes.list` drops the `search` argument, which the API ignored, and gains `external_id` (the athletes you created with that `external_id`, newest first) and `profile_complete` filters.
- Retries follow what the API says. A `RateLimitError` is read by its `code`: `rate_limit_exceeded` (a throttle) is retried after `Retry-After`, and `catalog_paced` when that wait is 30 s or less; `rate_limited` (a block after an unusual request pattern) and the four daily ceilings (`daily_call_limit_reached`, `intelligence_daily_limit_reached`, `athlete_free_daily_limit_reached`, `distinct_lookup_daily_limit_reached`) raise at once. A daily ceiling has `daily_limit` True and `resets_at`, the UTC midnight it resets at (a timezone-aware `datetime`). A 429 with no `Retry-After` is treated as a daily ceiling. A 5xx is retried after its `Retry-After`, or after 1, 2 and 4 seconds, except on a `POST` that creates or changes a record, since the server may have done the write; calculation, product, inference, prep and export `POST`s still are, with every `GET`, `PUT`, `PATCH` and `DELETE`. The client never sleeps longer than 30 s inside one call.
- `SaturdayError.retry_after`, from `Retry-After` on any error that carries one. `DAILY_LIMIT_CODES` is exported.
- `organizations.update_subscription` takes `seats`, `status`, `start_date` and `end_date` (Unix seconds); the API refuses any other field.
- 403 responses raise the new `PermissionDeniedError`.
- `ActivityPrescription`'s six numbers are optional: a prescription stored as ranges (`profile_complete` false) carries none of them.
- `PlanBasis["source"]` is `PlanBasisSource` (`profile_incomplete`, `session_incomplete`, `profile_and_session_incomplete`, `stored_ranges`), with `missing_profile_fields` and `missing_session_inputs`.
- `ApiKeyInfo["last_used_at"]` is always present: 0 for a key never used.
- Every timestamp a partner key receives is Unix seconds, matching the API: webhooks and deliveries, `WebhookEvent["created_at"]` and the two typed sharing events, `PartnerAccount["created_at"]`, `ApiKeyInfo` and `CreatedApiKey` times, `TrialMetadata["trial_ends_at"]`, the fueling profile's `updated_at` and `IntegrationStatusDetail["last_sync_at"]` were milliseconds. `AthleteDataExport["exported_at"]` is an `int` of Unix seconds (it was an RFC 3339 string), and every time in the export's records is Unix seconds. Coach types keep Unix milliseconds.
- `activities.prep` sends only the lists you pass: `products=`, `legs=`, or an empty `products` list when you pass neither.
- `ImportActivityRequest` takes `type` alone as required (`duration_min` is required for a single sport only), with `legs` and `meal_before_min`.

Added:

- `nutrition.product_fit`, `nutrition.compare_products` and `activities.prep`, with `PlanBasis` for plans made from the middle of the ranges, naming what is missing.
- Prep, product fit and compare on a brick or triathlon: `product_fit` and `compare_products` take `legs`, and their answers carry `ProductFitLeg` and `ProductCompareLeg` under `legs`, each leg's share with the product or products sized against it; compare's `winner` is `ComparisonWinner`. `activities.prep(..., legs=[...])` takes a product list per leg, and `PrepLeg` comes under `PrepResponse["legs"]`, whose top level is the legs added up.
- `Precision["missing_profile_fields"]` and `Precision["missing_session_inputs"]`: the profile answers and session inputs a calculation lacks, sent to a partner key on every tier. `MissingField["required"]` documents what it marks: the safety core, with every listed field needed for exact numbers.
- Bricks and triathlons: `legs` on calculate, batch, activity create, import and update (`CalculateLeg`, `ActivityLeg`), each leg's share as `LegPrescription` under `legs` on `NutritionCalculateResponse` and `ActivityPrescription`, and `Activity["legs"]`. `ActivityType`, `LinkedSessionType` and `SessionType` literals. `reference.activity_types(activity_type=...)` filters, and `ActivityTypesResponse["linked_session_types"]` (`LinkedSessionTypeInfo`) carries the rules for legs.
- `ValidationError.suggestion`: for code `unsupported_field`, the field the request was probably meant to send, read from the API's message. `param` is the field's path in your body (`legs[1].duration_mins`).
- `nutrition.extract` (nutrition label reading), `infer.activity_type`, `infer.brick_types`, `reference.activity_types`, `reference.settings_schema`.
- `athletes.erase` (`POST /v1/athletes/{id}/delete`), `athletes.list_consent`, `record_consent`, `revoke_consent`.
- `partner.get`, `usage`, `usage_daily`, `list_api_keys`, `create_api_key`, `revoke_api_key`, `rotate_api_key`.
- `webhooks.list_deliveries` (`WebhookDeliveryList`); `organizations.update`, offers and seat subscriptions with licenses; `integrations.sync`, `status`, `disconnect`; `testing.simulate_subscription`; `meta.discovery`, `errors`, `health`.
- `set_notification_rules` documents `channel_config`, the email address and push devices alerts go to: a write replaces it with the rest of the set, so send back the one `get_notification_rules` returned. Left out at the overall scope, the coach's email and push alerts turn off.
- TypedDicts for every new response, and `OnboardingQuestionsResponse` for `onboarding.questions`.
- A live suite (`tests/test_live.py`) and a check of its recorded responses against the types. The suite covers bricks and triathlons through calculate, batch, activity create, prep, update and import.

Earlier unreleased changes:

- Add `athletes.get_fueling_profile(athlete_id)` for `GET /v1/athletes/{id}/fueling-profile`: the athlete's Saturday app answers while they share them with you, typed as `FuelingProfile`. `profile` (`FuelingProfileAnswers`, each answer with `value` and `calculations_use`) and `updated_at` are present only when `sharing` is `"on"`; `"off"` and `"not_linked"` carry `message`. `Athlete` gains the optional `profile_sharing` (`ProfileSharing`: `on`, `off` or `not_linked`), returned by `athletes.get`.
- Add webhook body types: `WebhookEvent`, `WebhookEventType` (the names registration accepts), and `ProfileSharingChangedEvent` and `FuelingProfileUpdatedEvent` for `athlete.profile_sharing_changed` and `athlete.fueling_profile_updated`, whose data is the athlete record (the second adds `changed_fields`, typed `FuelingProfileFieldName`).
- `Activity` gains the optional `source_attributions`: the credit lines the activity's sources require, for example `"Garmin Edge 1040"` on a workout recorded on a Garmin device. Show each line verbatim wherever you show the activity or anything built from it. The API sends it only when a source requires credit; the coach roster, report and session reads carry the same field.
- `set_notification_rules` documents `hourly_cap` (`enabled`, `per_hour` 1 to 12), the limit on the emails, and separately the pushes, one athlete's alerts send the coach in any 60 minutes. With no scope setting it, the cap is on at 1 per hour; leaving it out of the rules clears it at that scope.
- `CoachConnectCharge` gains the optional `stripe_fee_paid_by` (`coach` or `saturday`) and `platform_fee_returned_cents` the transactions endpoint returns. `CoachChargeBreakdown` gains `stripe_fee_paid_by`, `refunded_cents`, `platform_fee_returned_cents`, `disputes_cents` and `dispute_costs_recovered_cents`, and `CoachEarningsSummary` their `total_` sums, which the earnings endpoint returns. `CoachConnectSummary` gains the fee terms the summary endpoint returns: `platform_fee_minimum_cents`, `coach_pays_stripe_fees_from` and Stripe's rates (`stripe_fee_domestic_bps`, `stripe_fee_international_bps`, `stripe_fee_fixed_cents`).
- `CoachSeatState` gains `pending_coach_paid_count`: coach-paid athletes whose seat starts billing when the time they paid for on their own Monthly plan runs out. They are not in `coach_paid_count` until then.
- `MissingField.band_impact` is optional. A request made with an athlete's OAuth access token (`bearer_token`) gets `precision["missing_fields"]` without `band_impact`, in a fixed order. With a partner API key every entry still carries `band_impact`, sorted most-impactful-first. Read it with `.get("band_impact")`.

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
