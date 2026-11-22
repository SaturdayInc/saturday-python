"""Wire response types. Values remain ordinary dictionaries at runtime."""

from typing import Any, Dict, List, Literal, Optional, TypedDict

ActivityType = Literal["bike", "run", "swim", "row", "ski", "lift", "hike"]
"""A single sport. Each leg of a brick or triathlon is one of these."""

LinkedSessionType = Literal["brick", "triathlon"]
"""A session made of 2 to 10 legs, each a single sport."""

SessionType = Literal["bike", "run", "swim", "row", "ski", "lift", "hike", "brick", "triathlon"]
"""What a calculation or an activity can be: a single sport, or a brick or triathlon with legs."""

SessionInput = Literal["intensity_level", "thermal_stress_level", "meal_before_min", "is_race"]
"""A session input a plan from ranges can be missing."""

PlanBasisSource = Literal[
    "profile_incomplete",
    "session_incomplete",
    "profile_and_session_incomplete",
    "stored_ranges",
    "trial_allowance",
    "simulation_allowance",
]
"""Why a plan is from ranges: the athlete's profile answers are missing, the session's inputs are,
or both. ``stored_ranges`` is an activity's stored ranges with nothing missing that can be named now
(the athlete has answered since): calculate the activity again. ``trial_allowance``: the athlete's
trial has used today's calls or given all its exact answers, or this profile is past the trial's
allowance of profiles;
``message`` says which, in words you can show the athlete. ``simulation_allowance`` (test
environment only): the athlete's simulated subscription has given its allowance."""


class SafetyMetadata(TypedDict):
    max_safe_fluid_ml_per_hr: int
    max_safe_sodium_mg_per_hr: int
    confidence_score: float
    requires_human_review: bool
    warnings: Optional[List[str]]
    not_instructions: Literal[True]


class Attribution(TypedDict):
    text: str
    logo_url: str
    link: str
    required: bool


class SubscriptionCTA(TypedDict):
    message: str
    subscribe_url: str
    features: List[str]


class BandImpact(TypedDict):
    carb_g_per_hr: float
    sodium_mg_per_hr: float
    fluid_ml_per_hr: float


class _MissingFieldRequired(TypedDict):
    field: str
    # True for the safety core: sex, age, weight, sweat, saltiness, carb experience, usual carbs,
    # effort and heat. False does not mean optional: the answer stays ranges while any listed field
    # is missing, required or not.
    required: bool


class MissingField(_MissingFieldRequired, total=False):
    # Sent with a partner API key; absent with an athlete's OAuth access token.
    band_impact: BandImpact
    display_label: str


class _OnboardingInviteRequired(TypedDict):
    message: str


class OnboardingInvite(_OnboardingInviteRequired, total=False):
    url: str


# A language the hosted onboarding page opens in.
OnboardingLocale = Literal["en", "es", "fr", "pt", "de", "ja"]


class OnboardingLink(TypedDict):
    """POST /v1/athletes/{athlete_id}/onboarding-link: a fresh link to the hosted onboarding page."""

    object: Literal["onboarding_link"]
    athlete_id: str
    url: str
    expires_at: int  # Unix seconds; the link stops working then, 90 days after it was made.


class _PrecisionRequired(TypedDict):
    profile_complete: bool


class Precision(_PrecisionRequired, total=False):
    # Every field this calculation still needs, profile answers and session inputs alike. A field
    # the athlete answered in a linked Saturday app is listed too.
    missing_fields: List[MissingField]
    # With a partner API key, on every tier: the athlete's profile answers this calculation lacks,
    # by the names missing_fields uses. The onboarding link collects them.
    missing_profile_fields: List[str]
    # With a partner API key, on every tier: the session inputs your request or activity left out.
    # Send them. Both lists empty is one condition of exact numbers; the other is the athlete's
    # access (a subscription, a seat license or the trial).
    missing_session_inputs: List[SessionInput]
    # With a partner API key: names the athlete's profile answers (the onboarding link collects
    # them) apart from the session inputs your request or activity left out, and where to send those.
    message: str
    # With a partner API key, present only when profile answers are missing.
    onboarding: OnboardingInvite


class LegPrescription(TypedDict):
    """One leg's share of a brick's or triathlon's prescription, as the Saturday app's leg cards
    show it. The legs' totals add up to the session's totals before the session's own rounding.
    Per hour is as the app's leg card shows it, which is not always the leg's total divided by its hours."""

    duration_min: int
    total_carb_g: int
    total_sodium_mg: int
    total_fluid_ml: int
    carb_g_per_hr: float
    sodium_mg_per_hr: float
    fluid_ml_per_hr: float


class CalculateLeg(TypedDict):
    """One leg of a brick or triathlon on a calculate request. The legs together may be at most 2160 minutes."""

    activity_type: ActivityType
    duration_min: int  # 5 to 2160.
    intensity_level: int  # 1 to 9 (lift and hike: 1 to 3; a higher value computes as 3).
    thermal_stress_level: int  # 1 (cold, dry) to 9 (hot, humid).


class ActivityLeg(TypedDict):
    """One leg of a stored brick or triathlon. The legs together may be at most 2160 minutes."""

    type: ActivityType
    duration_min: int  # 5 to 2160.
    intensity_level: int  # 1 to 9 (lift and hike: 1 to 3; a higher value is stored as 3).
    thermal_stress_level: int  # 1 (cold, dry) to 9 (hot, humid).


