"""Turn uploaded files into page-level text and retrieval chunks."""

from __future__ import annotations

import io
import re
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
    return split_text_pages(data.decode("utf-8", errors="replace"))


# Header/footer lines like "Seite/Page 12", "Page 12 of 170" or "- 12 -" in text exported from a PDF.
_PAGE_LINE = re.compile(r"^.{0,60}?\b(?:seite/)?page\s+(\d{1,4})\b.{0,60}$", re.IGNORECASE | re.MULTILINE)


_NUMBERED_LINE = re.compile(r"^\s*(?:(\d{1,4})\s+(\D{2,40}?)|(\D{2,40}?)\s+(\d{1,4}))\s*$", re.MULTILINE)


def _rising(marks: list[tuple[int, int]]) -> bool:
    ups = sum(1 for a, b in zip(marks, marks[1:]) if b[1] > a[1])
    return len(marks) >= 3 and ups >= 0.8 * (len(marks) - 1)


def _running_header_marks(text: str) -> list[tuple[int, int]]:
    """Find a running header such as 'HATZ Manual 83' / '84 Manual HATZ' that repeats with the page number."""
    groups: dict[frozenset, list[tuple[int, int]]] = {}
    for m in _NUMBERED_LINE.finditer(text):
        num, label = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        key = frozenset(label.lower().split())
        groups.setdefault(key, []).append((m.start(), int(num)))
    best = max(groups.values(), key=len, default=[])
    return best if _rising(best) else []


def split_text_pages(text: str) -> list[Page]:
    """Recover page numbers from text exported from a PDF.

    Form feeds win if present. Otherwise lines that carry a page number
    ("Seite/Page 12", or a running header like "HATZ Manual 83") mark the
    pages, as long as the numbers mostly rise. Anything else stays one page.
    """
    if "\f" in text:
        return [Page(i + 1, t) for i, t in enumerate(text.split("\f"))]
    marks = [(m.start(), int(m.group(1))) for m in _PAGE_LINE.finditer(text)]
    if not _rising(marks):
        marks = _running_header_marks(text)
    if not marks:
        return [Page(1, text)]
    pages: list[Page] = []
    # A header line starts its page; text before the first header belongs to the page before it.
    if text[: marks[0][0]].strip():
        pages.append(Page(max(marks[0][1] - 1, 1), text[: marks[0][0]]))
    for (start, num), nxt in zip(marks, marks[1:] + [(len(text), 0)]):
        pages.append(Page(num, text[start : nxt[0]]))
    return pages


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
