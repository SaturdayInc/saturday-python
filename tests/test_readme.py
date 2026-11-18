from pathlib import Path
import json
import re

import httpx
import pytest


ATHLETE = {"id": "ath_1", "partner_id": "partner_example", "settings": {}, "profile_complete": True, "created_at": 1, "updated_at": 1}


@pytest.mark.parametrize("payload, expected", [
    ({"tier": "full", "carb_g_per_hr": 70, "sodium_mg_per_hr": 900, "fluid_ml_per_hr": 1000, "precision": {"profile_complete": True}},
     ["70", "900", "1000"]),
    ({"tier": "full", "carb_range_g_per_hr": "60-80", "sodium_range_mg_per_hr": "800-1000", "fluid_range_ml_per_hr": "900-1100",
      "precision": {"profile_complete": False}}, ["60-80", "800-1000", "900-1100"]),
    ({"tier": "full", "carb_g_per_hr": 70, "fluid_ml_per_hr": 500, "precision": {"profile_complete": True}}, ["70", "0", "500"]),
])
def test_readme_quickstart(monkeypatch, capsys, payload, expected):
    def send(client, request, **kwargs):
        assert request.method == "POST"
        body = json.loads(request.content)
        if request.url.path == "/v1/athletes":
            assert body["settings"]["concerns_answered"] is True
            return httpx.Response(201, json=ATHLETE, request=request)
        assert request.url.path == "/v1/nutrition/calculate"
        assert body == {"athlete_id": "ath_1", "activity_type": "bike", "duration_min": 180, "intensity_level": 5,
                        "thermal_stress_level": 7, "meal_before_min": 120, "is_race": False}
        return httpx.Response(200, json={**payload, "safety": {"warnings": ["Drink to thirst above this rate."]}}, request=request)

    monkeypatch.setattr(httpx.Client, "send", send)
    monkeypatch.setenv("SATURDAY_API_KEY", "sk_test_fake")
    readme = Path(__file__).parents[1].joinpath("README.md").read_text()
    code = re.search(r"```python\n(.*?)```", readme, re.S).group(1)
    exec(compile(code, "README.md quickstart", "exec"), {})

    assert capsys.readouterr().out.splitlines() == [
        f"Carbs: {expected[0]} g/hr", f"Sodium: {expected[1]} mg/hr", f"Fluid: {expected[2]} mL/hr", "Drink to thirst above this rate.",
    ]


def test_readme_python_examples_compile():
    readme = Path(__file__).parents[1].joinpath("README.md").read_text()
    for i, code in enumerate(re.findall(r"```python\n(.*?)```", readme, re.S)):
        compile(code, f"README.md example {i}", "exec")


@pytest.mark.parametrize("name, expected", [
    ("fueling_profile_on", "Sweat level 7; calculations use saturday_app"),
    ("fueling_profile_off", "This athlete has not chosen to share their Saturday app answers with you."),
    ("fueling_profile_not_linked", "This athlete has not connected a Saturday account, so there are no Saturday app answers to share."),
])
def test_readme_fueling_profile(monkeypatch, capsys, name, expected):
    fixtures = json.loads(Path(__file__).with_name("fixtures").joinpath("contracts.json").read_text())

    def send(client, request, **kwargs):
        assert request.method == "GET"
        assert request.url.path == "/v1/athletes/ath_123/fueling-profile"
        return httpx.Response(200, json=fixtures[name], request=request)

    monkeypatch.setattr(httpx.Client, "send", send)
    readme = Path(__file__).parents[1].joinpath("README.md").read_text()
    code = next(code for code in re.findall(r"```python\n(.*?)```", readme, re.S) if "get_fueling_profile" in code)
    exec(compile(code, "README.md fueling profile", "exec"), {})
    assert capsys.readouterr().out.splitlines() == [expected]