class TrialMetadata(TypedDict, total=False):
    """Trial and sandbox fields on a calculation. ``partner.get()`` gives the trial's length in
    ``rate_limits.trial_days`` and the exact answers it gives in all in
    ``rate_limits.trial_answers``."""

    tier_source: str
    trial_ends_at: int  # When the trial ends, Unix seconds.
    trial_calls_remaining_today: int
    # The athlete's trial has used today's calls, so these numbers are ranges; trial_cap_note says so.
    trial_cap_reached: bool
    trial_cap_note: str
    # Your key has started its new trials for the UTC day (rate_limits.trial_starts_per_day), so
    # this athlete's trial starts on a later day and these numbers are ranges.
    trial_start_deferred: bool
    # The athlete's trial already covers its allowance of distinct profiles
    # (rate_limits.trial_profiles_per_athlete), so this new one is answered in ranges. Earlier
    # profiles stay exact.
    trial_profile_limit_reached: bool
    # The athlete's trial has given all its exact answers (rate_limits.trial_answers), so these
    # numbers are ranges until the athlete subscribes.
    trial_answers_used_up: bool
    # With trial_start_deferred, trial_profile_limit_reached or trial_answers_used_up, why these
    # numbers are ranges, in words you can show the athlete.
    trial_note: str
    # Test environment only: the athlete's simulated subscription has given its allowance of exact
    # answers or distinct profiles, so these numbers are ranges.
    simulated_limit_reached: bool
    simulation_note: str  # With simulated_limit_reached, which allowance was reached.


class _CalculationRequired(TypedDict):
    tier: Literal["full", "teaser"]
    safety: SafetyMetadata
    attribution: Attribution


class NutritionCalculateResponse(_CalculationRequired, TrialMetadata, total=False):
    """Per-hour figures are whole numbers, as the Saturday app's Fuel card shows them, which is not
    always the total divided by the session's hours. The totals are for the whole session."""

    carb_g_per_hr: float
    sodium_mg_per_hr: float
    fluid_ml_per_hr: float
    total_carb_g: int
    total_sodium_mg: int
    total_fluid_ml: int
    carb_range_g_per_hr: str
    sodium_range_mg_per_hr: str
    fluid_range_ml_per_hr: str
    precision: Precision
    subscription_cta: SubscriptionCTA
    # A brick or triathlon with exact numbers: each leg's share, in the order of the legs sent.
    # Absent for a single sport and on answers with ranges.
    legs: List[LegPrescription]


class _ActivityPrescriptionRequired(TypedDict):
    calculated_at: int  # Epoch seconds.


class ActivityPrescription(_ActivityPrescriptionRequired, total=False):
    """Exact numbers when the profile is complete; when profile_complete is false the ranges
    carry the answer and the six numbers are absent."""

    total_carb_g: int
    total_sodium_mg: int
    total_fluid_ml: int
    carb_g_per_hr: float
    sodium_mg_per_hr: float
    fluid_ml_per_hr: float
    profile_complete: bool
    carb_range_g_per_hr: str
    sodium_range_mg_per_hr: str
    fluid_range_ml_per_hr: str
    carriage_tactic_id: str
    activity_subtype: str
    # A brick or triathlon with exact numbers: each leg's share, in the order of the activity's
    # legs. Absent for a single sport and on a prescription of ranges.
    legs: List[LegPrescription]


class PrescriptionEnvelope(_CalculationRequired, TrialMetadata, total=False):
    prescription: ActivityPrescription
    carb_range_g_per_hr: str
    sodium_range_mg_per_hr: str
    fluid_range_ml_per_hr: str
    precision: Precision
    subscription_cta: SubscriptionCTA


class StoredPrescriptionResponse(TypedDict):
    prescription: ActivityPrescription
    safety: SafetyMetadata


class _ActivityFeedbackRequired(TypedDict):
    created_at: int  # Epoch seconds.


class ActivityFeedback(_ActivityFeedbackRequired, total=False):
    rating: int
    notes: str


class _ActivityRequired(TypedDict):
    id: str
    athlete_id: str
    partner_id: str
    type: SessionType
    duration_min: int  # For a brick or triathlon, its legs' total.
    created_at: int  # Epoch seconds.
    updated_at: int  # Epoch seconds.


class Activity(_ActivityRequired, total=False):
    # A brick's or triathlon's legs, in order. Absent for a single sport.
    legs: List[ActivityLeg]
    # Absent for a brick or triathlon, whose legs carry it.
    intensity_level: int
    thermal_stress_level: int
    is_race_event: bool
    meal_before_min: int
    external_id: str
    prescription: ActivityPrescription
    feedback: ActivityFeedback
    # Credit the data's sources require ("Garmin Edge 1040"): show each line verbatim with the
    # activity and anything built from it. Absent when none is required. Read-only.
    source_attributions: List[str]


class AthleteSettings(TypedDict, total=False):
    # A write takes 1, 3, 5, 7 or 9 and refuses any other value with 400 invalid_value.
    sweat_level: int
    # A write takes 1, 5 or 9 and refuses any other value with 400 invalid_value.
    saltiness: int
    # A write takes 1, 3, 5, 7 or 9 and refuses any other value with 400 invalid_value.
    satiety_level: int
    # A write takes 1, 3, 5, 7 or 9 and refuses any other value with 400 invalid_value.
    fitness_level: int
    carb_experience: str
    usual_carb_consumption: str
    # A write takes 50 to 150 g/hr in steps of 10, or 0 to clear it; any other value is refused
    # with 400 out_of_range.
    carb_upper_limit_override: int
    muscle_cramps: bool
    gut_distress: bool
    performance: bool
    hunger: bool
    heat_tolerance: bool
    faintness: bool
    drinking_resistance: bool
    thirst: bool
    concerns_answered: bool


ProfileSharing = Literal["on", "off", "not_linked"]
"""Whether an athlete shares their Saturday app answers with you; not_linked means no Saturday account is connected."""

CalculationsUse = Literal["partner", "saturday_app", "default"]
"""Where the value Saturday's calculations use for a field comes from: yours, the app answer, or neither (a default, so numbers come back as ranges)."""


class _AthleteRequired(TypedDict):
    id: str
    partner_id: str
    settings: AthleteSettings
    profile_complete: bool
    created_at: int  # Epoch seconds.
    updated_at: int  # Epoch seconds.


