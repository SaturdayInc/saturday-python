from typing import Any, Dict, Mapping, Optional

from saturday import (
    ActivityFeedback,
    CoachConnectArrangements,
    CoachConnectChargesPage,
    CoachConnectEarnings,
    CoachConnectSummary,
    CoachLedgerPage,
    CoachSeatState,
    CoachTierStatus,
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
    seats: CoachSeatState = client.coach.seat_state(org_id="org_1")
    ledger: CoachLedgerPage = client.coach.ledger(view="inflows", limit=50, cursor="1749480000000")
    tier: CoachTierStatus = client.coach.tier_status()
    summary: CoachConnectSummary = client.coach.connect_summary()
    earnings: CoachConnectEarnings = client.coach.connect_earnings()
    charges: CoachConnectChargesPage = client.coach.connect_transactions(limit=20)
    arrangements: CoachConnectArrangements = client.coach.connect_arrangements()
    fair_use: bool = seats["is_fair_use"]
    next_cursor: Optional[str] = ledger.get("next_cursor")
    active: bool = tier["status"]["is_active"]
    account = summary["connect_account"]
    country: Optional[str] = account["country"] if account is not None else None
    net: int = earnings["summary"]["total_net_cents"] + charges["charges"][0]["net_to_coach_cents"] + arrangements["arrangements"][0]["amount_cents"]
    ledger["pagination"]  # type: ignore[typeddict-item]
    seats["next_athlete_price"]  # type: ignore[typeddict-item]
