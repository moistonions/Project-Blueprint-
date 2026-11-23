"""LLM agent that explains why a vendor does more than the OEM requires.

For each vendor addition or tightened interval, it searches ticket notes and
other field documents for evidence, then asks the model for the operating
reason with verbatim quotes. Quotes are checked against the retrieved text; a
reason without a verified quote is stored as "unconfirmed". Each piece of extra
work also gets a status (justified / unjustified / unknown) for display. The
POC does not build an approval flow on top of it.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from blueprint.llm import LLM
from blueprint.models import ExtraWorkStatus, Finding, FindingType, Rationale
from blueprint.safety import UNTRUSTED_RULE, wrap
from blueprint.stores.vector import Hit, VectorStore

RATIONALE_TYPES = {FindingType.VENDOR_ADDITION, FindingType.TIGHTENED_INTERVAL}

_SYSTEM = """You are a reliability engineer documenting why a maintenance vendor does MORE maintenance
than the OEM requires. Use only the evidence excerpts provided.

- rationale: the operating reason in one or two sentences, or what information is missing.
- conditions: site conditions involved (e.g. heavy load, dust, high ambient temperature, duty cycle).
- quotes: copy the supporting sentences from the excerpts EXACTLY, character for character.
  Leave empty if nothing in the excerpts supports the reason.
- status: "justified" if the excerpts give a concrete site or failure reason, "unjustified" if they
  show the extra work is not needed, "unknown" if they say nothing either way.
- confidence is 0-1: how directly the quotes support the rationale.

"""
_SYSTEM += UNTRUSTED_RULE


class _Draft(BaseModel):
    rationale: str
    status: ExtraWorkStatus
    conditions: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def verified_quotes(quotes: list[str], hits: list[Hit]) -> list[str]:
    """Keep only quotes that really appear in the retrieved evidence."""
    corpus = " ".join(_squash(h.text) for h in hits)
    return [q.strip() for q in quotes if q.strip() and _squash(q) in corpus]


def _gather_evidence(store: VectorStore, finding: Finding, k: int) -> list[Hit]:
    task = finding.vendor_task or finding.oem_task
    assert task is not None
    queries = [
        f"why {task.action} {task.component} more often",
        f"{task.component} wear failure condition site",
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
    ) or "(no field documents or tickets found for this asset)"
    user = f"Deviation: {finding.message}\n\nEvidence excerpts:\n{wrap('evidence', evidence)}"
    draft = llm.parse(model=model, system=_SYSTEM, user=user, schema=_Draft)

    quotes = verified_quotes(draft.quotes, hits)
    confirmed = bool(quotes)
    status = draft.status
    if not confirmed and status != ExtraWorkStatus.UNKNOWN:
        # A verdict either way needs a source; without one we don't know.
        status = ExtraWorkStatus.UNKNOWN
    return Rationale(
        asset_id=finding.asset_id,
        vendor=finding.vendor,
        task_key=finding.task_key,
        rationale=draft.rationale,
        status=status,
        confirmed=confirmed,
        conditions=draft.conditions if confirmed else [],
        evidence=quotes,
        confidence=draft.confidence if confirmed else 0.0,
    )