class Athlete(_AthleteRequired, total=False):
    external_id: str
    email: str
    name: str
    sex: str
    year_of_birth: int
    weight_kg: float
    subscription_id: str
    partner_plan: str
    org_id: str
    subscription_status: str
    profile_sharing: ProfileSharing
    """Computed on athletes.get and in the sharing webhooks' record; absent on lists, and when it could not be read."""


# Fueling profile: the athlete's Saturday app answers, when they share them with you. Each answer
# carries value (the app answer, None when not answered in the app) and calculations_use.


class FuelingConcerns(TypedDict):
    performance: bool
    gut_distress: bool
    heat_tolerance: bool
    muscle_cramps: bool
    faintness: bool
    hunger: bool
    thirst: bool
    drinking_resistance: bool


class FuelingProfileSex(TypedDict):
    value: Optional[Literal["male", "female", "intersex"]]
    calculations_use: CalculationsUse


class FuelingProfileInt(TypedDict):
    """age in whole years, or a 1 to 9 answer."""

    value: Optional[int]
    calculations_use: CalculationsUse


class FuelingProfileWeight(TypedDict):
    """Kilograms, to one decimal."""

    value: Optional[float]
    calculations_use: CalculationsUse


class FuelingProfileCarbExperience(TypedDict):
    value: Optional[Literal["range_0_30", "range_40_60", "range_gt_70"]]
    calculations_use: CalculationsUse


class FuelingProfileUsualCarb(TypedDict):
    value: Optional[Literal["range_lt_60", "range_60_80", "range_80_100", "range_gt_100"]]
    calculations_use: CalculationsUse


class FuelingProfileConcerns(TypedDict):
    """value is None when the athlete never answered the concerns question."""

    value: Optional[FuelingConcerns]
    calculations_use: CalculationsUse


class FuelingProfileAnswers(TypedDict):
    """The shared answers, under the calculation-side names."""

    sex: FuelingProfileSex
    age: FuelingProfileInt
    athlete_weight_kg: FuelingProfileWeight
    sweat_level: FuelingProfileInt
    saltiness: FuelingProfileInt
    satiety_level: FuelingProfileInt
    fitness_level: FuelingProfileInt
    carb_experience: FuelingProfileCarbExperience
    usual_carb_consumption: FuelingProfileUsualCarb
    concerns: FuelingProfileConcerns


FuelingProfileFieldName = Literal[
    "sex", "age", "athlete_weight_kg", "sweat_level", "saltiness", "satiety_level",
    "fitness_level", "carb_experience", "usual_carb_consumption", "concerns",
]
"""A shared answer's name, as athlete.fueling_profile_updated lists it in changed_fields."""


class _FuelingProfileRequired(TypedDict):
    object: Literal["fueling_profile"]
    athlete_id: str
    sharing: ProfileSharing
    message: Optional[str]


class FuelingProfile(_FuelingProfileRequired, total=False):
    """athletes.get_fueling_profile: profile and updated_at (Unix seconds) are present only when sharing is "on"; otherwise message says why."""

    profile: FuelingProfileAnswers
    updated_at: int


class _PaginationRequired(TypedDict):
    total: int
    has_more: bool


class PaginationMeta(_PaginationRequired, total=False):
    """total counts this page; pass next_cursor as the next request's cursor."""

    next_cursor: str


class AthleteListResponse(TypedDict):
    athletes: List[Athlete]
    pagination: PaginationMeta
    request_id: str


class ActivityListResponse(TypedDict):
    activities: List[Activity]
    pagination: PaginationMeta
    request_id: str


class _BatchErrorRequired(TypedDict):
    index: int
    code: str
    message: str


class BatchError(_BatchErrorRequired, total=False):
    athlete_id: str  # For athlete_exists: the athlete that holds the item's external_id.


class _BatchSummaryRequired(TypedDict):
    total: int
    succeeded: int
    failed: int
    request_id: str


class BatchSummary(_BatchSummaryRequired, total=False):
    errors: List[BatchError]


class BatchCalculateResponse(BatchSummary):
    results: List[NutritionCalculateResponse]
    estimated_ms: int
    elapsed_ms: int


class BatchAthleteResponse(BatchSummary):
    created: List[Athlete]


class _ImportActivityRequired(TypedDict):
    type: SessionType


class ImportActivityRequest(_ImportActivityRequired, total=False):
    """One activity to import. ``duration_min`` is required for a single sport; a brick or
    triathlon sends ``legs`` (its minutes are their total) and carries effort and heat on them."""

    duration_min: int
    legs: List[ActivityLeg]
    intensity_level: int
    thermal_stress_level: int
    is_race_event: bool
    meal_before_min: int
    external_id: str
    calculate: bool


class _ImportPrescriptionRequired(TypedDict):
    index: int
    activity_id: str


class ImportPrescriptionItem(_ImportPrescriptionRequired, total=False):
    result: PrescriptionEnvelope
    code: str
    message: str


class _ActivityImportRequired(BatchSummary):
    imported: List[Activity]


class ActivityImportResponse(_ActivityImportRequired, total=False):
    prescriptions: List[ImportPrescriptionItem]


# --- Coach billing (read-only; a key carrying billing:read) ---
#
# The figures the portal's Billing pages show, for the coach who minted the key.
# Amounts are integer cents in the row's currency; timestamps are Unix milliseconds.


class CoachSeatState(TypedDict):
    tier: str
    included_total: int
    included_used: int
    coach_paid_count: int
    # Coach-paid athletes whose seat starts billing when the time they paid for on their
    # own Monthly plan runs out; not in coach_paid_count until then.
    pending_coach_paid_count: int
    next_athlete_price_cents: int
    volume_tier: int
    volume_discount_pct: int
    total_monthly_cents: int
    is_fair_use: bool


