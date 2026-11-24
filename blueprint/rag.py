"""Question answering over indexed documents, findings and rationales."""

from __future__ import annotations

from dataclasses import dataclass

from blueprint.llm import LLM
from blueprint.safety import UNTRUSTED_RULE, check_question, wrap
from blueprint.stores.vector import Hit, Metadata, VectorStore

_SYSTEM = """You answer questions from field engineers and maintenance leads about equipment maintenance,
OEM requirements, vendor schedules, compliance gaps and the reasons behind vendor deviations.

Answer only from the numbered context. Cite sources inline like [1] or [2]. If the context does not
contain the answer, say so plainly and suggest which document would need to be uploaded.
Only answer questions about maintenance and these assets; politely decline anything else.

"""
_SYSTEM += UNTRUSTED_RULE


@dataclass
class Answer:
    """A chat answer and the retrieved chunks it was based on."""
    text: str
    sources: list[Hit]


def source_label(h: Hit) -> str:
    """Readable label for a retrieved source, shown under the answer."""
    m = h.metadata
    if m.get("type") == "finding":
        return f"Gap finding · {m.get('asset_id')} · {m.get('vendor') or 'n/a'}"
    if m.get("type") == "rationale":
        return f"Vendor rationale · {m.get('asset_id')} · {m.get('vendor') or 'n/a'}"
    if m.get("type") == "ticket":
        return f"Vendor {m.get('filename')} · {m.get('asset_id')}"
    return f"{m.get('filename', '?')} p.{m.get('page', '?')} ({m.get('kind', '?')})"


def ask(llm: LLM, store: VectorStore, question: str, *, model: str, asset_id: str | None = None, k: int = 8) -> Answer:
    """Answer a question using only retrieved context.

    Checks the question, retrieves the top `k` chunks (optionally for one asset), numbers them,
    wraps them as untrusted data, and asks the LLM to answer with [n] citations.
    """
    question = check_question(question)
    where: Metadata | None = {"asset_id": asset_id} if asset_id else None
    hits = store.query(question, k=k, where=where)
    if not hits:
        return Answer("Nothing has been indexed yet for this scope. Upload documents first.", [])
    context = "\n\n".join(f"[{i}] {source_label(h)}\n{h.text}" for i, h in enumerate(hits, 1))
    text = llm.complete(
        model=model,
        system=_SYSTEM,
        user=f"Context:\n{wrap('document', context)}\n\nQuestion:\n{wrap('question', question)}",
    )
    return Answer(text, hits)
