"""Panda 60i scenario: proposed baseline from the real manuals, simulated vendor side.

The vendor contract extraction is faked with vendor_expected_tasks.json (what a
correct extraction of the contract returns), so this scores the deterministic
engine against the planted gaps. scripts/score_scenario.py runs it with real LLM extraction.
"""

import json

import pytest

from blueprint.config import Settings
from blueprint.models import ExtractedTask, ExtractionResult, Interval
from blueprint.pipeline import Blueprint
from blueprint.rationale import _Draft
from blueprint.samples import score
from blueprint.scenarios import answer_key, load_scenario, scenario_path
from blueprint.stores.structured import StructuredStore
from blueprint.stores.vector import ChromaStore
from tests.test_pipeline import FakeEmbedder

NAME = "panda-60i"


class ContractLLM:
    def parse(self, *, model, system, user, schema):
        if schema is ExtractionResult:
            rows = json.loads((scenario_path(NAME) / "vendor_expected_tasks.json").read_text())
            return ExtractionResult(tasks=[
                ExtractedTask(asset_id="PANDA-60I", component=r["component"], action=r["action"], spec=r["spec"],
                              intervals=[Interval(**i) for i in r["intervals"]])
                for r in rows
            ])
        if schema is _Draft:
            return _Draft(rationale="n/a", status="unknown", confidence=0)
        raise AssertionError(schema)

    def complete(self, **_):
        return ""


@pytest.fixture
def bp(tmp_path):
    settings = Settings(anthropic_api_key="test", data_dir=tmp_path)
    return Blueprint(settings, ContractLLM(), StructuredStore(":memory:"),
                     ChromaStore(None, FakeEmbedder(), collection=tmp_path.name))


def test_panda_planted_gaps_found_with_no_false_alarms(bp):
    findings = load_scenario(bp, NAME)
    result = score(findings, answer_key(NAME))
    assert [g["id"] for g in result["missed"]] == []
    assert [f.message for f in result["false_alarms"]] == []
    assert len(result["found"]) == 10


def test_panda_vendor_extras_reported_as_info(bp):
    findings = load_scenario(bp, NAME)
    info = sorted((f.type.value, (f.vendor_task or f.oem_task).component) for f in findings if f.severity.value == "info")
    assert info == [("tightened_interval", "starter battery"), ("vendor_addition", "exhaust mixing elbow")]


def test_panda_nothing_compared_before_sign_off(bp):
    assert load_scenario(bp, NAME, sign_off=False) == []
