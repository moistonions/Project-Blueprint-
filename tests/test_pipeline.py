"""End-to-end pipeline on the synthetic generator sample, with the LLM calls faked.

The fake extraction returns what a correct extraction of the sample files looks
like, so these tests score the deterministic engine against the planted gaps.
(`scripts/load_samples.py` runs the same scoring with real LLM extraction.)
"""

import hashlib

import pytest

from blueprint.config import Settings
from blueprint.models import BaselineStatus, ExtractedTask, ExtractionResult, ExtraWorkStatus, SourceKind
from blueprint.pipeline import Blueprint
from blueprint.rationale import _Draft
from blueprint.samples import SAMPLE_ASSET, load_samples, score
from blueprint.stores.structured import StructuredStore
from blueprint.stores.vector import ChromaStore
from tests.helpers import task

A = SAMPLE_ASSET
OEM_TASKS = [
    task("engine oil and oil filter", "replace", (250, "hours"), (6, "months"), parts=["SG-OF-10"], spec="SAE 15W-40", asset=A),
    task("fuel filter", "replace", (500, "hours"), (12, "months"), parts=["SG-FF-20"], asset=A),
    task("air filter element", "replace", (500, "hours"), (12, "months"), parts=["SG-AF-30"], asset=A),
    task("engine coolant", "replace", (3000, "hours"), (24, "months"), spec="ELC 50/50", asset=A),
    task("drive belt tension", "inspect", (250, "hours"), (6, "months"), asset=A),
    task("starting battery and charger", "inspect", (3, "months"), asset=A),
    task("emergency stop and shutdown safety devices", "test", (6, "months"), asset=A),
    task("load bank", "test", (12, "months"), asset=A),
    task("alternator winding insulation resistance", "test", (12, "months"), asset=A),
    task("crankcase breather filter", "replace", (1000, "hours"), parts=["SG-BF-40"], asset=A),
    task("exhaust system", "inspect", (250, "hours"), (6, "months"), asset=A),
]
VENDOR_TASKS = [
    task("engine oil and oil filter", "change", (250, "hours"), (6, "months"), parts=["SG-OF-10"], spec="SAE 10W-30", asset=A),
    task("fuel filter", "change", (525, "hours"), (12, "months"), parts=["SG-FF-20"], asset=A),
    task("air filter element", "change", (750, "hours"), (12, "months"), parts=["SG-AF-30"], asset=A),
    task("coolant", "replace", (3000, "hours"), (36, "months"), spec="ELC 50/50", asset=A),
    task("drive belt tension", "check", (250, "hours"), (6, "months"), asset=A),
    task("starting battery and charger", "check", (1, "months"), asset=A),
    task("e-stop and shutdown safety devices", "test", (27, "weeks"), asset=A),
    task("crankcase breather filter", "replace", (1000, "hours"), parts=["SG-BF-41"], asset=A),
    task("exhaust system", "inspect", (250, "hours"), (6, "months"), asset=A),
    task("radiator fins", "clean", (3, "months"), asset=A),
]


class FakeEmbedder:
    """Bag-of-words hashing embedder: deterministic, offline, good enough for retrieval tests."""

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 64
            for w in t.lower().split():
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1
            out.append(v if any(v) else [1.0] + [0.0] * 63)
        return out


class FakeLLM:
    def __init__(self):
        self.rationale_prompts = []
        self.extraction_calls = 0

    def parse(self, *, model, system, user, schema):
        if schema is ExtractionResult:
            self.extraction_calls += 1
            src = OEM_TASKS if "NOT A REAL OEM MANUAL" in user else VENDOR_TASKS
            return ExtractionResult(tasks=[ExtractedTask(**t.model_dump(exclude={"id", "safety_critical"})) for t in src])
        if schema is _Draft:
            self.rationale_prompts.append(user)
            if "radiator" in user.splitlines()[0]:  # the deviation line, not the evidence
                quote = "Quarry site with heavy dust; radiator fins were half blocked"
                return _Draft(rationale="Dust", status="justified", conditions=["dust"], quotes=[quote], confidence=0.9)
            # Claims a reason but cites a quote that isn't in the evidence -> must become unconfirmed.
            return _Draft(rationale="Probably heat", status="justified", quotes=["invented quote"], confidence=0.7)
        raise AssertionError(schema)

    def complete(self, *, model, system, user):
        return "answer [1]"


@pytest.fixture
def bp(tmp_path):
    settings = Settings(anthropic_api_key="test", data_dir=tmp_path)
    return Blueprint(settings, FakeLLM(), StructuredStore(":memory:"), ChromaStore(None, FakeEmbedder(), collection=tmp_path.name))


def test_all_planted_gaps_found_with_no_false_alarms(bp):
    result = score(load_samples(bp))
    assert [g["id"] for g in result["missed"]] == []
    assert [f.message for f in result["false_alarms"]] == []
    assert len(result["found"]) == 10


def test_vendor_extras_are_explained_not_flagged(bp):
    findings = load_samples(bp)
    info = sorted((f.type.value, f.task_key.split("|")[0]) for f in findings if f.severity.value == "info")
    assert info == [("tightened_interval", "battery charger starting"), ("vendor_addition", "fin radiator")]
    assert any("Quarry site" in p for p in bp.llm.rationale_prompts)  # ticket notes reached the agent

    rats = {r.task_key.split("|")[0]: r for r in bp.db.rationales(SAMPLE_ASSET)}
    radiator, battery = rats["fin radiator"], rats["battery charger starting"]
    assert radiator.confirmed and radiator.status == ExtraWorkStatus.JUSTIFIED and radiator.evidence
    assert not battery.confirmed and battery.status == ExtraWorkStatus.UNKNOWN and battery.evidence == []


def test_nothing_is_compared_until_baseline_is_approved(bp):
    assert load_samples(bp, sign_off=False) == []
    oem_doc = bp.db.documents(SourceKind.OEM)[0]
    assert oem_doc.baseline_status == BaselineStatus.DRAFT
    bp.approve_baseline(oem_doc.doc_id)
    assert bp.analyze(SAMPLE_ASSET)


def test_editing_baseline_sends_it_back_to_draft(bp):
    load_samples(bp)
    doc = bp.db.documents(SourceKind.OEM)[0]
    bp.db.replace_document_tasks(doc.doc_id, bp.db.document_tasks(doc.doc_id))
    assert bp.db.documents(SourceKind.OEM)[0].baseline_status == BaselineStatus.DRAFT


def test_reload_is_idempotent_and_keeps_signoff(bp):
    first = load_samples(bp)
    calls = bp.llm.extraction_calls
    second = load_samples(bp, sign_off=False)
    assert bp.llm.extraction_calls == calls  # same files are not re-extracted
    assert len(second) == len(first)
    assert len(bp.db.documents()) == 2
    assert len(bp.vectors.query("x", k=100, where={"type": "finding"})) == len(first)


def test_usage_rate_from_tickets(bp):
    load_samples(bp)
    assert 29 < bp.usage_rate(SAMPLE_ASSET) < 31


def test_findings_and_rationales_are_searchable(bp):
    load_samples(bp)
    assert bp.vectors.query("coolant", k=20, where={"type": "finding"})
    assert bp.vectors.query("radiator", k=20, where={"type": "rationale"})
    assert bp.ask("why clean radiator fins", SAMPLE_ASSET).sources


def test_field_documents_are_not_sent_for_extraction(bp):
    _, n_tasks, n_chunks = bp.ingest("log.txt", b"pump ran hot", kind=SourceKind.FIELD, asset_id="X")
    assert n_tasks == 0 and n_chunks == 1
