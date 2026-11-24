"""LLM-based extraction of structured maintenance tasks from unstructured documents."""

from __future__ import annotations

import re

from blueprint.ingest import Page
from blueprint.llm import LLM
from blueprint.models import ExtractionResult, MaintenanceTask, SourceKind
from blueprint.normalize import task_key
from blueprint.safety import UNTRUSTED_RULE, wrap

_SYSTEM = """You extract preventive-maintenance requirements from {kind_desc}.

Return every distinct maintenance task as a structured record:
- component: the part or system serviced, in plain words ("engine oil filter", "hydraulic return filter").
- action: one verb from replace, inspect, lubricate, clean, flush, adjust, calibrate, overhaul, sample,
  or another single verb if none fits.
- part_ids: part numbers exactly as printed. Empty list if none.
- spec: the fluid or material specification if stated ("SAE 15W-40", "ISO VG 46"), else null.
- intervals: every trigger. "Every 500 hours or 3 months, whichever comes first" is two intervals.
  Use units hours (operating hours), days, weeks, months, years, km, miles or cycles.
- source_quote: the shortest verbatim passage that states the requirement. For a table row, include the
  column or section header that gives the interval ("Every 500 operating hours ... Change the fuel filter").
- page: the page number from the [page N] marker the passage sits under.
- needs_review: true when you are not sure of the task or interval, for example a garbled or
  partly unreadable table, "as required" / "as needed" instead of an interval, or conflicting
  numbers. Explain why in review_note. It is better to flag than to guess.

Rules:
- Only extract what the text states. Never infer tasks or intervals from general knowledge.
- Vague timing ("regularly", "periodically", "from time to time", "as necessary") is not an interval:
  leave intervals empty and set needs_review.
- Skip safety warnings, troubleshooting tables and one-off repair procedures.
- Use asset_id "{asset_id}" for every task.

"""
_SYSTEM += UNTRUSTED_RULE.replace("{", "{{").replace("}", "}}")

_KIND_DESC = {
    SourceKind.OEM: "an OEM equipment manual or maintenance specification",
    SourceKind.VENDOR: "a vendor service contract or maintenance schedule",
    SourceKind.FIELD: "a field service log, work order or maintenance report",
}


def _windows(pages: list[Page], max_chars: int) -> list[str]:
    windows, buf = [], ""
    for p in pages:
        # A page longer than a window is split, with each piece keeping its page marker.
        pieces = [p.text[i : i + max_chars] for i in range(0, len(p.text), max_chars)] or [""]
        for piece in pieces:
            block = f"[page {p.number}]\n{piece}\n"
            if buf and len(buf) + len(block) > max_chars:
                windows.append(buf)
                buf = ""
            buf += block
    if buf.strip():
        windows.append(buf)
    return windows


_NUMBER_WORDS = {
    1: ("one ", "once", "annual", "daily", "weekly", "monthly", "yearly"),
    2: ("two", "twice", "bi-", "biannual", "fortnight"), 3: ("three",), 4: ("four",), 5: ("five",),
    6: ("six", "semi-annual", "half-year", "half year"), 7: ("seven",), 8: ("eight",), 9: ("nine",),
    10: ("ten",), 12: ("twelve",), 24: ("twenty-four", "twenty four"),
}


def interval_in_quote(value: float, quote: str) -> bool:
    """True if the interval's number is actually written in the quote (as digits or a common word)."""
    q = quote.lower()
    digits = f"{value:g}"
    if re.search(rf"(?<![\d.,]){re.escape(digits)}(?![\d])", q.replace(",", "")):
        return True
    if value != int(value):
        return False
    if value == 1 and re.search(r"\b(a|an|every|each|per)\s+(day|week|month|year|hour|season)", q):
        return True
    return any(w in q for w in _NUMBER_WORDS.get(int(value), ()))


def _drop_unstated_intervals(task: MaintenanceTask, page_text: str = "") -> None:
    """Remove intervals the source doesn't state, and flag the task for review.

    An interval counts as stated if its number is in the quote. In a table the
    interval often sits in a column or section header rather than the row the
    model quoted, so a number other than 1 written on the same page also counts,
    with a note. A bare 1 ("daily", "once") must be in the quote itself, because
    those words are everywhere.
    """
    if not task.source_quote:
        return
    kept, from_page = [], []
    for iv in task.intervals:
        if interval_in_quote(iv.value, task.source_quote):
            kept.append(iv)
        elif iv.value != 1 and page_text and interval_in_quote(iv.value, page_text):
            kept.append(iv)
            from_page.append(iv)
    if from_page:
        found = ", ".join(f"{iv.value:g} {iv.unit.value}" for iv in from_page)
        note = f"Interval {found} is on the same page (likely a table header), not in the quote."
        task.review_note = f"{task.review_note} {note}".strip()
    if len(kept) < len(task.intervals):
        dropped = ", ".join(f"{iv.value:g} {iv.unit.value}" for iv in task.intervals if iv not in kept)
        task.intervals = kept
        task.needs_review = True
        note = f"Removed interval not stated in the source quote: {dropped}."
        task.review_note = f"{task.review_note} {note}".strip()


def extract_tasks(
    llm: LLM,
    *,
    model: str,
    pages: list[Page],
    kind: SourceKind,
    asset_id: str,
    max_chars: int = 24_000,
) -> list[MaintenanceTask]:
    """Use the LLM to pull maintenance tasks out of a document.

    The text is sent in page-tagged windows of at most `max_chars`. Each window's output is forced
    into the ExtractionResult schema, then checked in code: intervals not stated in the quoted page
    are dropped and the task is flagged for review. Duplicate tasks (e.g. table + body text) are merged.
    """
    system = _SYSTEM.format(kind_desc=_KIND_DESC[kind], asset_id=asset_id)
    seen: dict[str, MaintenanceTask] = {}
    page_text: dict[int, str] = {}
    for p in pages:
        page_text[p.number] = page_text.get(p.number, "") + p.text
    for window in _windows(pages, max_chars):
        result = llm.parse(model=model, system=system, user=wrap("document", window), schema=ExtractionResult)
        for extracted in result.tasks:
            task = MaintenanceTask(**extracted.model_dump(exclude={"asset_id"}), asset_id=asset_id)
            _drop_unstated_intervals(task, page_text.get(task.page or -1, ""))
            # The same task often appears in a summary table and in the body text.
            # Keep the first occurrence but merge any extra intervals/part numbers.
            key = task_key(task)
            if key in seen:
                prev = seen[key]
                new = [iv for iv in task.intervals if iv not in prev.intervals]
                if new and task.source_quote and task.source_quote not in prev.source_quote:
                    # Keep the evidence for merged intervals next to them.
                    page = f" (p.{task.page})" if task.page else ""
                    prev.source_quote = f"{prev.source_quote} … {task.source_quote}{page}".strip(" …")
                prev.intervals += new
                prev.part_ids += [p for p in task.part_ids if p not in prev.part_ids]
                prev.needs_review |= task.needs_review
            else:
                seen[key] = task
    return list(seen.values())
