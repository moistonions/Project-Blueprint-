"""Turn uploaded files into page-level text and retrieval chunks."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".csv", ".eml"}


@dataclass
class Page:
    number: int  # 1-based
    text: str


@dataclass
class Chunk:
    text: str
    page: int
    index: int


def read_pages(filename: str, data: bytes) -> list[Page]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type '{suffix}'. Supported: {sorted(SUPPORTED_SUFFIXES)}")
    if suffix == ".pdf":
        reader = PdfReader(io.BytesIO(data))
        # Scanned (image-only) manuals return empty text here and need OCR first.
        return [Page(i + 1, p.extract_text() or "") for i, p in enumerate(reader.pages)]
    return [Page(1, data.decode("utf-8", errors="replace"))]


def chunk_pages(pages: list[Page], max_chars: int = 2000, overlap: int = 200) -> list[Chunk]:
    """Split pages on paragraph boundaries into overlapping chunks that keep page numbers."""
    chunks: list[Chunk] = []
    for page in pages:
        buf = ""
        for para in (p.strip() for p in page.text.split("\n\n")):
            if not para:
                continue
            if buf and len(buf) + len(para) + 2 > max_chars:
                chunks.append(Chunk(buf, page.number, len(chunks)))
                buf = buf[-overlap:] if overlap else ""
            buf = f"{buf}\n\n{para}" if buf else para
            while len(buf) > max_chars:
                chunks.append(Chunk(buf[:max_chars], page.number, len(chunks)))
                buf = buf[max_chars - overlap :]
        if buf.strip():
            chunks.append(Chunk(buf, page.number, len(chunks)))
    return chunks
