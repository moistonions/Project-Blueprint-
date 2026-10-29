"""Deterministic execution check: did the vendor actually do OEM tasks on time?

Works from vendor checklist tickets. The observation window runs from the
asset's first ticket to its latest ticket (or an as-of date). For each OEM task
it walks the completions in order and flags any stretch between them, or after
the last one, that is longer than the OEM interval plus tolerance, using
whichever trigger (calendar, running hours) is hit first.
"""

from __future__ import annotations

from datetime import date
from itertools import pairwise

from blueprint.models import Finding, FindingType, MaintenanceTask, Severity, Ticket
from blueprint.normalize import Dimension, interval_map, task_key
from blueprint.rules import COMPONENT_SIMILARITY_THRESHOLD, ROUNDING_SLACK, candidate_match, tolerance_for


class HourMeter:
    """Hour-meter readings for one asset, interpolated between visits."""

    def __init__(self, tickets: list[Ticket]):
        pts: dict[date, float] = {}
        for t in tickets:
            if t.meter_hours is not None:
                pts[t.date] = max(pts.get(t.date, 0.0), t.meter_hours)
        self.points = sorted(pts.items())

    def usage_rate(self) -> float | None:
        """Running hours per month across the readings on file."""
        if len(self.points) < 2:
            return None
        (d0, h0), (d1, h1) = self.points[0], self.points[-1]
        days = (d1 - d0).days
        return (h1 - h0) / days * (365.25 / 12) if days > 0 else None

    def at(self, d: date) -> float | None:
        if not self.points:
            return None
        if len(self.points) == 1:
            return self.points[0][1] if d == self.points[0][0] else None
        for (d0, h0), (d1, h1) in pairwise(self.points):
            if d0 <= d <= d1:
                span = (d1 - d0).days
                return h0 if span == 0 else h0 + (h1 - h0) * (d - d0).days / span
        # Outside the readings: extrapolate with the average usage rate.
        rate_per_day = (self.usage_rate() or 0) / (365.25 / 12)
        ref_d, ref_h = self.points[0] if d < self.points[0][0] else self.points[-1]
        return ref_h + rate_per_day * (d - ref_d).days


def _done(task: MaintenanceTask, ticket: Ticket) -> bool:
    cand = candidate_match(task, ticket.as_task())
    return cand is not None and cand[1] >= COMPONENT_SIMILARITY_THRESHOLD


def check_execution(
    oem: list[MaintenanceTask],
    tickets: list[Ticket],
    *,
    asset_id: str,
    vendor_name: str | None,
    tolerance: float,
    as_of: date | None = None,
) -> list[Finding]:
    tickets = sorted((t for t in tickets if t.asset_id == asset_id), key=lambda t: t.date)
    if not tickets:
        return []
    meter = HourMeter(tickets)
    start = tickets[0].date
    end = as_of or tickets[-1].date
    findings: list[Finding] = []

    for task in oem:
        if task.needs_review:
            continue
        limits = interval_map(task)
        days_limit, hours_limit = limits.get(Dimension.CALENDAR), limits.get(Dimension.USAGE)
        if not (days_limit or hours_limit):
            continue
        allowed = 1 + max(tolerance_for(task, tolerance), ROUNDING_SLACK)
        done = sorted({t.date for t in tickets if _done(task, t)})
        anchors = done if done and done[0] == start else [start, *done]
        segments = [(a, b, False) for a, b in pairwise(anchors)] + [(anchors[-1], end, True)]
        problems: list[str] = []
        for prev, cur, is_open in segments:
            overrun = []
            days = (cur - prev).days
            if days_limit and days > days_limit * allowed:
                overrun.append(f"{days} days vs {days_limit:.0f}")
            h0, h1 = meter.at(prev), meter.at(cur)
            if hours_limit and h0 is not None and h1 is not None and h1 - h0 > hours_limit * allowed:
                overrun.append(f"{h1 - h0:.0f} running hours vs {hours_limit:.0f}")
            if not overrun:
                continue
            since = "start of records" if prev == start and prev not in done else f"last done {prev}"
            if is_open:
                problems.append(f"not done since {since} as of {cur} ({'; '.join(overrun)})")
            else:
                problems.append(f"done late on {cur}, {since} ({'; '.join(overrun)})")
        for p in problems:
            findings.append(
                Finding(
                    asset_id=asset_id,
                    vendor=vendor_name,
                    type=FindingType.EXECUTION_GAP,
                    severity=Severity.CRITICAL,
                    task_key=task_key(task),
                    message=f"'{task.action} {task.component}' {p}.",
                    oem_task=task,
                )
            )
    return findings
