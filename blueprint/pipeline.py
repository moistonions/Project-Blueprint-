"""Orchestrates ingest -> extract -> compare -> explain -> index."""

from __future__ import annotations

import hashlib

from blueprint import rag, rationale
from blueprint.config import Settings
from blueprint.extract import extract_tasks
from blueprint.ingest import chunk_pages, read_pages
from blueprint.llm import LLM
from blueprint.models import Document, Finding, Rationale, SourceKind
from blueprint.rules import compare
from blueprint.stores.structured import StructuredStore
from blueprint.stores.vector import Record, VectorStore


class Blueprint:
    def __init__(self, settings: Settings, llm: LLM, structured: StructuredStore, vectors: VectorStore):
        self.settings = settings
        self.llm = llm
        self.db = structured
        self.vectors = vectors

    @classmethod
    def from_settings(cls, settings: Settings) -> Blueprint:
        from blueprint.llm import OpenAIClient
        from blueprint.stores.vector import make_vector_store

        client = OpenAIClient(settings)
        return cls(
            settings,
            client,
            StructuredStore(settings.sqlite_path),
            make_vector_store(settings.vector_backend, settings.chroma_path, client),
        )

    # ------------------------------------------------------------------
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
        """Store and index one document. Returns (document, tasks_extracted, chunks_indexed)."""
        doc = Document(
            doc_id=hashlib.sha256(data).hexdigest()[:16],
            filename=filename,
            kind=kind,
            asset_id=asset_id,
            vendor=vendor,
            is_sample=is_sample,
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
        self.vectors.delete({"doc_id": doc.doc_id})
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

    # ------------------------------------------------------------------
    def analyze(self, asset_id: str, *, explain: bool = True) -> list[Finding]:
        """Run the deterministic gap check for every vendor of an asset, then capture rationales."""
        all_findings: list[Finding] = []
        oem = self.db.tasks(asset_id, SourceKind.OEM)
        if not oem:
            return all_findings
        for vendor in self.db.vendors(asset_id):
            findings = compare(
                oem, self.db.tasks(asset_id, SourceKind.VENDOR, vendor), asset_id=asset_id, vendor_name=vendor
            )
            self.db.replace_findings(asset_id, vendor, findings)
            self._index_findings(asset_id, vendor, findings)
            all_findings += findings
        if explain:
            for f in all_findings:
                if f.type in rationale.RATIONALE_TYPES:
                    self._capture_rationale(f)
        return all_findings

    def _index_findings(self, asset_id: str, vendor: str | None, findings: list[Finding]) -> None:
        self.vectors.delete({"type": "finding", "asset_id": asset_id, "vendor": vendor or ""})
        self.vectors.upsert(
            [
                Record(
                    id=f"finding:{asset_id}:{vendor}:{i}",
                    text=f"[{f.severity.value.upper()} {f.type.value}] {f.message}",
                    metadata={
                        "type": "finding",
                        "asset_id": asset_id,
                        "vendor": vendor or "",
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
        text = f"{finding.message}\nRationale: {r.rationale}"
        if r.conditions:
            text += f"\nConditions: {', '.join(r.conditions)}"
        if r.evidence:
            text += "\nEvidence: " + " | ".join(r.evidence)
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
                    },
                )
            ]
        )
        return r

    # ------------------------------------------------------------------
    def ask(self, question: str, asset_id: str | None = None) -> rag.Answer:
        return rag.ask(self.llm, self.vectors, question, model=self.settings.chat_model, asset_id=asset_id)
