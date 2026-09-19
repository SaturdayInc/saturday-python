"""Wire response types. Values remain ordinary dictionaries at runtime."""

from typing import List, Literal, Optional, TypedDict


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