class _CoachLedgerEntryRequired(TypedDict):
    id: str
    entry_id: str
    user_uid: str
    direction: Literal["charge", "receipt", "refund", "covered_by"]
    amount_cents: int
    currency: str
    category: str
    counterparty_type: str
    counterparty_display_name: str
    source_type: str
    source_reference_id: str
    description: str
    occurred_at: int
    created_at: int


class CoachLedgerEntry(_CoachLedgerEntryRequired, total=False):
    counterparty_id: str
    period_start: int
    period_end: int
    receipt_url: str
    metadata: Dict[str, Any]
    related_relationship_id: str
    related_arrangement_id: str
    tags: List[str]
    charge_group_id: str
    settlement_status: str


class _CoachLedgerPageRequired(TypedDict):
    entries: List[CoachLedgerEntry]


class CoachLedgerPage(_CoachLedgerPageRequired, total=False):
    """next_cursor is present only when another page exists; pass it back as cursor."""

    next_cursor: str


class _CoachTierSubscriptionRequired(TypedDict):
    subscription_id: str
    subscriber_type: str
    subscriber_id: str
    tier: str
    channel: str
    source_sku: str
    status: str
    current_period_start: int
    current_period_end: int
    amount_cents: int
    lifetime_discount_applied: bool
    auto_renew: bool
    created_at: int
    updated_at: int


class CoachTierSubscription(_CoachTierSubscriptionRequired, total=False):
    stripe_subscription_id: str
    iap_original_transaction_id: str
    trial_ends_at: int
    discount_code: str
    canceled_at: int
    grace_until: int
    source_purchase_doc_id: str
    purchased_assistant_seats: int


class _CoachSubscriptionStatusRequired(TypedDict):
    has_purchase: bool
    has_tier_sub: bool
    is_active: bool


class CoachSubscriptionStatus(_CoachSubscriptionStatusRequired, total=False):
    source: str
    product_id: str
    tier_id: str
    expiry_date_ms: int
    is_lifetime: bool
    has_coverage: bool


class CoachTierStatus(TypedDict):
    subscriptions: List[CoachTierSubscription]
    count: int
    status: CoachSubscriptionStatus


class _CoachConnectAccountRequired(TypedDict):
    coach_uid: str
    stripe_account_id: str
    charges_enabled: bool
    payouts_enabled: bool
    details_submitted: bool
    requirements_currently_due_count: int
    country: str
    default_currency: str
    updated_at: int


class CoachConnectAccount(_CoachConnectAccountRequired, total=False):
    card_payments_status: str
    transfers_status: str
    capabilities: Dict[str, str]
    onboarded_at: int
    disabled_reason: str
    closed: bool


class CoachConnectSummary(TypedDict):
    """connect_account is None for a coach with no Connect account. platform_fee_minimum_cents is the
    least Saturday's fee takes from a charge. coach_pays_stripe_fees_from is when the coach starts
    paying Stripe's processing fee (Unix ms, 0 while Saturday pays it); the stripe_fee_* fields are
    that fee on Saturday's account: a domestic and an international card rate, plus a fixed amount."""

    connect_account: Optional[CoachConnectAccount]
    is_onboarded: bool
    active_arrangements: int
    month_charges_cents: int
    month_fees_cents: int
    month_net_cents: int
    lifetime_charges_cents: int
    lifetime_fees_cents: int
    lifetime_net_cents: int
    platform_fee_bps: int
    platform_fee_minimum_cents: int
    coach_pays_stripe_fees_from: int
    stripe_fee_domestic_bps: int
    stripe_fee_international_bps: int
    stripe_fee_fixed_cents: int


class CoachEarningsSummary(TypedDict):
    """total_refunded_cents went back to athletes; total_platform_fee_returned_cents is Saturday's fee
    given back on refunds; total_disputes_cents was taken for disputes and their fees, less what was
    paid back, of which total_dispute_costs_recovered_cents repaid earlier disputes' costs."""

    coach_uid: str
    total_gross_cents: int
    total_stripe_fee_cents: int
    total_platform_fee_cents: int
    total_refunded_cents: int
    total_platform_fee_returned_cents: int
    total_disputes_cents: int
    total_dispute_costs_recovered_cents: int
    total_net_cents: int
    charge_count: int
    settled_count: int
    settling_count: int
    currency: str


class _CoachChargeBreakdownRequired(TypedDict):
    charge_group_id: str
    gross_amount_cents: int
    stripe_fees_cents: int
    platform_fee_cents: int
    refunded_cents: int
    platform_fee_returned_cents: int
    disputes_cents: int
    dispute_costs_recovered_cents: int
    net_to_coach_cents: int
    currency: str
    settlement_status: str
    occurred_at: int


class CoachChargeBreakdown(_CoachChargeBreakdownRequired, total=False):
    """stripe_fees_cents is the part of Stripe's processing fee the coach pays; stripe_fee_paid_by says
    who paid it, absent when no fee was recorded. refunded_cents went back to the athlete,
    platform_fee_returned_cents is Saturday's fee given back on refunds, disputes_cents was taken for
    disputes and their fees, less what was paid back, of which dispute_costs_recovered_cents repaid
    earlier disputes' costs."""

    stripe_fee_paid_by: Literal["coach", "saturday"]
    athlete_uid: str
    athlete_display_name: str


class CoachConnectEarnings(TypedDict):
    """breakdowns is an empty list when there are no charges."""

    summary: CoachEarningsSummary
    breakdowns: List[CoachChargeBreakdown]


class _CoachConnectChargeRequired(TypedDict):
    charge_id: str
    coach_uid: str
    athlete_uid: str
    amount_cents: int
    platform_fee_cents: int
    stripe_fees_cents: int
    net_to_coach_cents: int
    currency: str
    status: Literal["succeeded", "pending", "failed", "refunded", "disputed", "dispute_lost"]
    captured_at: int
    stripe_webhook_event_id: str


