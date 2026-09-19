"""Opt-in sandbox contract proof. Never enabled by the normal test suite."""

import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4

import pytest
import httpx

from saturday import Saturday, SaturdayError


SANDBOX_BASE = "https://partner-api-5vozuebg2a-uc.a.run.app"
OPT_IN = "SATURDAY_SANDBOX_ALLOW_MUTATIONS"


def sandbox_config(env):
    if env.get(OPT_IN) != "1":
        return None
    if env.get("SATURDAY_SANDBOX_BASE_URL") != SANDBOX_BASE:
        raise ValueError("Exact sandbox base URL required")
    if not env.get("SATURDAY_SANDBOX_API_KEY", "").startswith("sk_test_"):
        raise ValueError("Sandbox test key required")
    return dict(api_key=env["SATURDAY_SANDBOX_API_KEY"], base_url=SANDBOX_BASE, max_retries=0, timeout=60)


def test_sandbox_requires_explicit_mutation_opt_in():
    assert sandbox_config({}) is None
    assert sandbox_config({"SATURDAY_SANDBOX_API_KEY": "sk_test_fake", "SATURDAY_SANDBOX_BASE_URL": SANDBOX_BASE}) is None


@pytest.mark.parametrize("env", [
    {},
    {"SATURDAY_SANDBOX_BASE_URL": "https://api.saturday.fit", "SATURDAY_SANDBOX_API_KEY": "sk_test_fake"},
    {"SATURDAY_SANDBOX_BASE_URL": SANDBOX_BASE + "/", "SATURDAY_SANDBOX_API_KEY": "sk_test_fake"},
    {"SATURDAY_SANDBOX_BASE_URL": SANDBOX_BASE, "SATURDAY_SANDBOX_API_KEY": "sk_live_fake"},
])
def test_unsafe_sandbox_configuration_is_rejected(env):
    with pytest.raises(ValueError):
        sandbox_config({**env, OPT_IN: "1"})


def test_sandbox_disables_request_retries():
    config = sandbox_config({OPT_IN: "1", "SATURDAY_SANDBOX_BASE_URL": SANDBOX_BASE, "SATURDAY_SANDBOX_API_KEY": "sk_test_fake"})
    assert config["base_url"] == SANDBOX_BASE
    assert config["max_retries"] == 0


@pytest.mark.parametrize("tier", ["full", "teaser"])
def test_sandbox_rehearsal_uses_only_offline_transport(monkeypatch, capsys, tier):
    fixtures = json.loads(Path(__file__).with_name("fixtures").joinpath("contracts.json").read_text())
    envelope = fixtures["activity_full" if tier == "full" else "activity_teaser"]
    nutrition = fixtures["nutrition_exact" if tier == "full" else "nutrition_teaser"]
    activities, calls, preferences = [], [], {}
    athlete_id = "owned-athlete"

    def send(client, request, **kwargs):
        nonlocal preferences
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        calls.append(request.method + " " + path)
        assert not client.follow_redirects
        if path == "/v1/athletes":
            assert "email" not in body
            preferences = body["settings"]
            payload = {**fixtures["athlete"], **body, "id": athlete_id}
        elif path.endswith("/settings"):
            if request.method == "PATCH":
                preferences = body
            payload = preferences
        elif path == "/v1/nutrition/calculate":
            payload = nutrition
        elif path == "/v1/nutrition/calculate/batch":
            payload = {**fixtures["batch_partial"], "total": 2, "succeeded": 1, "results": [nutrition]}
        elif path == "/v1/athletes/batch":
            assert all(not value.get("email") for value in body["athletes"])
            payload = {**fixtures["athletes_partial"], "created": [{**fixtures["athlete"], **body["athletes"][0], "id": "owned-batch"}]}
        elif path.endswith("/import"):
            item = body["activities"][0]
            activity = {**fixtures["activity"], **item, "id": f"owned-activity-{len(activities)}", "athlete_id": athlete_id}
            activity.pop("prescription", None)
            activities.append(activity)
            payload = {**fixtures["import_plain"], "imported": [activity]}
            if body.get("calculate") or item.get("calculate"):
                payload["prescriptions"] = [{"index": 0, "activity_id": activity["id"], "result": envelope}]
        elif path.endswith("/activities") and request.method == "POST":
            payload = {**fixtures["activity"], **body, "id": "owned-activity", "athlete_id": athlete_id}
            payload.pop("prescription", None)
            activities.append(payload)
        elif path.endswith("/activities"):
            payload = {"activities": activities[:1], "pagination": {"total": 1, "has_more": True, "next_cursor": "1700000000"}, "request_id": "fixture"}
        elif path.endswith("/calculate"):
            payload = envelope
        elif path.endswith("/prescription"):
            payload = fixtures["stored_exact"]
        elif path.endswith("/feedback"):
            payload = fixtures["feedback"]
        else:
            raise AssertionError("Unexpected offline sandbox path")
        return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setenv(OPT_IN, "1")
    monkeypatch.setenv("SATURDAY_SANDBOX_BASE_URL", SANDBOX_BASE)
    monkeypatch.setenv("SATURDAY_SANDBOX_API_KEY", "sk_test_fake")
    test_live_sandbox_contracts_with_new_synthetic_records_only(monkeypatch)
    lines = capsys.readouterr().out.splitlines()
    report = json.loads(lines[-1].removeprefix("SATURDAY_SANDBOX_LEDGER "))
    assert len(calls) == (14 if tier == "full" else 13)
    assert report["stage"] == "passed" and len(report["created"]) == 6
    assert "sk_test_fake" not in json.dumps(report)
    assert report["variants"]["stored"] == ("verified" if tier == "full" else "not available under natural teaser tier")


