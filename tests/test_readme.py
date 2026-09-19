from pathlib import Path
import json
import re

import httpx
import pytest


@pytest.mark.parametrize("payload, expected", [
    ({"tier": "full", "carb_g_per_hr": 70, "sodium_mg_per_hr": 900, "fluid_ml_per_hr": 1000}, ["70", "900", "1000"]),
    ({"tier": "full", "carb_range_g_per_hr": "60-80", "sodium_range_mg_per_hr": "800-1000", "fluid_range_ml_per_hr": "900-1100"}, ["60-80", "800-1000", "900-1100"]),
    ({"tier": "teaser", "carb_range_g_per_hr": "60-90", "sodium_range_mg_per_hr": "500-1000", "fluid_range_ml_per_hr": "500-1000"}, ["60-90", "500-1000", "500-1000"]),
    ({"tier": "full"}, ["0", "0", "0"]),
])
def test_readme_quickstart(monkeypatch, capsys, payload, expected):
    def send(client, request, **kwargs):
        assert request.method == "POST"
        assert request.url.path == "/v1/nutrition/calculate"
        return httpx.Response(200, json={**payload, "safety": {"warnings": []}}, request=request)

    monkeypatch.setattr(httpx.Client, "send", send)
    readme = Path(__file__).parents[1].joinpath("README.md").read_text()
    code = re.search(r"```python\n(.*?)```", readme, re.S).group(1)
    namespace = {}
    try:
        exec(compile(code, "README.md quickstart", "exec"), namespace)
    finally:
        if "client" in namespace:
            namespace["client"].close()

    assert capsys.readouterr().out.splitlines() == [
        "[]", f"Carbs: {expected[0]} g/hr", f"Sodium: {expected[1]} mg/hr", f"Fluid: {expected[2]} mL/hr",
    ]


@pytest.mark.parametrize("name, warnings, carbs", [
    ("stored_exact", None, "60"),
    ("stored_banded", [], "50-70"),
    ("stored_banded", ["Review this recommendation"], "50-70"),
])
def test_readme_stored_prescription(monkeypatch, capsys, name, warnings, carbs):
    fixtures = json.loads(Path(__file__).with_name("fixtures").joinpath("contracts.json").read_text())
    payload = fixtures[name]

    def send(client, request, **kwargs):
        assert request.method == "GET"
        assert request.url.path == "/v1/athletes/ath_123/activities/act_123/prescription"
        return httpx.Response(200, json={**payload, "safety": {**payload["safety"], "warnings": warnings}}, request=request)

    monkeypatch.setattr(httpx.Client, "send", send)
    readme = Path(__file__).parents[1].joinpath("README.md").read_text()
    code = next(code for code in re.findall(r"```python\n(.*?)```", readme, re.S) if "get_prescription" in code)
    exec(compile(code, "README.md stored prescription", "exec"), {})
    assert capsys.readouterr().out.splitlines() == [f"Carbs: {carbs} g/hr", *(warnings or [])]
