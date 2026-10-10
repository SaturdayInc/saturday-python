"""Wire response types. Values remain ordinary dictionaries at runtime."""

from typing import Any, Dict, List, Literal, Optional, TypedDict


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
    required: bool
    band_impact: BandImpact


class MissingField(_MissingFieldRequired, total=False):
    display_label: str


class _OnboardingInviteRequired(TypedDict):
    message: str


class OnboardingInvite(_OnboardingInviteRequired, total=False):
    url: str


class _PrecisionRequired(TypedDict):
    profile_complete: bool


class Precision(_PrecisionRequired, total=False):
    missing_fields: List[MissingField]
    message: str
    onboarding: OnboardingInvite


class TrialMetadata(TypedDict, total=False):
    tier_source: str
    trial_ends_at: int  # Epoch milliseconds.
    trial_calls_remaining_today: int
    trial_cap_reached: bool
    trial_cap_note: str


class _CalculationRequired(TypedDict):
    tier: Literal["full", "teaser"]
    safety: SafetyMetadata
    attribution: Attribution


class NutritionCalculateResponse(_CalculationRequired, TrialMetadata, total=False):
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


class _ActivityPrescriptionRequired(TypedDict):
    total_carb_g: int
    total_sodium_mg: int
    total_fluid_ml: int
    carb_g_per_hr: float
    sodium_mg_per_hr: float
    fluid_ml_per_hr: float
    calculated_at: int  # Epoch seconds.


class ActivityPrescription(_ActivityPrescriptionRequired, total=False):
    """When profile_complete is false, ranges carry the result and numbers are zero."""

    profile_complete: bool
    carb_range_g_per_hr: str
    sodium_range_mg_per_hr: str
    fluid_range_ml_per_hr: str
    carriage_tactic_id: str
    activity_subtype: str


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
    type: str
    duration_min: int
    created_at: int  # Epoch seconds.
    updated_at: int  # Epoch seconds.


class Activity(_ActivityRequired, total=False):
    intensity_level: int
    thermal_stress_level: int
    is_race_event: bool
    meal_before_min: int
    external_id: str
    prescription: ActivityPrescription
    feedback: ActivityFeedback


class AthleteSettings(TypedDict, total=False):
    sweat_level: int
    saltiness: int
    satiety_level: int
    fitness_level: int
    carb_experience: str
    usual_carb_consumption: str
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
    """athletes.get_fueling_profile: profile and updated_at (Unix ms) are present only when sharing is "on"; otherwise message says why."""

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


class BatchError(TypedDict):
    index: int
    code: str
    message: str


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
    type: Literal["bike", "run", "swim", "row", "ski", "lift", "hike"]
    duration_min: int


class ImportActivityRequest(_ImportActivityRequired, total=False):
    intensity_level: int
    thermal_stress_level: int
    is_race_event: bool
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
    created_at: int
    data: Dict[str, Any]


class FuelingProfileUpdatedData(Athlete):
    """The athlete record, profile_sharing included, plus the names of the shared answers that changed."""

    changed_fields: List[FuelingProfileFieldName]


class ProfileSharingChangedEvent(TypedDict):
    """athlete.profile_sharing_changed: data is the athlete record as athletes.get returns it, profile_sharing its new state."""

    id: str
    type: Literal["athlete.profile_sharing_changed"]
    created_at: int
    data: Athlete


class FuelingProfileUpdatedEvent(TypedDict):
    """athlete.fueling_profile_updated: the athlete record plus the names of the changed answers, never their values."""

    id: str
    type: Literal["athlete.fueling_profile_updated"]
    created_at: int
    data: FuelingProfileUpdatedData