class CoachConnectCharge(_CoachConnectChargeRequired, total=False):
    """status is refunded once any part of the charge is, and refund_amount_cents says how much.
    stripe_fees_cents is the part of Stripe's processing fee the coach pays; stripe_fee_paid_by says who
    paid it on a destination charge (absent on a direct charge, where the coach did).
    platform_fee_returned_cents is Saturday's fee given back on refunds. Absent fields are zero."""

    arrangement_id: str
    refund_amount_cents: int
    stripe_fee_paid_by: Literal["coach", "saturday"]
    platform_fee_returned_cents: int


class _CoachConnectChargesPageRequired(TypedDict):
    charges: List[CoachConnectCharge]
    total: int


class CoachConnectChargesPage(_CoachConnectChargesPageRequired, total=False):
    """total counts this page; next_cursor is present only when another page exists."""

    next_cursor: str


class _CoachBillingArrangementRequired(TypedDict):
    arrangement_id: str
    coach_uid: str
    athlete_uid: str
    stripe_connect_account_id: str
    billing_mode: Literal["recurring", "one_time", "invoice"]
    amount_cents: int
    currency: str
    status: Literal["active", "paused", "canceled", "past_due"]
    platform_fee_bps: int
    created_at: int


class CoachBillingArrangement(_CoachBillingArrangementRequired, total=False):
    stripe_customer_id: str
    stripe_subscription_id: str
    interval: str
    trial_days: int
    promo_code: str
    refund_policy: str
    terms_text: str
    activated_at: int
    paused_at: int
    canceled_at: int


class CoachConnectArrangements(TypedDict):
    arrangements: List[CoachBillingArrangement]
    total: int


# --- Webhooks ---

WebhookEventType = Literal[
    "athlete.created", "athlete.updated", "athlete.profile_completed",
    "athlete.profile_sharing_changed", "athlete.fueling_profile_updated", "athlete.deleted",
    "activity.created", "activity.updated", "activity.deleted",
    "prescription.calculated", "feedback.submitted",
    "subscription.created", "subscription.updated", "subscription.cancelled",
    "partner.rate_limit_approaching", "webhook.test",
]
"""Event names a partner webhook can register. Registration rejects the whole request on one
unknown name. subscription.updated and partner.rate_limit_approaching are accepted but never sent
to a partner webhook."""


class WebhookEvent(TypedDict):
    """A webhook delivery's body. Verify the signature on the raw body before parsing it."""

    id: str
    type: str
    created_at: int  # When the event happened, Unix seconds. The signature header's t is Unix seconds too.
    data: Dict[str, Any]


class FuelingProfileUpdatedData(Athlete):
    """The athlete record, profile_sharing included, plus the names of the shared answers that changed."""

    changed_fields: List[FuelingProfileFieldName]


class ProfileSharingChangedEvent(TypedDict):
    """athlete.profile_sharing_changed: data is the athlete record as athletes.get returns it, profile_sharing its new state."""

    id: str
    type: Literal["athlete.profile_sharing_changed"]
    created_at: int  # Unix seconds.
    data: Athlete


class FuelingProfileUpdatedEvent(TypedDict):
    """athlete.fueling_profile_updated: the athlete record plus the names of the changed answers, never their values."""

    id: str
    type: Literal["athlete.fueling_profile_updated"]
    created_at: int  # Unix seconds.
    data: FuelingProfileUpdatedData


# --- Prep, product fit and product compare ---


class NutrientAmounts(TypedDict):
    """Whole-session amounts."""

    carb_g: int
    sodium_mg: int
    fluid_ml: int


class _PerServingRequired(TypedDict):
    carb_g: float
    sodium_mg: float
    fluid_ml: float


class PerServing(_PerServingRequired, total=False):
    # Absent when Saturday has no caffeine figure for the product.
    caffeine_mg: float


class GapAmounts(TypedDict):
    carb_g: float
    sodium_mg: float
    fluid_ml: float


LimitingFactor = Literal["carbs", "sodium", "fluid", "product_too_large", "negligible_per_serving", "no_nutrients"]


class ProductFitDetail(TypedDict):
    product_id: str
    product_name: str
    product_type: str
    brand: str
    per_serving: PerServing
    # The most servings, in the app's Prep steps, before a nutrient overshoots; 0 when one step already does.
    max_servings: float
    at_max_servings: NutrientAmounts
    carb_coverage_pct: float
    sodium_coverage_pct: float
    fluid_coverage_pct: float
    limiting_factor: LimitingFactor
    remaining_gap: GapAmounts
    verdict: str


class _PlanBasisRequired(TypedDict):
    source: PlanBasisSource
    message: str  # Names what is missing and where each goes, or which allowance was reached. Show it with the plan.
    carb_range_g_per_hr: str
    sodium_range_mg_per_hr: str
    fluid_range_ml_per_hr: str


class PlanBasis(_PlanBasisRequired, total=False):
    """Present when a plan uses the middle of the per-hour ranges for the session because the
    athlete's profile or the session is missing inputs, or a trial or simulated subscription is past
    its allowance (``source``). With every input in and the athlete's access open, it is absent."""

    # The athlete's profile answers the plan lacks, by the names precision.missing_fields uses.
    missing_profile_fields: List[str]
    # The session inputs the plan lacks: send them in the request (fit, compare), or set them on
    # the activity (prep).
    missing_session_inputs: List[SessionInput]
    # Present only when profile answers are missing.
    onboarding: OnboardingInvite


class ProductCategory(TypedDict):
    id: str
    name: str
    description: str


class _ProductAnswerRequired(TypedDict):
    tier: Literal["full", "teaser"]
    safety: SafetyMetadata


class ProductFitLeg(TypedDict):
    """One leg of a brick or triathlon on a fit answer, in the order of the legs sent: its share of
    the session's plan, as the Saturday app's leg cards show it, and the product sized against that
    share, as the app's Prep page for that leg sizes it."""

    activity_type: ActivityType
    duration_min: int
    prescription: NutrientAmounts
    fit: ProductFitDetail


