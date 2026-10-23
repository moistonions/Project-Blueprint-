"""LLM-based extraction of structured maintenance tasks from unstructured documents."""

from __future__ import annotations

from blueprint.ingest import Page
from blueprint.llm import LLM
from blueprint.models import ExtractionResult, MaintenanceTask, SourceKind
from blueprint.normalize import task_key

_SYSTEM = """You extract preventive-maintenance requirements from {kind_desc}.

Return every distinct maintenance task as a structured record:
- component: the part or system serviced, in plain words ("engine oil filter", "hydraulic return filter").
- action: one verb from replace, inspect, lubricate, clean, flush, adjust, calibrate, overhaul, sample,
  or another single verb if none fits.
- part_ids: part numbers exactly as printed. Empty list if none.
- intervals: every trigger. "Every 500 hours or 3 months, whichever comes first" is two intervals.
  Use units hours (operating hours), days, weeks, months, years, km, miles or cycles.
- source_quote: the shortest verbatim passage that states the requirement.
- page: the page number from the [page N] marker the passage sits under.

Rules:
- Only extract what the text states. Never infer tasks or intervals from general knowledge.
- Skip safety warnings, troubleshooting tables and one-off repair procedures.
- Use asset_id "{asset_id}" for every task."""

_KIND_DESC = {
    SourceKind.OEM: "an OEM equipment manual or maintenance specification",
    SourceKind.VENDOR: "a vendor service contract or maintenance schedule",
    SourceKind.FIELD: "a field service log, work order or maintenance report",
}


def _windows(pages: list[Page], max_chars: int) -> list[str]:
    windows, buf = [], ""
    for p in pages:
        block = f"[page {p.number}]\n{p.text}\n"
        if buf and len(buf) + len(block) > max_chars:
            windows.append(buf)
            buf = ""
        buf += block
    if buf.strip():
        windows.append(buf)
    return windows


def extract_tasks(
    llm: LLM,
    *,
    model: str,
    pages: list[Page],
    kind: SourceKind,
    asset_id: str,
    max_chars: int = 24_000,
) -> list[MaintenanceTask]:
    system = _SYSTEM.format(kind_desc=_KIND_DESC[kind], asset_id=asset_id)
    seen: dict[str, MaintenanceTask] = {}
    for window in _windows(pages, max_chars):
        result = llm.parse(model=model, system=system, user=window, schema=ExtractionResult)
        for task in result.tasks:
            task.asset_id = asset_id
            # The same task often appears in a summary table and in the body text.
            # Keep the first occurrence but merge any extra intervals/part numbers.
            key = task_key(task)
            if key in seen:
                prev = seen[key]
                prev.intervals += [iv for iv in task.intervals if iv not in prev.intervals]
                prev.part_ids += [p for p in task.part_ids if p not in prev.part_ids]
            else:
                seen[key] = task
    return list(seen.values())