@pytest.mark.skipif(os.environ.get(OPT_IN) != "1", reason="explicit sandbox mutation opt-in required")
def test_live_sandbox_contracts_with_new_synthetic_records_only(monkeypatch):
    config = sandbox_config(os.environ)
    run_id = f"sdk-python-{uuid4()}"
    report = {
        "run_id": run_id, "stage": "start", "calls": 0, "created": [], "variants": {},
        "cleanup": "retained named test fixtures; athlete DELETE does not cascade subcollections",
    }
    owned_athletes = set()
    deadline = time.monotonic() + 300

    def ledger():
        print("SATURDAY_SANDBOX_LEDGER " + json.dumps(report), flush=True)

    def must(condition, code):
        if not condition:
            report["failure"] = code
            raise AssertionError("Sandbox contract assertion failed")

    def stage(name):
        report["stage"] = name
        ledger()

    def safety(value):
        must(isinstance(value, dict) and value.get("not_instructions") is True, "safety framing")
        warnings = value.get("warnings")
        must("warnings" in value and (warnings is None or (isinstance(warnings, list) and all(isinstance(item, str) for item in warnings))), "nullable safety warnings")
        for field in ("max_safe_fluid_ml_per_hr", "max_safe_sodium_mg_per_hr", "confidence_score"):
            must(type(value.get(field)) in (int, float), "safety " + field)
        must(type(value.get("requires_human_review")) is bool, "human review flag")

    def prescription(value):
        must(isinstance(value, dict), "prescription object")
        for field in ("total_carb_g", "total_sodium_mg", "total_fluid_ml", "carb_g_per_hr", "sodium_mg_per_hr", "fluid_ml_per_hr", "calculated_at"):
            must(type(value.get(field)) in (int, float), "prescription " + field)
        must(0 < value["calculated_at"] < 100000000000, "calculated_at epoch seconds")

    def calculation(value, nested):
        must(isinstance(value, dict) and value.get("tier") in ("full", "teaser"), "calculation tier")
        safety(value.get("safety"))
        must(isinstance(value.get("attribution"), dict), "attribution")
        if nested and value["tier"] == "full":
            prescription(value.get("prescription"))
        for field in ("trial_ends_at", "trial_calls_remaining_today"):
            if field in value:
                must(type(value[field]) in (int, float), field)
        result = value["prescription"] if nested and value["tier"] == "full" else value
        for field in ("carb_range_g_per_hr", "sodium_range_mg_per_hr", "fluid_range_ml_per_hr"):
            if field in result or value["tier"] == "teaser":
                must(isinstance(result.get(field), str), field)
        return {"tier": value["tier"], "banded": isinstance(result.get("carb_range_g_per_hr"), str), "trial": value.get("tier_source") == "trial"}

    def remember_athlete(value, marker):
        must(isinstance(value, dict) and isinstance(value.get("id"), str) and value.get("external_id") == marker and value.get("name") == marker and not value.get("email"), "new athlete ownership")
        owned_athletes.add(value["id"])
        report["created"].append({"resource": "athlete", "id": value["id"], "marker": marker})
        ledger()
        return value["id"]

    def remember_activity(value, athlete_id, marker):
        must(isinstance(value, dict) and isinstance(value.get("id"), str) and value.get("athlete_id") == athlete_id and value.get("external_id") == marker, "new activity ownership")
        report["created"].append({"resource": "activity", "id": value["id"], "athlete_id": athlete_id, "marker": marker})
        ledger()
        return value["id"]

    settings = dict(
        sweat_level=5, saltiness=5, satiety_level=5, fitness_level=5,
        carb_experience="range_40_60", usual_carb_consumption="range_60_80",
        muscle_cramps=False, gut_distress=False, performance=False, hunger=False,
        heat_tolerance=False, faintness=False, drinking_resistance=False, thirst=False,
    )
    with Saturday(**config) as client:
        original_request = client.request

        def guarded(method, path, **kwargs):
            report["calls"] += 1
            must(report["calls"] <= 20 and time.monotonic() < deadline, "sandbox call/time budget")
            athlete = re.match(r"^/v1/athletes/([^/]+)/", path)
            allowed = athlete.group(1) in owned_athletes if athlete else path in (
                "/v1/athletes", "/v1/athletes/batch", "/v1/nutrition/calculate", "/v1/nutrition/calculate/batch",
            )
            must(allowed, "owned resource path")
            must(method in ("GET", "POST", "PATCH") and not (method == "GET" and path == "/v1/athletes"), "permitted operation")
            return original_request(method, path, **kwargs)

        monkeypatch.setattr(client, "request", guarded)
        try:
            stage("create athlete")
            athlete_id = remember_athlete(client.athletes.create(name=run_id, external_id=run_id, sex="intersex", year_of_birth=1990, weight_kg=75, settings=settings), run_id)
            stage("read settings")
            stored_settings = client.athletes.get_settings(athlete_id)
            must(stored_settings.get("sweat_level") == 5 and "concerns" not in stored_settings, "flat settings")
            stage("replace own settings")
            updated = client.athletes.update_settings(athlete_id, **{**settings, "gut_distress": True})
            must(updated.get("gut_distress") is True and updated.get("sweat_level") == 5, "settings replacement response")
            stage("create activity")
            activity_id = remember_activity(client.activities.create(athlete_id, type="bike", duration_min=60, intensity_level=5, thermal_stress_level=5, meal_before_min=120, external_id=run_id + "-activity"), athlete_id, run_id + "-activity")
            stage("calculate activity")
            envelope = client.activities.calculate_prescription(athlete_id, activity_id)
            report["variants"]["activity"] = calculation(envelope, True)
            if envelope.get("prescription"):
                stage("read stored prescription")
                stored = client.activities.get_prescription(athlete_id, activity_id)
                prescription(stored.get("prescription"))
                safety(stored.get("safety"))
                must("tier" not in stored, "stored wrapper has no tier")
                report["variants"]["stored"] = "verified"
            else:
                report["variants"]["stored"] = "not available under natural teaser tier"
            stage("calculate nutrition")
            report["variants"]["nutrition"] = calculation(client.nutrition.calculate(athlete_id=athlete_id, activity_type="run", duration_min=45, intensity_level=5, thermal_stress_level=5, meal_before_min=120), False)
            for mode in ("default", "global", "per_item"):
                stage("import " + mode)
                marker = run_id + "-" + mode
                item = dict(type="bike", duration_min=30, external_id=marker)
                if mode == "per_item":
                    item["calculate"] = True
                options = {} if mode == "default" else {"calculate": mode == "global"}
                result = client.activities.import_activities(athlete_id, [item], **options)
                must(result.get("total") == 1 and result.get("succeeded") == 1 and result.get("failed") == 0 and len(result.get("imported", [])) == 1, "import summary")
                remember_activity(result["imported"][0], athlete_id, marker)
                if mode == "default":
                    must(not result.get("prescriptions") and not result["imported"][0].get("prescription"), "default import does not calculate")
                else:
                    outcomes = result.get("prescriptions", [])
                    must(len(outcomes) == 1 and outcomes[0].get("index") == 0 and outcomes[0].get("activity_id") == result["imported"][0]["id"], "import calculation indexes")
                    report["variants"]["import_" + mode] = calculation(outcomes[0].get("result"), True)
            stage("nutrition batch")
            batch = client.nutrition.batch_calculate([
                dict(athlete_id=athlete_id, activity_type="bike", duration_min=40),
                dict(athlete_id=athlete_id, activity_type="bike", duration_min=0),
            ])
            must(batch.get("total") == 2 and batch.get("succeeded") == 1 and batch.get("failed") == 1 and len(batch.get("results", [])) == 1 and batch.get("errors", [{}])[0].get("index") == 1, "flat partial nutrition batch")
            must(type(batch.get("estimated_ms")) is int and type(batch.get("elapsed_ms")) is int, "batch timing")
            report["variants"]["batch"] = calculation(batch["results"][0], False)
            stage("athlete batch")
            marker = run_id + "-batch"
            athletes = client.athletes.batch_create([dict(name=marker, external_id=marker), {}])
            must(athletes.get("total") == 2 and athletes.get("succeeded") == 1 and athletes.get("failed") == 1 and len(athletes.get("created", [])) == 1 and athletes.get("errors", [{}])[0].get("index") == 1, "flat partial athlete batch")
            remember_athlete(athletes["created"][0], marker)
            stage("scoped activity pagination")
            page = client.activities.list(athlete_id, limit=1)
            pagination = page.get("pagination", {})
            must(isinstance(page.get("activities"), list) and all(value.get("athlete_id") == athlete_id for value in page["activities"]) and pagination.get("total") == len(page["activities"]) and type(pagination.get("has_more")) is bool and isinstance(page.get("request_id"), str), "nested scoped pagination")
            if pagination["has_more"]:
                must(isinstance(pagination.get("next_cursor"), str), "next cursor")
            stage("feedback")
            feedback = client.activities.submit_feedback(athlete_id, activity_id, rating=4, notes="Synthetic SDK contract test")
            must(feedback.get("rating") == 4 and type(feedback.get("created_at")) is int and "message" not in feedback, "feedback object")
            report["stage"] = "passed"
        except Exception as error:
            report["error"] = {"kind": type(error).__name__}
            if isinstance(error, SaturdayError):
                report["error"]["status"] = error.status
            raise AssertionError("Sandbox contract failed at " + report["stage"] + "; inspect sanitized ledger") from None
        finally:
            ledger()
