"""Loader for the clearly labelled synthetic sample set in data/samples/.

The sample is a fictional generator with ~10 planted gaps (see planted_gaps.json)
so the engine can be scored: every planted gap found, no false alarms.
"""

from __future__ import annotations

import json

from blueprint.config import ROOT
from blueprint.models import GAP_TYPES, Finding, SourceKind
from blueprint.normalize import component_similarity
from blueprint.pipeline import Blueprint
from blueprint.tickets import parse_csv

SAMPLE_DIR = ROOT / "data" / "samples"
SAMPLE_ASSET = "SAMPLE-GEN-01"
SAMPLE_VENDOR = "Example Power Services Ltd (fictional)"


def answer_key() -> dict:
    """Planted gaps for the synthetic sample set, used to score a run."""
    return json.loads((SAMPLE_DIR / "planted_gaps.json").read_text())


def load_samples(bp: Blueprint, *, sign_off: bool = True) -> list[Finding]:
    """Ingest the sample docs and tickets, then analyze.

    With sign_off=True this also simulates the human baseline sign-off: it marks
    the answer key's safety-critical tasks and approves the OEM task list. With
    real manuals that step is done by a person on the Baseline page.
    """
    oem_doc, _, _ = bp.ingest(
        "sample_oem_generator_spec.txt", (SAMPLE_DIR / "sample_oem_generator_spec.txt").read_bytes(),
        kind=SourceKind.OEM, asset_id=SAMPLE_ASSET, is_sample=True,
    )
    bp.ingest(
        "sample_vendor_contract.txt", (SAMPLE_DIR / "sample_vendor_contract.txt").read_bytes(),
        kind=SourceKind.VENDOR, asset_id=SAMPLE_ASSET, vendor=SAMPLE_VENDOR, is_sample=True,
    )
    bp.db.delete_tickets(SAMPLE_ASSET, samples_only=True)
    bp.add_tickets(parse_csv((SAMPLE_DIR / "sample_tickets.csv").read_bytes(), is_sample=True))

    if sign_off:
        critical = answer_key()["safety_critical_components"]
        tasks = bp.db.document_tasks(oem_doc.doc_id)
        for t in tasks:
            t.safety_critical = any(component_similarity(t.component, c) >= 0.8 for c in critical)
        bp.db.replace_document_tasks(oem_doc.doc_id, tasks)
        bp.approve_baseline(oem_doc.doc_id)
    return bp.analyze(SAMPLE_ASSET)


def score(findings: list[Finding], key: dict | None = None) -> dict:
    """Compare reported gaps with the planted ones. Returns found / missed / false alarms."""
    planted = (key or answer_key())["gaps"]
    gaps = [f for f in findings if f.type in GAP_TYPES]
    used: set[int] = set()
    found, missed = [], []
    for g in planted:
        hit = next(
            (i for i, f in enumerate(gaps)
             if i not in used and f.type.value == g["type"]
             and component_similarity((f.oem_task or f.vendor_task).component, g["component"]) >= 0.8),
            None,
        )
        if hit is None:
            missed.append(g)
        else:
            used.add(hit)
            found.append((g, gaps[hit]))
    false_alarms = [f for i, f in enumerate(gaps) if i not in used]
    return {"found": found, "missed": missed, "false_alarms": false_alarms}
