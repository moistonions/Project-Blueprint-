"""Orchestrates ingest -> extract -> sign-off -> compare -> explain -> index."""

from __future__ import annotations

import hashlib
from datetime import date

from blueprint import rag, rationale
from blueprint.config import Settings
from blueprint.execution import HourMeter, check_execution
from blueprint.extract import extract_tasks
from blueprint.ingest import chunk_pages, read_pages
from blueprint.llm import LLM
from blueprint.models import BaselineStatus, Document, Finding, Rationale, SourceKind, Ticket
from blueprint.rules import compare
from blueprint.stores.structured import StructuredStore
from blueprint.stores.vector import Record, VectorStore
from blueprint.tickets import ticket_text


class Blueprint:
    def __init__(self, settings: Settings, llm: LLM, structured: StructuredStore, vectors: VectorStore):
        self.settings = settings
        self.llm = llm
        self.db = structured
        self.vectors = vectors

    @classmethod
    def from_settings(cls, settings: Settings) -> Blueprint:
        from blueprint.llm import make_embedder, make_llm
        from blueprint.stores.vector import make_vector_store

        llm = make_llm(settings)
        return cls(
            settings,
            llm,
            StructuredStore(settings.sqlite_path),
            make_vector_store(settings.vector_backend, settings.chroma_path, make_embedder(settings, llm)),
        )

    # ------------------------------------------------------------------ ingest
    def ingest(
        self,
        filename: str,
        data: bytes,
        *,
        kind: SourceKind,
        asset_id: str,
        vendor: str | None = None,
        is_sample: bool = False,
    ) -> tuple[Document, int, int]:
        """Store and index one document. Returns (document, tasks_extracted, chunks_indexed).

        Uploading the same file again for the same asset is a no-op, so a signed-off
        baseline isn't thrown away by a repeat upload.
        """
        doc_id = hashlib.sha256(data + asset_id.encode()).hexdigest()[:16]
        for existing in self.db.documents():
            if existing.doc_id == doc_id:
                return existing, len(self.db.document_tasks(doc_id)), 0

        doc = Document(
            doc_id=doc_id, filename=filename, kind=kind, asset_id=asset_id, vendor=vendor, is_sample=is_sample
        )
        pages = read_pages(filename, data)
        if not any(p.text.strip() for p in pages):
            raise ValueError(f"No text found in {filename}. Scanned PDFs need OCR before upload.")

        tasks = []
        if kind in (SourceKind.OEM, SourceKind.VENDOR):
            tasks = extract_tasks(
                self.llm, model=self.settings.extraction_model, pages=pages, kind=kind, asset_id=asset_id
            )
        self.db.add_document(doc, tasks)

        chunks = chunk_pages(pages)
        self.vectors.upsert(
            [
                Record(
                    id=f"{doc.doc_id}:{c.index}",
                    text=c.text,
                    metadata={
                        "type": "chunk",
                        "doc_id": doc.doc_id,
                        "filename": filename,
                        "kind": kind.value,
                        "asset_id": asset_id,
                        "vendor": vendor or "",
                        "page": c.page,
                        "is_sample": is_sample,
                    },
                )
                for c in chunks
            ]
        )
        return doc, len(tasks), len(chunks)

    def add_tickets(self, tickets: list[Ticket]) -> None:
        """Store vendor checklist lines; their notes become searchable field evidence."""
        self.db.add_tickets(tickets)
        self.vectors.upsert(
            [
                Record(
                    id="ticket:" + hashlib.sha256(t.model_dump_json().encode()).hexdigest()[:16],
                    text=ticket_text(t),
                    metadata={
                        "type": "ticket",
                        "kind": "field",
                        "filename": f"checklist {t.date}",
                        "asset_id": t.asset_id,
                        "vendor": t.vendor or "",
                        "is_sample": t.is_sample,
                    },
                )
                for t in tickets
            ]
        )

    def approve_baseline(self, doc_id: str) -> None:
        self.db.set_baseline_status(doc_id, BaselineStatus.APPROVED)

    def usage_rate(self, asset_id: str) -> float | None:
        """Running hours per month, from vendor checklist meter readings."""
        return HourMeter(self.db.tickets(asset_id)).usage_rate()

    # ------------------------------------------------------------------ analyze
    def analyze(self, asset_id: str, *, explain: bool = True, as_of: date | None = None) -> list[Finding]:
        """Run the deterministic checks for every vendor of an asset, then capture rationales.

        Only approved OEM baselines are compared. With none approved, nothing runs.
        """
        oem = self.db.tasks(asset_id, SourceKind.OEM, approved_only=True)
        findings: list[Finding] = []
        if oem:
            tol = self.settings.tolerance
            for vendor in self.db.vendors(asset_id):
                findings += compare(
                    oem,
                    self.db.tasks(asset_id, SourceKind.VENDOR, vendor),
                    asset_id=asset_id,
                    vendor_name=vendor,
                    tolerance=tol,
                )
            findings += check_execution(
                oem, self.db.tickets(asset_id), asset_id=asset_id, vendor_name=None, tolerance=tol, as_of=as_of
            )
        self.db.replace_findings(asset_id, findings)
        self._index_findings(asset_id, findings)
        if explain:
            for f in findings:
                if f.type in rationale.RATIONALE_TYPES:
                    self._capture_rationale(f)
        return findings

    def _index_findings(self, asset_id: str, findings: list[Finding]) -> None:
        self.vectors.delete({"type": "finding", "asset_id": asset_id})
        self.vectors.upsert(
            [
                Record(
                    id=f"finding:{asset_id}:{i}",
                    text=f"[{f.severity.value.upper()} {f.type.value}] {f.message}",
                    metadata={
                        "type": "finding",
                        "asset_id": asset_id,
                        "vendor": f.vendor or "",
                        "severity": f.severity.value,
                        "finding_type": f.type.value,
                    },
                )
                for i, f in enumerate(findings)
            ]
        )

    def _capture_rationale(self, finding: Finding) -> Rationale:
        r = rationale.explain(self.llm, self.vectors, finding, model=self.settings.agent_model)
        self.db.add_rationale(r)
        label = "Rationale" if r.confirmed else "Rationale (unconfirmed)"
        text = f"{finding.message}\n{label}: {r.rationale}\nStatus: {r.status.value}"
        if r.conditions:
            text += f"\nConditions: {', '.join(r.conditions)}"
        if r.evidence:
            text += "\nSource quotes: " + " | ".join(f'"{q}"' for q in r.evidence)
        self.vectors.upsert(
            [
                Record(
                    id=f"rationale:{r.asset_id}:{r.vendor}:{r.task_key}",
                    text=text,
                    metadata={
                        "type": "rationale",
                        "asset_id": r.asset_id,
                        "vendor": r.vendor or "",
                        "confidence": r.confidence,
                        "status": r.status.value,
                    },
                )
            ]
        )
        return r

    # ------------------------------------------------------------------ chat
    def ask(self, question: str, asset_id: str | None = None) -> rag.Answer:
        return rag.ask(self.llm, self.vectors, question, model=self.settings.chat_model, asset_id=asset_id)
