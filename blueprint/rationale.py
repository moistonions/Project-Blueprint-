"""LLM agent that explains why a vendor does more than the OEM requires.

For each vendor addition or tightened interval, it searches field documents
(service logs, work orders, emails) for evidence, then asks the model to state
the operating rationale and cite it. When nothing in the evidence explains the
deviation, it says so instead of guessing, which flags a knowledge gap to fill.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from blueprint.llm import LLM
from blueprint.models import Finding, FindingType, Rationale
from blueprint.stores.vector import Hit, VectorStore

RATIONALE_TYPES = {FindingType.VENDOR_ADDITION, FindingType.TIGHTENED_INTERVAL}

_SYSTEM = """You are a reliability engineer documenting why a maintenance vendor deviates from the
OEM schedule by doing MORE maintenance than required. Use only the evidence excerpts provided.

- If the evidence explains the deviation, summarise the operating rationale in one or two sentences,
  list the site conditions involved (e.g. heavy load, dust, high ambient temperature, duty cycle),
  and copy the supporting sentences verbatim into evidence.
- If the evidence does not explain it, set explained=false, leave conditions and evidence empty,
  and say what information is missing.
- confidence is 0-1: how directly the evidence supports the rationale."""


class _Draft(BaseModel):
    explained: bool
    rationale: str
    conditions: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


def _gather_evidence(store: VectorStore, finding: Finding, k: int) -> list[Hit]:
    task = finding.vendor_task or finding.oem_task
    assert task is not None
    queries = [
        f"why {task.action} {task.component} more often",
        f"{task.component} wear failure condition",
    ]
    hits: dict[str, Hit] = {}
    for q in queries:
        for kind in ("field", "vendor"):
            for h in store.query(q, k=k, where={"asset_id": finding.asset_id, "kind": kind}):
                if h.id not in hits or h.score > hits[h.id].score:
                    hits[h.id] = h
    return sorted(hits.values(), key=lambda h: h.score, reverse=True)[:k]


def explain(llm: LLM, store: VectorStore, finding: Finding, *, model: str, k: int = 6) -> Rationale:
    hits = _gather_evidence(store, finding, k)
    evidence = "\n\n".join(
        f"[{h.metadata.get('filename', '?')} p.{h.metadata.get('page', '?')}]\n{h.text}" for h in hits
    ) or "(no field documents found for this asset)"
    user = f"Deviation: {finding.message}\n\nEvidence excerpts:\n{evidence}"
    draft = llm.parse(model=model, system=_SYSTEM, user=user, schema=_Draft)
    return Rationale(
        asset_id=finding.asset_id,
        vendor=finding.vendor,
        task_key=finding.task_key,
        rationale=draft.rationale if draft.explained else f"UNDOCUMENTED: {draft.rationale}",
        conditions=draft.conditions,
        evidence=draft.evidence,
        confidence=draft.confidence if draft.explained else 0.0,
    )
