"""
Saturday Nutrition Intelligence API — Official Python SDK

Personalized fuel, hydration, and electrolyte prescriptions for endurance
athletes. Calculate carbohydrate, sodium, and fluid targets based on activity
type, duration, athlete profile, and environmental conditions.

Example::

    from saturday import Saturday

    client = Saturday(api_key="sk_live_...")

    prescription = client.nutrition.calculate(
        activity_type="bike",
        duration_min=180,
        athlete_weight_kg=75.0,
        thermal_stress_level=7,
    )

    # Safety metadata is included on every tier.
    print(prescription["safety"]["warnings"])
    carbs = prescription.get("carb_range_g_per_hr", prescription.get("carb_g_per_hr", 0))
    print(f"Carbs: {carbs} g/hr")
"""

from saturday.client import SDK_VERSION, Saturday
from saturday.errors import (
    SaturdayError,
    AuthenticationError,
    RateLimitError,
    ValidationError,
    NotFoundError,
)
from saturday.types import (
    Activity,
    ActivityFeedback,
    ActivityImportResponse,
    ActivityPrescription,
    Athlete,
    Attribution,
    BandImpact,
    BatchAthleteResponse,
    BatchCalculateResponse,
    BatchError,
    BatchSummary,
    ImportActivityRequest,
    ImportPrescriptionItem,
    MissingField,
    NutritionCalculateResponse,
    OnboardingInvite,
    Precision,
    PrescriptionEnvelope,
    SafetyMetadata,
    StoredPrescriptionResponse,
    SubscriptionCTA,
    TrialMetadata,
)

__version__ = SDK_VERSION
__all__ = [
    "Saturday",
    "SaturdayError",
    "AuthenticationError",
    "RateLimitError",
    "ValidationError",
    "NotFoundError",
    "Activity",
    "ActivityFeedback",
    "ActivityImportResponse",
    "ActivityPrescription",
    "Athlete",
    "Attribution",
    "BandImpact",
    "BatchAthleteResponse",
    "BatchCalculateResponse",
    "BatchError",
    "BatchSummary",
    "ImportActivityRequest",
    "ImportPrescriptionItem",
    "MissingField",
    "NutritionCalculateResponse",
    "OnboardingInvite",
    "Precision",
    "PrescriptionEnvelope",
    "SafetyMetadata",
    "StoredPrescriptionResponse",
    "SubscriptionCTA",
    "TrialMetadata",
]
