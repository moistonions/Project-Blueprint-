"""Question answering over indexed documents, findings and rationales."""

from __future__ import annotations

from dataclasses import dataclass

from blueprint.llm import LLM
from blueprint.stores.vector import Hit, Metadata, VectorStore

_SYSTEM = """You answer questions from field engineers and maintenance leads about equipment maintenance,
OEM requirements, vendor schedules, compliance gaps and the reasons behind vendor deviations.

Answer only from the numbered context. Cite sources inline like [1] or [2]. If the context does not
contain the answer, say so plainly and suggest which document would need to be uploaded."""


@dataclass
class Answer:
    text: str
    sources: list[Hit]


def source_label(h: Hit) -> str:
    m = h.metadata
    if m.get("type") == "finding":
        return f"Gap finding · {m.get('asset_id')} · {m.get('vendor') or 'n/a'}"
    if m.get("type") == "rationale":
        return f"Vendor rationale · {m.get('asset_id')} · {m.get('vendor') or 'n/a'}"
    return f"{m.get('filename', '?')} p.{m.get('page', '?')} ({m.get('kind', '?')})"


def ask(llm: LLM, store: VectorStore, question: str, *, model: str, asset_id: str | None = None, k: int = 8) -> Answer:
    where: Metadata | None = {"asset_id": asset_id} if asset_id else None
    hits = store.query(question, k=k, where=where)
    if not hits:
        return Answer("Nothing has been indexed yet for this scope. Upload documents first.", [])
    context = "\n\n".join(f"[{i}] {source_label(h)}\n{h.text}" for i, h in enumerate(hits, 1))
    text = llm.complete(model=model, system=_SYSTEM, user=f"Context:\n{context}\n\nQuestion: {question}")
    return Answer(text, hits)
