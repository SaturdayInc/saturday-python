from typing import Optional

from saturday import (
    ActivityFeedback,
    ActivityImportResponse,
    BatchAthleteResponse,
    BatchCalculateResponse,
    ImportActivityRequest,
    PrescriptionEnvelope,
    Saturday,
    StoredPrescriptionResponse,
)


def check_resource_types(client: Saturday) -> None:
    calculated: PrescriptionEnvelope = client.activities.calculate_prescription("ath_1", "act_1")
    stored: StoredPrescriptionResponse = client.activities.get_prescription("ath_1", "act_1")
    batch: BatchCalculateResponse = client.nutrition.batch_calculate([{"activity_type": "bike", "duration_min": 120}])
    athletes: BatchAthleteResponse = client.athletes.batch_create([{"name": "Fixture"}])
    activities: list[ImportActivityRequest] = [{"type": "bike", "duration_min": 120, "calculate": True}]
    imported: ActivityImportResponse = client.activities.import_activities("ath_1", activities, calculate=False)
    feedback: ActivityFeedback = client.activities.submit_feedback("ath_1", "act_1", rating=4)
    timestamp: int = stored["prescription"]["calculated_at"]
    remaining: Optional[int] = calculated.get("trial_calls_remaining_today")
    warnings = stored["safety"]["warnings"]
    if warnings is not None:
        for warning in warnings:
            warning.upper()
    calculated["carb_g_per_hr"]  # type: ignore[typeddict-item]
    stored["tier"]  # type: ignore[typeddict-item]
    batch["results"][0]["index"]  # type: ignore[typeddict-item]
    athletes["athletes"]  # type: ignore[typeddict-item]
    feedback["message"]  # type: ignore[typeddict-item]
