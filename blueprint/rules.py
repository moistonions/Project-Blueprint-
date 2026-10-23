"""Deterministic compliance engine: approved OEM baseline vs vendor schedule.

No LLM is involved here. Given the same tasks, the engine always produces the
same findings, which is what makes the gap report auditable.
"""

from __future__ import annotations

from dataclasses import dataclass

from blueprint.models import Finding, FindingType, MaintenanceTask, MatchBasis, Severity
from blueprint.normalize import (
    canonical_action,
    canonical_parts,
    canonical_spec,
    component_similarity,
    interval_map,
    task_key,
)

# Overrun allowed on recurring tasks before "longer" becomes "beyond tolerance".
# Provisional; safety-critical tasks always use zero.
DEFAULT_TOLERANCE = 0.10
# Unit conversion is not exact (3 months = 91.3 days, 13 weeks = 91 days), so
# differences this small are treated as equal rather than reported.
ROUNDING_SLACK = 0.02
COMPONENT_SIMILARITY_THRESHOLD = 0.8


@dataclass
class Match:
    oem: MaintenanceTask
    vendor: MaintenanceTask
    basis: MatchBasis
    confidence: float


def candidate_match(o: MaintenanceTask, v: MaintenanceTask) -> tuple[MatchBasis, float] | None:
    if canonical_action(o.action) != canonical_action(v.action):
        return None
    if task_key(o) == task_key(v):
        return MatchBasis.TASK_KEY, 1.0
    if canonical_parts(o.part_ids) & canonical_parts(v.part_ids):
        return MatchBasis.PART_NUMBER, 0.95
    sim = component_similarity(o.component, v.component)
    if sim >= COMPONENT_SIMILARITY_THRESHOLD:
        return MatchBasis.SIMILAR_NAME, round(min(sim, 0.9), 2)
    return None


def match_tasks(
    oem: list[MaintenanceTask], vendor: list[MaintenanceTask]
) -> tuple[list[Match], list[MaintenanceTask], list[MaintenanceTask]]:
    """Pair OEM tasks with vendor tasks one-to-one, best candidate first.

    Returns (matches, unmatched_oem, unmatched_vendor).
    """
    remaining = list(vendor)
    matches: list[Match] = []
    unmatched_oem: list[MaintenanceTask] = []
    for o in oem:
        best: tuple[float, MaintenanceTask, MatchBasis] | None = None
        for v in remaining:
            cand = candidate_match(o, v)
            if cand and (best is None or cand[1] > best[0]):
                best = (cand[1], v, cand[0])
        if best is None:
            unmatched_oem.append(o)
        else:
            remaining.remove(best[1])
            matches.append(Match(o, best[1], best[2], best[0]))
    return matches, unmatched_oem, remaining


def _fmt(task: MaintenanceTask) -> str:
    ivs = " or ".join(f"{iv.value:g} {iv.unit.value}" for iv in task.intervals) or "no interval"
    return f"{task.action} {task.component} ({ivs})"


def tolerance_for(task: MaintenanceTask, tolerance: float) -> float:
    return 0.0 if task.safety_critical else tolerance


def compare(
    oem: list[MaintenanceTask],
    vendor: list[MaintenanceTask],
    *,
    asset_id: str,
    vendor_name: str | None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[Finding]:
    findings: list[Finding] = []

    def add(type_, sev, o, v, msg, m: Match | None = None):
        findings.append(
            Finding(
                asset_id=asset_id,
                vendor=vendor_name,
                type=type_,
                severity=sev,
                task_key=task_key(o or v),
                message=msg,
                oem_task=o,
                vendor_task=v,
                match_basis=m.basis if m else None,
                match_confidence=m.confidence if m else None,
            )
        )

    # Uncertain extractions can't be trusted either way, so they fail until a person resolves them.
    for o in oem:
        if o.needs_review:
            note = f" ({o.review_note})" if o.review_note else ""
            add(FindingType.NEEDS_REVIEW, Severity.CRITICAL, o, None,
                f"OEM task '{_fmt(o)}' needs review{note}. Counts as failed until resolved.")

    matches, missing, additions = match_tasks([o for o in oem if not o.needs_review], vendor)

    for o in missing:
        add(FindingType.MISSING_TASK, Severity.CRITICAL, o, None,
            f"OEM requires '{_fmt(o)}' but the vendor schedule has no matching task.")

    for m in matches:
        o, v = m.oem, m.vendor
        tol = tolerance_for(o, tolerance)
        o_parts, v_parts = canonical_parts(o.part_ids), canonical_parts(v.part_ids)
        if o_parts and v_parts and not (o_parts & v_parts):
            add(FindingType.SPEC_MISMATCH, Severity.WARNING, o, v,
                f"Part numbers differ for '{o.component}' (ambiguous): OEM {', '.join(o.part_ids)}; "
                f"vendor {', '.join(v.part_ids)}.", m)
        if canonical_spec(o.spec) and canonical_spec(v.spec) and canonical_spec(o.spec) != canonical_spec(v.spec):
            add(FindingType.SPEC_MISMATCH, Severity.WARNING, o, v,
                f"Fluid/material spec differs for '{o.component}' (ambiguous): OEM {o.spec}; vendor {v.spec}.", m)

        o_iv, v_iv = interval_map(o), interval_map(v)
        if o_iv and not v_iv:
            add(FindingType.MISSING_INTERVAL_BASIS, Severity.WARNING, o, v,
                f"Vendor performs '{v.action} {v.component}' but states no interval; OEM: {_fmt(o)}.", m)
            continue
        tightened = False
        for dim, o_val in o_iv.items():
            v_val = v_iv.get(dim)
            if v_val is None:
                add(FindingType.MISSING_INTERVAL_BASIS, Severity.WARNING, o, v,
                    f"OEM sets a {dim.value} limit for '{o.component}' that the vendor schedule does not "
                    f"track. OEM: {_fmt(o)}; vendor: {_fmt(v)}.", m)
                continue
            over = v_val / o_val - 1
            if over > max(tol, ROUNDING_SLACK):
                why = "safety-critical, zero tolerance" if o.safety_critical else f"tolerance {tol:.0%}"
                add(FindingType.BEYOND_TOLERANCE, Severity.CRITICAL, o, v,
                    f"Vendor {dim.value} interval for '{o.component}' is {over:.0%} longer than OEM ({why}). "
                    f"OEM: {_fmt(o)}; vendor: {_fmt(v)}.", m)
            elif over > ROUNDING_SLACK:
                add(FindingType.LONGER_INTERVAL, Severity.WARNING, o, v,
                    f"Vendor {dim.value} interval for '{o.component}' is {over:.0%} longer than OEM, within "
                    f"the {tol:.0%} tolerance. OEM: {_fmt(o)}; vendor: {_fmt(v)}.", m)
            elif over < -ROUNDING_SLACK:
                tightened = True
        if tightened:
            add(FindingType.TIGHTENED_INTERVAL, Severity.INFO, o, v,
                f"Vendor services '{o.component}' more often than OEM. OEM: {_fmt(o)}; vendor: {_fmt(v)}.", m)

    for v in additions:
        add(FindingType.VENDOR_ADDITION, Severity.INFO, None, v,
            f"Vendor performs '{_fmt(v)}', which the OEM schedule does not require.")

    return findings
