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

    # Safety metadata is ALWAYS included — athlete safety cannot be paywalled
    print(prescription["safety"]["warnings"])
    print(f"Carbs: {prescription['carb_g_per_hr']} g/hr")
"""

from saturday.client import Saturday
from saturday.errors import (
    SaturdayError,
    AuthenticationError,
    RateLimitError,
    ValidationError,
    NotFoundError,
)

__version__ = "0.1.0"
__all__ = [
    "Saturday",
    "SaturdayError",
    "AuthenticationError",
    "RateLimitError",
    "ValidationError",
    "NotFoundError",
]
