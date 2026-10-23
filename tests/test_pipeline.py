"""End-to-end pipeline on the synthetic samples, with the OpenAI calls faked."""

import hashlib

import pytest

from blueprint.config import Settings
from blueprint.models import ExtractionResult, FindingType, SourceKind
from blueprint.pipeline import Blueprint
from blueprint.rationale import _Draft
from blueprint.samples import SAMPLE_ASSET, load_samples
from blueprint.stores.structured import StructuredStore
from blueprint.stores.vector import ChromaStore
from tests.helpers import task


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
    """Returns what a good extraction of the sample files would look like."""

    def __init__(self):
        self.rationale_prompts = []

    def parse(self, *, model, system, user, schema):
        if schema is ExtractionResult:
            a = SAMPLE_ASSET
            if "NOT A REAL OEM MANUAL" in user:
                tasks = [
                    task("mechanical seal kit", "replace", (8000, "hours"), (24, "months"), parts=["SK-100-01"], asset=a),
                    task("motor bearings", "lubricate", (2000, "hours"), (6, "months"), asset=a),
                    task("coupling alignment", "inspect", (12, "months"), asset=a),
                    task("suction strainer element", "replace", (4000, "hours"), asset=a),
                ]
            else:
                tasks = [
                    task("mechanical seal kit", "change", (30, "months"), parts=["SK-100-01"], asset=a),
                    task("motor bearings", "grease", (1000, "hours"), (3, "months"), asset=a),
                    task("suction strainer element", "replace", (4000, "hours"), asset=a),
                    task("impeller and volute", "clean", (6, "months"), asset=a),
                ]
            return ExtractionResult(tasks=tasks)
        if schema is _Draft:
            self.rationale_prompts.append(user)
            return _Draft(explained=True, rationale="Site conditions", conditions=["heat"], evidence=[], confidence=0.8)
        raise AssertionError(schema)

    def complete(self, *, model, system, user):
        return "answer [1]"


@pytest.fixture
def bp(tmp_path):
    settings = Settings(openai_api_key="test", data_dir=tmp_path)
    return Blueprint(settings, FakeLLM(), StructuredStore(":memory:"), ChromaStore(None, FakeEmbedder(), collection=tmp_path.name))


def test_samples_end_to_end(bp):
    findings = load_samples(bp)
    got = sorted((f.type, f.task_key.split("|")[0]) for f in findings)
    assert got == sorted([
        (FindingType.MISSING_TASK, "alignment coupling"),
        (FindingType.EXTENDED_INTERVAL, "kit mechanical seal"),
        (FindingType.MISSING_INTERVAL_BASIS, "kit mechanical seal"),
        (FindingType.TIGHTENED_INTERVAL, "bearings motor"),
        (FindingType.VENDOR_ADDITION, "impeller volute"),
    ])

    # Rationale agent ran for both "more than OEM" findings, with field-log evidence in its prompt.
    rats = bp.db.rationales(SAMPLE_ASSET)
    assert len(rats) == 2
    assert any("slurry" in p for p in bp.llm.rationale_prompts)

    # Documents are tagged as samples, and findings + rationales are searchable.
    assert all(d.is_sample for d in bp.db.documents())
    assert bp.vectors.query("seal", k=20, where={"type": "finding"})
    assert bp.vectors.query("bearings", k=20, where={"type": "rationale"})
    assert bp.ask("why grease bearings", SAMPLE_ASSET).sources


def test_reingest_and_reanalyze_is_idempotent(bp):
    first = load_samples(bp)
    second = load_samples(bp)
    assert len(bp.db.findings(SAMPLE_ASSET)) == len(first) == len(second)
    assert len(bp.db.documents()) == 3
    assert len(bp.db.rationales(SAMPLE_ASSET)) == 2
    assert len(bp.vectors.query("x", k=100, where={"type": "finding"})) == len(first)


def test_field_documents_are_not_sent_for_extraction(bp):
    _, n_tasks, n_chunks = bp.ingest("log.txt", b"pump ran hot", kind=SourceKind.FIELD, asset_id="X")
    assert n_tasks == 0 and n_chunks == 1