class ProductFitResponse(_ProductAnswerRequired, total=False):
    """``full`` carries prescription and fit; ``teaser`` carries categories, cta and request_id."""

    prescription: NutrientAmounts  # The whole session's plan.
    fit: ProductFitDetail  # The product sized against the whole session.
    # A brick or triathlon with exact numbers: each leg's share and the product sized against it.
    # Absent for a single sport and on a plan from ranges (plan_basis).
    legs: List[ProductFitLeg]
    plan_basis: PlanBasis
    categories: List[ProductCategory]
    cta: SubscriptionCTA
    request_id: str
    # Teaser tier only: your key has started its new trials for the UTC day, so this athlete's
    # trial starts on a later day. trial_note says why, in words you can show the athlete.
    trial_start_deferred: bool
    trial_note: str


ProductChoice = Literal["product_a", "product_b"]


class ComparisonWinner(TypedDict):
    """The product covering more of each nutrient at its max_servings; overall by average coverage. A tie goes to product_a."""

    carb: ProductChoice
    sodium: ProductChoice
    fluid: ProductChoice
    overall: ProductChoice


class ProductCompareLeg(TypedDict):
    """One leg of a brick or triathlon on a compare answer, in the order of the legs sent: its share
    of the plan and both products sized against it."""

    activity_type: ActivityType
    duration_min: int
    prescription: NutrientAmounts
    product_a: ProductFitDetail
    product_b: ProductFitDetail
    winner: ComparisonWinner


class ProductCompareResponse(_ProductAnswerRequired, total=False):
    prescription: NutrientAmounts  # The whole session's plan.
    product_a: ProductFitDetail
    product_b: ProductFitDetail
    winner: ComparisonWinner
    # A brick or triathlon with exact numbers: each leg's share and both products sized against it.
    # Absent for a single sport and on a plan from ranges (plan_basis).
    legs: List[ProductCompareLeg]
    plan_basis: PlanBasis
    categories: List[ProductCategory]
    cta: SubscriptionCTA
    request_id: str
    trial_start_deferred: bool  # Teaser tier only, as on product fit.
    trial_note: str


class PrepProduct(TypedDict):
    product_id: str
    product_name: str
    servings: float
    carb_g: int
    sodium_mg: int
    fluid_ml: int


class CoveragePct(TypedDict):
    carb: float
    sodium: float
    fluid: float


class GearItem(TypedDict):
    id: str
    name: str
    type: str
    capacity_ml: int
    is_default: bool
    created_at: int  # Unix seconds.
    updated_at: int  # Unix seconds.


class _PrepLegRequired(TypedDict):
    activity_type: ActivityType
    duration_min: int
    prescription: NutrientAmounts
    products: List[PrepProduct]
    totals_from_products: NutrientAmounts
    remaining_gap: NutrientAmounts
    coverage_pct: CoveragePct


class PrepLeg(_PrepLegRequired, total=False):
    """One leg of a brick or triathlon on a prep answer, in leg order: the leg's share of the plan,
    as the Saturday app's leg card shows it, and its products sized against that share, as the
    app's Prep page for that leg sizes them."""

    warnings: List[str]  # Present when the leg's products overshoot its share.
    note: str  # Present when a gap remains on the leg, saying what the base mix covers.


class _PrepResponseRequired(TypedDict):
    prescription: NutrientAmounts
    products: List[PrepProduct]
    totals_from_products: NutrientAmounts
    remaining_gap: NutrientAmounts
    coverage_pct: CoveragePct
    safety: SafetyMetadata


class PrepResponse(_PrepResponseRequired, total=False):
    """Totals are for the whole activity. On a brick or triathlon with exact numbers, legs preps
    each leg and the top level is the legs added up: each product once with its servings and
    nutrients summed over the legs, totals_from_products and remaining_gap the legs' sums,
    coverage_pct those totals against prescription, and warnings the legs' warnings, each naming
    its leg. prescription stays the session's plan; the legs' shares add up to it before the
    session's own rounding, so prescription less the totals can differ from remaining_gap by that
    rounding."""

    gear: List[GearItem]
    warnings: List[str]
    note: str
    # A brick or triathlon with exact numbers: each leg prepped against its share. Absent for a
    # single session and on a plan from ranges.
    legs: List[PrepLeg]
    plan_basis: PlanBasis


# --- Reference and meta ---


class ActivityTypeInfo(TypedDict):
    id: ActivityType
    name: str
    description: str


class LinkedSessionTypeInfo(TypedDict):
    """A session type made of legs, and the rules for its legs."""

    id: LinkedSessionType
    name: str
    description: str
    min_legs: int
    max_legs: int
    leg_types: List[ActivityType]  # The sports a leg may be.
    min_leg_duration_min: int
    max_duration_min: int  # The most minutes the legs may add up to.


class _ActivityTypesRequired(TypedDict):
    activity_types: List[ActivityTypeInfo]  # The single sports.
    total: int  # How many entries activity_types holds.
    request_id: str


class ActivityTypesResponse(_ActivityTypesRequired, total=False):
    # brick and triathlon, with the rules for their legs. Sent to a partner API key.
    linked_session_types: List[LinkedSessionTypeInfo]


class _SettingsFieldRequired(TypedDict):
    field: str
    type: Literal["integer", "string", "boolean"]
    description: str
    default: Any


class SettingsFieldSchema(_SettingsFieldRequired, total=False):
    min: float
    max: float
    options: List[str]
    # The only values an integer setting takes, when it takes fewer than every whole number from
    # min to max (sweat_level, satiety_level and fitness_level: 1, 3, 5, 7, 9; saltiness: 1, 5, 9).
    values: List[int]
    # The spacing of the values an integer setting takes from min to max (carb_upper_limit_override: 10).
    step: int


class SettingsSchemaResponse(TypedDict):
    settings: List[SettingsFieldSchema]
    total: int
    request_id: str


