"""LLM agent that explains why a vendor does more than the OEM requires.

For each vendor addition or tightened interval, Claude runs as a tool-using
agent: it decides what to search for in ticket notes, field reports and vendor
documents, can look up the OEM requirement, and finishes by submitting a reason
with verbatim quotes (explain_with_agent). Models without tool support use the
fixed chain instead: two preset searches, then one structured call. Quotes are checked against the retrieved text; a
reason without a verified quote is stored as "unconfirmed". Each piece of extra
work also gets a status (justified / unjustified / unknown) for display. The
POC does not build an approval flow on top of it.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from blueprint.llm import LLM, Tool
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


_AGENT_SYSTEM = """You are a reliability engineer documenting why a maintenance vendor does MORE maintenance
than the OEM requires. You have tools to search the asset's field notes (vendor checklist notes, field
reports, emails) and vendor documents, and to look up the OEM requirement.

How to work:
- Start by searching the field notes for the task, then try other wording or the vendor documents if
  nothing useful comes back. Use at most 4 searches; stop as soon as you have evidence or clearly have none.
- Finish by calling submit_rationale exactly once:
  - rationale: the operating reason in one or two sentences, or what information is missing.
  - conditions: site conditions involved (e.g. heavy load, dust, high ambient temperature, duty cycle).
  - quotes: sentences copied EXACTLY, character for character, from the search results. Empty if none.
  - status: "justified" if the evidence gives a concrete site or failure reason, "unjustified" if it shows
    the extra work is not needed, "unknown" if it says nothing either way.
  - confidence 0-1: how directly the quotes support the rationale.
- Only use what the tools return. Never invent evidence.

"""
_AGENT_SYSTEM += UNTRUSTED_RULE
MAX_SEARCHES = 4


def explain(llm: LLM, store: VectorStore, finding: Finding, *, model: str, k: int = 6) -> Rationale:
    """Explain a vendor deviation: tool-using agent where the LLM supports it, else the fixed chain."""
    if hasattr(llm, "run_agent"):
        result = explain_with_agent(llm, store, finding, model=model)
        if result is not None:
            return result
    return explain_with_chain(llm, store, finding, model=model, k=k)


def explain_with_agent(llm, store: VectorStore, finding: Finding, *, model: str, k: int = 4) -> Rationale | None:
    """Let the model choose its searches. Returns None if it never submitted (caller falls back)."""
    seen: dict[str, Hit] = {}
    trace: list[str] = []
    submitted: list[_Draft] = []
    searches = [0]

    def search(kind: str, label: str):
        """Make a search tool over one kind of indexed text (field notes or vendor documents)."""
        def run(args: dict) -> str:
            """Run the search, enforce the search cap, remember hits for quote checking, return wrapped results."""
            query = str(args.get("query", "")).strip()[:200]
            if searches[0] >= MAX_SEARCHES:
                trace.append(f'{label}("{query}") refused: search limit reached')
                return "Search limit reached. Call submit_rationale now with what you have."
            searches[0] += 1
            hits = store.query(query, k=k, where={"asset_id": finding.asset_id, "kind": kind}) if query else []
            for h in hits:
                if h.id not in seen or h.score > seen[h.id].score:
                    seen[h.id] = h
            trace.append(f'{label}("{query}") → {len(hits)} result(s)')
            if not hits:
                return "No results."
            body = "\n\n".join(f"[{h.metadata.get('filename', '?')} p.{h.metadata.get('page', '?')}]\n{h.text}"
                               for h in hits)
            return wrap("evidence", body)
        return run

    def oem_requirement(_: dict) -> str:
        """Tool: return the OEM requirement and the vendor's version of the task."""
        trace.append("get_oem_requirement()")
        o, v = finding.oem_task, finding.vendor_task
        oem = (f"OEM: {o.action} {o.component}, intervals {[f'{i.value:g} {i.unit.value}' for i in o.intervals]}"
               f"; quote: {o.source_quote}") if o else "OEM: the OEM schedule has no such task."
        ven = (f"Vendor: {v.action} {v.component}, intervals {[f'{i.value:g} {i.unit.value}' for i in v.intervals]}"
               if v else "Vendor: n/a")
        return wrap("evidence", f"{oem}\n{ven}")

    def submit(args: dict) -> str:
        """Tool: record the agent's final rationale draft (verified against the evidence afterwards)."""
        submitted.append(_Draft(
            rationale=str(args.get("rationale", "")),
            status=args.get("status", "unknown"),
            conditions=[str(c) for c in args.get("conditions", [])],
            quotes=[str(q) for q in args.get("quotes", [])],
            confidence=min(max(float(args.get("confidence", 0) or 0), 0.0), 1.0),
        ))
        trace.append(f"submit_rationale(status={submitted[-1].status.value})")
        return "Recorded."

    query_prop = {"query": {"type": "string", "description": "What to look for, in plain words"}}
    tools = [
        Tool("search_field_notes", "Search this asset's vendor checklist notes, field reports and emails.",
             query_prop, search("field", "search_field_notes")),
        Tool("search_vendor_documents", "Search this asset's vendor contract and schedule documents.",
             query_prop, search("vendor", "search_vendor_documents")),
        Tool("get_oem_requirement", "Get the OEM requirement and the vendor's version of this task.",
             {}, oem_requirement),
        Tool("submit_rationale", "Submit the final rationale. Call exactly once, at the end.", {
            "rationale": {"type": "string"},
            "status": {"type": "string", "enum": [s.value for s in ExtraWorkStatus]},
            "conditions": {"type": "array", "items": {"type": "string"}},
            "quotes": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
        }, submit, ends_run=True),
    ]
    user = f"Deviation to explain: {finding.message}\nAsset: {finding.asset_id}. Vendor: {finding.vendor or 'n/a'}."
    llm.run_agent(model=model, system=_AGENT_SYSTEM, user=user, tools=tools)
    if not submitted:
        return None
    return _finish(finding, submitted[-1], list(seen.values()), method="agent", trace=trace)


def _finish(finding: Finding, draft: _Draft, hits: list[Hit], *, method: str, trace: list[str]) -> Rationale:
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
        method=method,
        trace=trace,
    )


def explain_with_chain(llm: LLM, store: VectorStore, finding: Finding, *, model: str, k: int = 6) -> Rationale:
    """Fixed prompt chain: two preset searches, then one structured LLM call."""
    hits = _gather_evidence(store, finding, k)
    evidence = "\n\n".join(
        f"[{h.metadata.get('filename', '?')} p.{h.metadata.get('page', '?')}]\n{h.text}" for h in hits
    ) or "(no field documents or tickets found for this asset)"
    user = f"Deviation: {finding.message}\n\nEvidence excerpts:\n{wrap('evidence', evidence)}"
    draft = llm.parse(model=model, system=_SYSTEM, user=user, schema=_Draft)

    return _finish(finding, draft, hits, method="chain", trace=[])
