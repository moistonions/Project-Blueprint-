"""Vendor checklist tickets: CSV import and text rendering for search.

The checklist format is still provisional. One row = one task done at a visit.
Required columns: date, asset_id, component, action. Optional: vendor,
meter_hours, time_spent_hours, notes.
"""

from __future__ import annotations

import csv
import io

from pydantic import ValidationError

from blueprint.models import Ticket

REQUIRED_COLUMNS = {"date", "asset_id", "component", "action"}
CSV_TEMPLATE = "date,asset_id,vendor,component,action,meter_hours,time_spent_hours,notes\n"


def parse_csv(data: bytes, *, vendor: str | None = None, is_sample: bool = False) -> list[Ticket]:
    """Parse a vendor checklist CSV into Ticket records (one per task line)."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    cols = {c.strip() for c in reader.fieldnames or []}
    if missing := REQUIRED_COLUMNS - cols:
        raise ValueError(f"Ticket CSV is missing columns: {', '.join(sorted(missing))}")
    tickets = []
    for n, row in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        try:
            tickets.append(
                Ticket(
                    asset_id=row["asset_id"],
                    vendor=row.get("vendor") or vendor,
                    date=row["date"],
                    component=row["component"],
                    action=row["action"],
                    meter_hours=row.get("meter_hours") or None,
                    time_spent_hours=row.get("time_spent_hours") or None,
                    notes=row.get("notes", ""),
                    is_sample=is_sample,
                )
            )
        except ValidationError as e:
            raise ValueError(f"Ticket CSV line {n}: {e.errors()[0]['msg']}") from e
    return tickets


def ticket_text(t: Ticket) -> str:
    """How a ticket reads in the vector index (its notes are field evidence)."""
    parts = [f"Checklist {t.date} {t.asset_id}: {t.action} {t.component}"]
    if t.meter_hours is not None:
        parts.append(f"meter {t.meter_hours:g} h")
    if t.time_spent_hours is not None:
        parts.append(f"time spent {t.time_spent_hours:g} h")
    text = ", ".join(parts) + "."
    return f"{text}\nNotes: {t.notes}" if t.notes else text
