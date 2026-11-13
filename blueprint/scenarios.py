"""Scenario loader: a signed-off OEM baseline plus a simulated vendor contract,
checklists and planted-gap answer key, kept in data/scenarios/<name>/.

Unlike data/samples/, a scenario's baseline comes from real manuals. It is stored
as a reviewed task list (proposed_baseline.json), standing in for the person who
signs it off on the Baseline page, so scoring doesn't depend on a fresh extraction.
The vendor side is invented and labelled SIMULATED.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from blueprint.config import ROOT
from blueprint.models import Document, Finding, Interval, MaintenanceTask, SourceKind
from blueprint.pipeline import Blueprint
from blueprint.tickets import parse_csv

SCENARIO_DIR = ROOT / "data" / "scenarios"


def scenario_path(name: str) -> Path:
    return SCENARIO_DIR / name


def answer_key(name: str) -> dict:
    return json.loads((scenario_path(name) / "planted_gaps.json").read_text())


def baseline_tasks(name: str) -> tuple[str, list[MaintenanceTask]]:
    data = json.loads((scenario_path(name) / "proposed_baseline.json").read_text())
    tasks = [
        MaintenanceTask(
            asset_id=data["asset_id"],
            component=t["component"],
            action=t["action"],
            spec=t.get("spec"),
            intervals=[Interval(**i) for i in t["intervals"]],
            source_quote=t["source_quote"],
            page=t["page"],
            safety_critical=t.get("safety_critical", False),
            review_note=("PLACEHOLDER engine manual. " if t.get("placeholder") else "") + f"Source: {t['source']}",
        )
        for t in data["tasks"]
    ]
    return data["asset_id"], tasks


def load_scenario(bp: Blueprint, name: str, *, sign_off: bool = True) -> list[Finding]:
    """Load the baseline, ingest the simulated contract (LLM extraction) and checklists, then analyze."""
    folder = scenario_path(name)
    key = answer_key(name)
    asset_id, tasks = baseline_tasks(name)
    raw = (folder / "proposed_baseline.json").read_bytes()
    doc = Document(
        doc_id="baseline-" + hashlib.sha256(raw).hexdigest()[:12],
        filename=f"{name} proposed baseline",
        kind=SourceKind.OEM,
        asset_id=asset_id,
    )
    if doc.doc_id not in {d.doc_id for d in bp.db.documents()}:
        bp.db.add_document(doc, tasks)

    contract = folder / "vendor_contract_SIMULATED.txt"
    bp.ingest(contract.name, contract.read_bytes(), kind=SourceKind.VENDOR, asset_id=asset_id,
              vendor=key["vendor"], is_sample=True)
    bp.db.delete_tickets(asset_id, samples_only=True)
    bp.add_tickets(parse_csv((folder / "tickets_SIMULATED.csv").read_bytes(), is_sample=True))

    if sign_off:
        bp.approve_baseline(doc.doc_id)
    return bp.analyze(asset_id)
