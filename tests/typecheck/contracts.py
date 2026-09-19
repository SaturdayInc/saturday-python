from typing import Any, Dict, Mapping, Optional

from saturday import (
    ActivityFeedback,
    ActivityImportResponse,
    ActivityListResponse,
    AthleteListResponse,
    AthleteSettings,
    BatchAthleteResponse,
    BatchCalculateResponse,
    ImportActivityRequest,
    PrescriptionEnvelope,
    Saturday,
    StoredPrescriptionResponse,
)


def read_mapping(value: Mapping[str, object]) -> None:
    pass


def mutable_dictionary(value: Dict[str, Any]) -> None:
    pass


def check_resource_types(client: Saturday) -> None:
    calculated: PrescriptionEnvelope = client.activities.calculate_prescription("ath_1", "act_1")
    stored: StoredPrescriptionResponse = client.activities.get_prescription("ath_1", "act_1")
    batch: BatchCalculateResponse = client.nutrition.batch_calculate([{"activity_type": "bike", "duration_min": 120}])
    athletes: BatchAthleteResponse = client.athletes.batch_create([{"name": "Fixture"}])
    activities: list[ImportActivityRequest] = [{"type": "bike", "duration_min": 120, "calculate": True}]
    imported: ActivityImportResponse = client.activities.import_activities("ath_1", activities, calculate=False)
    feedback: ActivityFeedback = client.activities.submit_feedback("ath_1", "act_1", rating=4)
    athlete_page: AthleteListResponse = client.athletes.list()
    activity_page: ActivityListResponse = client.activities.list("ath_1")
    cursor: Optional[str] = athlete_page["pagination"].get("next_cursor")
    has_more: bool = activity_page["pagination"]["has_more"]
    settings: AthleteSettings = client.athletes.get_settings("ath_1")
    updated: AthleteSettings = client.athletes.update_settings("ath_1", sweat_level=5, gut_distress=False)
    read_mapping(calculated)
    mutable_dictionary(dict(calculated))
    mutable_dictionary(calculated)  # type: ignore[arg-type]
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
    athlete_page["has_more"]  # type: ignore[typeddict-item]
    activity_page["cursor"]  # type: ignore[typeddict-item]
    settings["concerns"]  # type: ignore[typeddict-item]
    settings["athlete_id"]  # type: ignore[typeddict-item]
