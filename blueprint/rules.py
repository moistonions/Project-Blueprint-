"""Deterministic compliance engine: OEM requirements vs vendor schedule.

No LLM is involved here. Given the same extracted tasks, the engine always
produces the same findings, which is what makes the gap report auditable.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from blueprint.models import Finding, FindingType, MaintenanceTask, Severity
from blueprint.normalize import canonical_action, canonical_component, interval_map, task_key

# Unit conversion is not exact (3 months = 91.3 days), so allow a small slack
# before calling an interval "extended". Anything above this is a gap.
DEFAULT_TOLERANCE = 0.02
COMPONENT_SIMILARITY_THRESHOLD = 0.8


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def match_tasks(
    oem: list[MaintenanceTask], vendor: list[MaintenanceTask]
) -> tuple[list[tuple[MaintenanceTask, MaintenanceTask]], list[MaintenanceTask], list[MaintenanceTask]]:
    """Pair OEM tasks with vendor tasks one-to-one.

    Passes, strongest first: identical task key, then same action with a shared
    part number, then same action with a similar component name.
    Returns (pairs, unmatched_oem, unmatched_vendor).
    """
    remaining = list(vendor)
    pairs: list[tuple[MaintenanceTask, MaintenanceTask]] = []
    unmatched_oem: list[MaintenanceTask] = []

    def take(pred) -> MaintenanceTask | None:
        for v in remaining:
            if pred(v):
                remaining.remove(v)
                return v
        return None

    for o in oem:
        okey, oact = task_key(o), canonical_action(o.action)
        ocomp, oparts = canonical_component(o.component), {p.upper() for p in o.part_ids}
        v = (
            take(lambda v: task_key(v) == okey)
            or take(
                lambda v: canonical_action(v.action) == oact
                and bool(oparts & {p.upper() for p in v.part_ids})
            )
            or take(
                lambda v: canonical_action(v.action) == oact
                and _similar(canonical_component(v.component), ocomp)
                >= COMPONENT_SIMILARITY_THRESHOLD
            )
        )
        if v is None:
            unmatched_oem.append(o)
        else:
            pairs.append((o, v))
    return pairs, unmatched_oem, remaining


def _fmt(task: MaintenanceTask) -> str:
    ivs = ", ".join(f"{iv.value:g} {iv.unit.value}" for iv in task.intervals) or "no interval"
    return f"{task.action} {task.component} ({ivs})"


def compare(
    oem: list[MaintenanceTask],
    vendor: list[MaintenanceTask],
    *,
    asset_id: str,
    vendor_name: str | None,
    tolerance: float = DEFAULT_TOLERANCE,
) -> list[Finding]:
    pairs, missing, additions = match_tasks(oem, vendor)
    findings: list[Finding] = []

    def add(type_, sev, key, msg, o=None, v=None):
        findings.append(
            Finding(
                asset_id=asset_id,
                vendor=vendor_name,
                type=type_,
                severity=sev,
                task_key=key,
                message=msg,
                oem_task=o,
                vendor_task=v,
            )
        )

    for o in missing:
        add(
            FindingType.MISSING_TASK,
            Severity.CRITICAL,
            task_key(o),
            f"OEM requires '{_fmt(o)}' but the vendor schedule has no matching task.",
            o=o,
        )

    for o, v in pairs:
        key = task_key(o)
        o_iv, v_iv = interval_map(o), interval_map(v)
        if o_iv and not v_iv:
            add(
                FindingType.MISSING_INTERVAL_BASIS,
                Severity.WARNING,
                key,
                f"Vendor performs '{v.action} {v.component}' but states no interval; OEM: {_fmt(o)}.",
                o,
                v,
            )
            continue
        tightened = False
        for dim, o_val in o_iv.items():
            v_val = v_iv.get(dim)
            if v_val is None:
                add(
                    FindingType.MISSING_INTERVAL_BASIS,
                    Severity.WARNING,
                    key,
                    f"OEM sets a {dim.value} limit for '{o.component}' that the vendor schedule "
                    f"does not track. OEM: {_fmt(o)}; vendor: {_fmt(v)}.",
                    o,
                    v,
                )
            elif v_val > o_val * (1 + tolerance):
                add(
                    FindingType.EXTENDED_INTERVAL,
                    Severity.CRITICAL,
                    key,
                    f"Vendor {dim.value} interval exceeds OEM for '{o.component}'. "
                    f"OEM: {_fmt(o)}; vendor: {_fmt(v)}.",
                    o,
                    v,
                )
            elif v_val < o_val * (1 - tolerance):
                tightened = True
        if tightened:
            add(
                FindingType.TIGHTENED_INTERVAL,
                Severity.INFO,
                key,
                f"Vendor services '{o.component}' more often than OEM. OEM: {_fmt(o)}; vendor: {_fmt(v)}.",
                o,
                v,
            )

    for v in additions:
        add(
            FindingType.VENDOR_ADDITION,
            Severity.INFO,
            task_key(v),
            f"Vendor performs '{_fmt(v)}', which the OEM schedule does not require.",
            v=v,
        )

    return findings
