"""Every response the live suite recorded (tests/fixtures/live.json) matches the TypedDict its
method returns: every required key present, no key the type does not declare, every value of
its declared type. A change to the API fails here until the types match."""

import importlib
import json
from pathlib import Path

import pytest

from test_contracts import matches

CAPTURED = json.loads(Path(__file__).with_name("fixtures").joinpath("live.json").read_text())


def test_recording_covers_the_main_flows():
    assert len(CAPTURED) > 40


@pytest.mark.parametrize("name", sorted(CAPTURED))
def test_recorded_response_matches_its_type(name):
    entry = CAPTURED[name]
    if entry["type"] == "Dict":
        assert isinstance(entry["body"], dict)
        return
    model = getattr(importlib.import_module("saturday.types"), entry["type"])
    assert matches(entry["body"], model), f"{name} does not match {entry['type']}"
