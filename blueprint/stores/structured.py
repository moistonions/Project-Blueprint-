"""SQLite store for documents, extracted tasks, findings and rationales."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from blueprint.models import Document, Finding, MaintenanceTask, Rationale, SourceKind

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    kind TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    vendor TEXT,
    is_sample INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    vendor TEXT,
    type TEXT NOT NULL,
    severity TEXT NOT NULL,
    task_key TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS rationales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id TEXT NOT NULL,
    vendor TEXT,
    task_key TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tasks_asset ON tasks(asset_id);
CREATE INDEX IF NOT EXISTS idx_findings_asset ON findings(asset_id, vendor);
"""


class StructuredStore:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)

    # documents / tasks -------------------------------------------------
    def add_document(self, doc: Document, tasks: list[MaintenanceTask]) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc.doc_id,))
            self._conn.execute(
                "INSERT INTO documents (doc_id, filename, kind, asset_id, vendor, is_sample) VALUES (?,?,?,?,?,?)",
                (doc.doc_id, doc.filename, doc.kind.value, doc.asset_id, doc.vendor, int(doc.is_sample)),
            )
            self._conn.executemany(
                "INSERT INTO tasks (doc_id, asset_id, data) VALUES (?,?,?)",
                [(doc.doc_id, t.asset_id, t.model_dump_json()) for t in tasks],
            )

    def documents(self) -> list[Document]:
        rows = self._conn.execute(
            "SELECT doc_id, filename, kind, asset_id, vendor, is_sample FROM documents ORDER BY created_at"
        ).fetchall()
        return [
            Document(doc_id=r[0], filename=r[1], kind=SourceKind(r[2]), asset_id=r[3], vendor=r[4], is_sample=bool(r[5]))
            for r in rows
        ]

    def tasks(self, asset_id: str, kind: SourceKind, vendor: str | None = None) -> list[MaintenanceTask]:
        sql = (
            "SELECT t.data FROM tasks t JOIN documents d ON d.doc_id = t.doc_id "
            "WHERE t.asset_id = ? AND d.kind = ?"
        )
        args: list = [asset_id, kind.value]
        if vendor is not None:
            sql += " AND d.vendor = ?"
            args.append(vendor)
        return [MaintenanceTask.model_validate_json(r[0]) for r in self._conn.execute(sql, args)]

    def assets(self) -> list[str]:
        return [r[0] for r in self._conn.execute("SELECT DISTINCT asset_id FROM documents ORDER BY asset_id")]

    def vendors(self, asset_id: str) -> list[str]:
        """Vendors with a schedule on file for this asset."""
        rows = self._conn.execute(
            "SELECT DISTINCT vendor FROM documents WHERE asset_id = ? AND kind = 'vendor' ORDER BY vendor",
            (asset_id,),
        )
        return [r[0] for r in rows]

    # findings / rationales ---------------------------------------------
    def replace_findings(self, asset_id: str, vendor: str | None, findings: list[Finding]) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM findings WHERE asset_id = ? AND vendor IS ?", (asset_id, vendor))
            self._conn.executemany(
                "INSERT INTO findings (asset_id, vendor, type, severity, task_key, data) VALUES (?,?,?,?,?,?)",
                [(f.asset_id, f.vendor, f.type.value, f.severity.value, f.task_key, f.model_dump_json()) for f in findings],
            )

    def findings(self, asset_id: str | None = None) -> list[Finding]:
        sql, args = "SELECT data FROM findings", []
        if asset_id:
            sql, args = sql + " WHERE asset_id = ?", [asset_id]
        return [Finding.model_validate_json(r[0]) for r in self._conn.execute(sql + " ORDER BY id", args)]

    def add_rationale(self, r: Rationale) -> None:
        with self._conn:
            self._conn.execute(
                "DELETE FROM rationales WHERE asset_id = ? AND vendor IS ? AND task_key = ?",
                (r.asset_id, r.vendor, r.task_key),
            )
            self._conn.execute(
                "INSERT INTO rationales (asset_id, vendor, task_key, data) VALUES (?,?,?,?)",
                (r.asset_id, r.vendor, r.task_key, r.model_dump_json()),
            )

    def rationales(self, asset_id: str | None = None) -> list[Rationale]:
        sql, args = "SELECT data FROM rationales", []
        if asset_id:
            sql, args = sql + " WHERE asset_id = ?", [asset_id]
        return [Rationale.model_validate_json(r[0]) for r in self._conn.execute(sql + " ORDER BY id", args)]