class _OnboardingOptionRequired(TypedDict):
    value: Any
    label_en: str


class OnboardingOption(_OnboardingOptionRequired, total=False):
    l10n_key: str
    pre_checked: bool


class _OnboardingQuestionRequired(TypedDict):
    field: str
    type: Literal["single_select", "multi_select", "year_of_birth", "weight"]
    required: bool
    title_en: str


class OnboardingQuestion(_OnboardingQuestionRequired, total=False):
    l10n_key: str
    options: List[OnboardingOption]
    min: float
    max: float


class OnboardingQuestionsResponse(TypedDict):
    schema_version: str
    questions: List[OnboardingQuestion]
    attribution: Attribution
    request_id: str


class _DiscoveryKeyInfoRequired(TypedDict):
    how: str
    page: str  # https://saturday.fit/api
    athletes_per_key: int
    more_athletes: str  # How to ask for more athletes.
    contact: str  # api@saturday.fit


class DiscoveryKeyInfo(_DiscoveryKeyInfoRequired, total=False):
    """How a key is had, in plain text values: a key comes with any paid Saturday plan and is made
    by the signed-in account at saturday.fit/api; it covers athletes_per_key athletes until
    Saturday raises it."""

    # The account routes that page calls. They take a signed-in Saturday account, not an API key,
    # so the SDK does not call them.
    account_routes: str
    trial: str
    limits: str
    platforms: str
    docs: str
    quickstart: str
    llms_txt: str
    who_is_this: str


class DiscoveryResponse(TypedDict):
    """``GET /v1/``: the routes and features this key can see, and how a key is had."""

    name: str
    version: str
    # Resource names to paths. A feature short of general availability carries its stage in its
    # name ("nutrition (alpha)"); a hidden feature is absent.
    links: Dict[str, str]
    get_a_key: DiscoveryKeyInfo
    request_id: str


class ErrorCatalogEntry(TypedDict):
    code: str
    type: str
    http_status: int
    message: str
    retryable: bool
    documentation_url: str


class ErrorCatalogResponse(TypedDict):
    errors: List[ErrorCatalogEntry]
    total: int
    request_id: str


class HealthResponse(TypedDict):
    status: str
    timestamp: str
    version: str


# --- Partner account ---


class PartnerRateLimits(TypedDict):
    requests_per_second: float
    burst_size: int
    requests_per_minute: int
    requests_per_day: Optional[int]  # All calls a day; None when no daily ceiling applies.
    ip_requests_per_day: Optional[int]  # Calculation calls a day; None when none applies.
    # New athlete trials this key may start per UTC day; an athlete past it gets ranges with
    # trial_start_deferred. None when the key has no such bound.
    trial_starts_per_day: Optional[int]
    # Distinct profiles one trial athlete's exact numbers cover over the trial; a further one gets
    # ranges with trial_profile_limit_reached. None when the key has no such bound.
    trial_profiles_per_athlete: Optional[int]
    trial_days: int  # Days an athlete's trial lasts from its first exact answer.
    # Exact answers one athlete's trial gives in all, however the days fall; the next answer gets
    # ranges with trial_answers_used_up. None when the key has no such bound.
    trial_answers: Optional[int]


class _PartnerAccountRequired(TypedDict):
    id: str
    name: str
    contact_email: str
    status: Literal["active", "suspended"]
    # partner for a platform partner, individual for a key that comes with a Saturday account's paid plan.
    plan: Literal["partner", "individual"]
    rate_limits: PartnerRateLimits
    created_at: int  # Unix seconds.


class PartnerAccount(_PartnerAccountRequired, total=False):
    return_url: str  # Where the hosted onboarding page sends athletes back to you; absent when none is set.
    # Where an athlete who opens an expired onboarding link is sent, with athlete_id and locale in the
    # query, so your server can get a fresh link and send them on. Absent when none is set.
    refresh_url: str


class DailyUsage(TypedDict):
    date: str  # YYYY-MM-DD, UTC.
    total_calls: int
    by_endpoint: Dict[str, int]
    ip_calls: int
    own_calls: int
    unique_athletes: int
    estimate_calculates: int


UsagePeriod = TypedDict("UsagePeriod", {"from": str, "to": str})


class UsageResponse(TypedDict):
    total_calls: int
    by_endpoint: Dict[str, int]
    period: UsagePeriod
    daily: List[DailyUsage]
    request_id: str


class DailyUsageResponse(TypedDict):
    daily: List[DailyUsage]
    period: UsagePeriod
    request_id: str


class _ApiKeyInfoRequired(TypedDict):
    id: str
    name: str
    environment: Literal["live", "test"]
    scopes: List[str]
    created_at: int  # Unix seconds.
    last_used_at: int  # The last authenticated call, Unix seconds; 0 when never used.
    revoked: bool


class ApiKeyInfo(_ApiKeyInfoRequired):
    pass


class ApiKeyListResponse(TypedDict):
    api_keys: List[ApiKeyInfo]
    total: int
    request_id: str


class CreatedApiKey(TypedDict):
    """``key`` is shown once: store it."""

    id: str
    key: str
    name: str
    environment: Literal["live", "test"]
    scopes: List[str]
    created_at: int  # Unix seconds.
    message: str
    request_id: str


class RotatedApiKey(TypedDict):
    id: str
    key: str
    name: str
    environment: Literal["live", "test"]
    scopes: List[str]
    rotated_from: str
    message: str
    request_id: str


# --- Webhooks ---


class _WebhookRequired(TypedDict):
    id: str
    partner_id: str
    url: str
    events: List[str]
    active: bool
    fail_count: int
    created_at: int  # Unix seconds.
    updated_at: int  # Unix seconds.


class Webhook(_WebhookRequired, total=False):
    disabled_at: int  # Unix seconds; set when Saturday disabled the webhook after repeated failures.


