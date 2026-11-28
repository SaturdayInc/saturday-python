from pathlib import Path
import inspect
import json
import re
import textwrap

import httpx
import pytest

import saturday

FIXTURES = Path(__file__).with_name("fixtures")
LIVE = {name: entry["body"] for name, entry in json.loads(FIXTURES.joinpath("live.json").read_text()).items()}
CONTRACTS = json.loads(FIXTURES.joinpath("contracts.json").read_text())
README = (Path(__file__).parents[1] / "README.md").read_text()
BLOCKS = re.findall(r"```python\n(.*?)```", README, re.S)


def _block(marker):
    return next(code for code in BLOCKS if marker in code)


def _run(monkeypatch, code, route, filename, namespace=None):
    """Execute an example with httpx.Client.send routed to ``route``."""
    seen = []

    def send(client, request, **kwargs):
        seen.append(request)
        return route(request)

    monkeypatch.setattr(httpx.Client, "send", send)
    namespace = {} if namespace is None else namespace
    exec(compile(code, filename, "exec"), namespace)
    return namespace, seen


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


def test_every_readme_block_has_an_executing_test():
    """Each python block in the README is run by a test in this file: the
    markers below are the substrings those tests select their block by, plus
    the quickstart (first block) and fueling profile tests above."""
    markers = ["Still needed:", "brick.get", "except ConflictError", "signing_secret",
               "hourly_cap", "except RateLimitError", "delegated =", "get_fueling_profile"]
    covered = {0}
    for marker in markers:
        covered |= {i for i, code in enumerate(BLOCKS) if marker in code}
    assert covered == set(range(len(BLOCKS))), f"README blocks not executed by any test: {sorted(set(range(len(BLOCKS))) - covered)}"


def _json(request, payload, status=200):
    return httpx.Response(status, json=payload, request=request)


def test_readme_prep_and_product_fit(monkeypatch, capsys):
    def route(request):
        path = request.url.path
        if path == "/v1/nutrition/products/fit":
            body = json.loads(request.content)
            return _json(request, LIVE["product_fit_brick"] if body.get("activity_type") == "brick" else LIVE["product_fit"])
        if path.endswith("/calculate"):
            return _json(request, LIVE["activity_calculate"])
        if path.endswith("/prep"):
            return _json(request, LIVE["prep"])
        assert path == "/v1/athletes/ATHLETE_ID/activities", path
        return _json(request, LIVE["activity"], 201)

    _, seen = _run(monkeypatch, _block("Still needed:"), route, "README.md prep and product fit")

    created = json.loads(seen[0].content)
    assert created == {"type": "bike", "duration_min": 150, "intensity_level": 6, "thermal_stress_level": 6,
                       "meal_before_min": 120, "is_race_event": False}
    prep = LIVE["prep"]
    expected = [f"{p['servings']} x {p['product_name']}" for p in prep["products"]]
    expected.append(f"Still needed: {prep['remaining_gap']}")
    expected.append(LIVE["product_fit"]["fit"]["verdict"])
    expected += [f"{leg['activity_type']}: {leg['fit']['max_servings']} servings"
                 for leg in LIVE["product_fit_brick"]["legs"]]
    assert capsys.readouterr().out.splitlines() == expected


def test_readme_bricks_and_triathlons(monkeypatch, capsys):
    def route(request):
        path = request.url.path
        if path == "/v1/nutrition/calculate":
            return _json(request, LIVE["calculate_brick"])
        if path.endswith("/calculate"):
            return _json(request, LIVE["activity_calculate_brick"])
        if path.endswith("/prep"):
            return _json(request, LIVE["prep_brick_per_leg"])
        assert path == "/v1/athletes/ATHLETE_ID/activities", path
        return _json(request, LIVE["activity_brick"], 201)

    _run(monkeypatch, _block("brick.get"), route, "README.md bricks and triathlons")

    expected = [f"{leg['duration_min']} min: {leg['total_carb_g']} g carbs" for leg in LIVE["calculate_brick"]["legs"]]
    expected.append(str(LIVE["activity_calculate_brick"]["prescription"]["legs"]))
    expected += [f"{leg['activity_type']} {len(leg['products'])} {leg['remaining_gap']}"
                 for leg in LIVE["prep_brick_per_leg"]["legs"]]
    assert capsys.readouterr().out.splitlines() == expected


def test_readme_external_id_conflict(monkeypatch, capsys):
    athlete = LIVE["athlete"]

    def route(request):
        if request.method == "POST":
            return _json(request, {"error": {"type": "invalid_request", "code": "athlete_exists",
                                              "athlete_id": athlete["id"],
                                              "message": 'An athlete with external_id "user-42" already exists.'}}, 409)
        assert request.url.path == f"/v1/athletes/{athlete['id']}"
        return _json(request, athlete)

    namespace, _ = _run(monkeypatch, _block("except ConflictError"), route, "README.md external id")
    assert namespace["athlete"] == athlete
    assert capsys.readouterr().out.splitlines() == [athlete["id"]]


def test_readme_webhooks(monkeypatch, capsys):
    def route(request):
        if request.url.path.endswith("/test"):
            return _json(request, LIVE["webhook_test"])
        assert request.url.path == "/v1/webhooks"
        return _json(request, LIVE["webhook_created"], 201)

    namespace, _ = _run(monkeypatch, _block("signing_secret"), route, "README.md webhooks")
    assert namespace["signing_secret"] == LIVE["webhook_created"]["webhook"]["secret"]
    delivery = LIVE["webhook_test"]["delivery"]
    assert capsys.readouterr().out.splitlines() == [f"{delivery['status']} {delivery['status_code']}"]


