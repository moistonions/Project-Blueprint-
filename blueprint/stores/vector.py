"""Vector store interface plus the Chroma implementation.

Everything outside this module talks to `VectorStore`, so swapping Chroma for
pgvector later means adding one class here and changing `make_vector_store`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from blueprint.llm import Embedder

# Metadata values must be scalars so every backend can filter on them.
Metadata = dict[str, str | int | float | bool]


@dataclass
class Record:
    id: str
    text: str
    metadata: Metadata = field(default_factory=dict)


@dataclass
class Hit:
    id: str
    text: str
    metadata: Metadata
    score: float  # higher is more similar


class VectorStore(Protocol):
    def upsert(self, records: list[Record]) -> None: ...

    def query(self, text: str, k: int = 5, where: Metadata | None = None) -> list[Hit]: ...

    def delete(self, where: Metadata) -> None: ...


def _where(filters: Metadata | None) -> dict | None:
    """Translate {'a': 1, 'b': 2} into Chroma's {'$and': [...]} filter syntax."""
    if not filters:
        return None
    clauses = [{k: v} for k, v in filters.items()]
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


class ChromaStore:
    def __init__(self, path: Path | str | None, embedder: Embedder, collection: str = "blueprint"):
        import chromadb

        client = chromadb.PersistentClient(path=str(path)) if path else chromadb.EphemeralClient()
        # We pass embeddings ourselves, so Chroma never downloads its default model.
        self._col = client.get_or_create_collection(
            collection, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )
        self._embedder = embedder

    def upsert(self, records: list[Record]) -> None:
        if not records:
            return
        self._col.upsert(
            ids=[r.id for r in records],
            documents=[r.text for r in records],
            metadatas=[r.metadata or {"_": ""} for r in records],
            embeddings=self._embedder.embed([r.text for r in records]),
        )

    def query(self, text: str, k: int = 5, where: Metadata | None = None) -> list[Hit]:
        if self._col.count() == 0:
            return []
        res = self._col.query(
            query_embeddings=self._embedder.embed([text]),
            n_results=k,
            where=_where(where),
            include=["documents", "metadatas", "distances"],
        )
        return [
            Hit(id=i, text=d, metadata=dict(m or {}), score=1 - dist)
            for i, d, m, dist in zip(res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0])
        ]

    def delete(self, where: Metadata) -> None:
        self._col.delete(where=_where(where))


def make_vector_store(backend: str, path: Path, embedder: Embedder) -> VectorStore:
    if backend == "chroma":
        return ChromaStore(path, embedder)
    # if backend == "pgvector": return PgVectorStore(dsn, embedder)
    raise ValueError(f"Unknown vector backend '{backend}'")