class WebhookWithSecret(Webhook):
    """The webhook as webhooks.create returns it: secret signs every delivery and is never returned again."""

    secret: str


class WebhookCreateResponse(TypedDict):
    """webhooks.create: the new webhook, with its signing secret, under webhook."""

    webhook: WebhookWithSecret
    message: str
    request_id: str


class WebhookListResponse(TypedDict):
    webhooks: List[Webhook]
    total: int
    request_id: str


class _WebhookDeliveryRequired(TypedDict):
    id: str
    webhook_id: str
    partner_id: str
    event_id: str
    event_type: str
    url: str
    status: Literal["pending", "delivered", "failed", "exhausted"]
    status_code: int
    attempts: int
    created_at: int  # Unix seconds.


class WebhookDelivery(_WebhookDeliveryRequired, total=False):
    response_body: str
    event_data: str  # The event body, base64.
    next_retry_at: int  # Unix seconds.
    completed_at: int  # Unix seconds.


class WebhookTestResponse(TypedDict):
    delivery: WebhookDelivery
    request_id: str


class WebhookDeliveryList(TypedDict):
    """The 50 most recent delivery attempts, newest first."""

    deliveries: List[WebhookDelivery]
    total: int
    request_id: str


# --- Organizations ---


class _OrganizationRequired(TypedDict):
    id: str
    partner_id: str
    display_name: str
    member_count: int
    created_at: int  # Unix seconds.
    updated_at: int


class Organization(_OrganizationRequired, total=False):
    description: str
    sport: str


class OrganizationListResponse(TypedDict):
    organizations: List[Organization]
    pagination: PaginationMeta
    request_id: str


class _OrganizationMemberRequired(TypedDict):
    id: str
    email: str
    role: Literal["admin", "member"]
    joined_at: int  # Unix seconds.


class OrganizationMember(_OrganizationMemberRequired, total=False):
    athlete_id: str


class OrganizationMembersResponse(TypedDict):
    members: List[OrganizationMember]
    total: int
    request_id: str


class _OrganizationOfferRequired(TypedDict):
    id: str
    org_id: str
    discount_percent: int
    active: bool
    created_at: int  # Unix seconds.
    stack_cap_percent: int


class OrganizationOffer(_OrganizationOfferRequired, total=False):
    applies_to_plan: str
    negotiated_by: str
    starts_at: int  # Unix seconds.
    ends_at: int
    note: str


class OrganizationSubscription(TypedDict):
    id: str
    org_id: str
    partner_id: str
    type: Literal["team", "enterprise"]
    seats: int
    used_seats: int
    status: Literal["active", "expired", "cancelled"]
    start_date: int  # Unix seconds.
    end_date: int  # Unix seconds.
    created_at: int  # Unix seconds.


class OrganizationSubscriptionListResponse(TypedDict):
    subscriptions: List[OrganizationSubscription]
    total: int
    request_id: str


class _LicenseRequired(TypedDict):
    email: str
    added_at: int  # Unix seconds.
    active: bool


class License(_LicenseRequired, total=False):
    athlete_id: str
    name: str


class LicenseListResponse(TypedDict):
    licenses: List[License]
    total: int
    request_id: str


# --- Privacy ---


ConsentType = Literal["data_processing", "marketing", "analytics"]


class _ConsentRecordRequired(TypedDict):
    id: str
    athlete_id: str
    partner_id: str
    consent_type: ConsentType
    granted: bool
    granted_at: int  # Unix seconds.


class ConsentRecord(_ConsentRecordRequired, total=False):
    revoked_at: int
    ip_address: str


class ConsentListResponse(TypedDict):
    consent: List[ConsentRecord]
    total: int
    request_id: str


class _AthleteDataExportRequired(TypedDict):
    athlete_id: str
    partner_id: str
    exported_at: int  # When the export was made, Unix seconds.
    # The athlete record as stored, every stored field included. Every time in the export's
    # records is Unix seconds.
    profile: Dict[str, Any]


class AthleteDataExport(_AthleteDataExportRequired, total=False):
    activities: List[Dict[str, Any]]  # Each activity as stored, its stored prescription included.
    consent: List[Dict[str, Any]]


# --- Integrations and the test project ---


IntegrationProvider = Literal["intervals_icu", "strava", "training_peaks"]
"""The providers ``integrations.status`` and ``integrations.disconnect`` take."""

SyncProvider = Literal["intervals_icu"]
"""The provider ``integrations.sync`` takes. Strava and TrainingPeaks tokens are refused with a
``ValidationError`` (``invalid_provider``)."""


class _IntegrationStatusDetailRequired(TypedDict):
    provider: IntegrationProvider
    connected: bool
    sync_count: int


class IntegrationStatusDetail(_IntegrationStatusDetailRequired, total=False):
    last_sync_at: int  # Unix seconds.
    errors: List[str]


class IntegrationStatusResponse(TypedDict):
    status: IntegrationStatusDetail
    request_id: str


class _IntegrationSyncResultRequired(TypedDict):
    provider: SyncProvider
    # partial when some activities could not be stored, failed when none could or intervals.icu
    # refused the token; errors says why.
    status: Literal["completed", "partial", "failed"]
    activities_found: int
    activities_synced: int
    activities_skipped: int  # Found but not stored: the activity's type names no sport the API supports.


class IntegrationSyncResult(_IntegrationSyncResultRequired, total=False):
    # Whether the athlete's prescriptions for these activities are exact (full) or ranges (teaser).
    prescription_tier: Literal["full", "teaser"]
    errors: List[str]


class IntegrationSyncResponse(TypedDict):
    result: IntegrationSyncResult
    request_id: str


class IntegrationDisconnectResponse(TypedDict):
    """The connection you supplied is ended."""

    message: str  # For example "Successfully disconnected intervals_icu".
    provider: IntegrationProvider
    request_id: str


class SimulateSubscriptionResponse(TypedDict):
    athlete_id: str
    simulated_active: bool
    request_id: str