def test_readme_coach_alert_rules(monkeypatch):
    from test_api_surface import COACH_RULES

    def route(request):
        assert request.url.path == "/v1/coach/config/notification-rules"
        if request.method == "GET":
            assert dict(request.url.params) == {"scope": "overall"}
            return _json(request, COACH_RULES)
        return _json(request, COACH_RULES)

    _, seen = _run(monkeypatch, _block("hourly_cap"), route, "README.md coach alert rules")
    assert json.loads(seen[1].content) == {
        "scope": "overall", "scope_id": None,
        "rules": {**COACH_RULES, "hourly_cap": {"enabled": True, "per_hour": 2}},
    }


@pytest.mark.parametrize("status, error_body, headers, check", [
    (429, {"type": "rate_limit_error", "code": "daily_call_limit_reached", "message": "Daily call limit reached."}, {},
     lambda line: re.fullmatch(r"daily_call_limit_reached: resets at \d{4}-\d{2}-\d{2}T00:00:00\+00:00", line)),
    (429, {"type": "rate_limit_error", "code": "rate_limited", "message": "Blocked."}, {"Retry-After": "5"},
     lambda line: line == "rate_limited: try again in 5 s"),
    (400, {"type": "invalid_request", "code": "unsupported_field", "param": "is_rac",
           "message": '"is_rac" is not a field of this request. Did you mean "is_race"?'}, {},
     lambda line: line == "is_rac is not a field of this request; send is_race"),
    (400, {"type": "invalid_request", "code": "invalid_value", "param": "duration_min",
           "message": "duration_min is out of range"}, {},
     lambda line: line == "Fix duration_min: duration_min is out of range"),
], ids=["daily-limit", "blocked", "unsupported-field", "invalid-value"])
def test_readme_errors(monkeypatch, capsys, status, error_body, headers, check):
    def route(request):
        return httpx.Response(status, json={"error": error_body}, headers=headers, request=request)

    _run(monkeypatch, _block("except RateLimitError"), route, "README.md errors")
    (line,) = capsys.readouterr().out.splitlines()
    assert check(line), line


def test_readme_configuration(monkeypatch):
    def route(request):
        pytest.fail("the configuration example makes no request")

    namespace, seen = _run(monkeypatch, _block("delegated ="), route, "README.md configuration")
    try:
        assert seen == []
        client = namespace["client"]
        assert client._base_url == "https://api.saturday.fit"
        assert client._timeout == 30.0
        assert client._max_retries == 3
        delegated = namespace["delegated"]
        assert delegated._bearer_token == "eyJ..."
        # The athlete's token is sent in place of the API key.
        assert delegated._client.headers["Authorization"] == "Bearer " + delegated._bearer_token
    finally:
        namespace["client"].close()
        namespace["delegated"].close()


def _docstring_code(obj):
    lines = inspect.getdoc(obj).splitlines()
    start = next(i for i, line in enumerate(lines) if line.rstrip().endswith("::"))
    return textwrap.dedent("\n".join(lines[start + 1:])).strip()


def test_package_docstring_example(monkeypatch, capsys):
    def route(request):
        assert request.url.path == "/v1/nutrition/calculate"
        assert json.loads(request.content) == {"activity_type": "bike", "duration_min": 120}
        return _json(request, CONTRACTS["nutrition_exact"])

    monkeypatch.setenv("SATURDAY_API_KEY", "sk_test_fake")
    _run(monkeypatch, _docstring_code(saturday), route, "package docstring example")
    plan = CONTRACTS["nutrition_exact"]
    assert capsys.readouterr().out.splitlines() == [str(plan.get("carb_g_per_hr", plan.get("carb_range_g_per_hr")))]


def test_saturday_class_docstring_example(monkeypatch):
    def route(request):
        if request.url.path == "/v1/athletes":
            return _json(request, LIVE["athlete"], 201)
        assert request.url.path == "/v1/nutrition/calculate"
        assert json.loads(request.content) == {
            "athlete_id": LIVE["athlete"]["id"], "activity_type": "run", "duration_min": 90,
            "intensity_level": 5, "thermal_stress_level": 6, "meal_before_min": 120, "is_race": False,
        }
        return _json(request, LIVE["calculate_exact"])

    # The class docstring snippet is a fragment: it uses Saturday without
    # importing it, so seed the name as the surrounding docs do.
    namespace, _ = _run(monkeypatch, _docstring_code(saturday.Saturday), route,
                        "client docstring example", namespace={"Saturday": saturday.Saturday})
    try:
        assert namespace["athlete"] == LIVE["athlete"]
        assert namespace["plan"] == LIVE["calculate_exact"]
    finally:
        namespace["client"].close()


def test_coach_resource_docstring_example(monkeypatch):
    from saturday.client import _CoachResource
    from test_api_surface import COACH_DIGEST

    def route(request):
        if request.method == "GET":
            assert request.url.path == "/v1/coach/roster/digest"
            assert dict(request.url.params) == {"window": "7"}
            return _json(request, COACH_DIGEST)
        assert request.url.path == "/v1/coach/config/preset"
        return _json(request, {})

    namespace, seen = _run(monkeypatch, _docstring_code(_CoachResource), route,
                           "coach resource docstring example", namespace={"Saturday": saturday.Saturday})
    try:
        assert namespace["digest"] == COACH_DIGEST
        assert json.loads(seen[1].content) == {"scope": "overall", "scope_id": None, "preset": "balanced"}
    finally:
        namespace["client"].close()
