"""Deterministic normalization of intervals and task identities.

Everything here is pure and rule-based so the compliance engine gives the same
answer every time for the same extracted data.
"""

from __future__ import annotations

import re
from enum import Enum

from blueprint.models import Interval, IntervalUnit, MaintenanceTask


class Dimension(str, Enum):
    CALENDAR = "calendar"  # normalized to days
    USAGE = "usage"  # normalized to operating hours
    DISTANCE = "distance"  # normalized to km
    CYCLES = "cycles"


_TO_BASE: dict[IntervalUnit, tuple[Dimension, float]] = {
    IntervalUnit.DAYS: (Dimension.CALENDAR, 1.0),
    IntervalUnit.WEEKS: (Dimension.CALENDAR, 7.0),
    IntervalUnit.MONTHS: (Dimension.CALENDAR, 365.25 / 12),
    IntervalUnit.YEARS: (Dimension.CALENDAR, 365.25),
    IntervalUnit.HOURS: (Dimension.USAGE, 1.0),
    IntervalUnit.KM: (Dimension.DISTANCE, 1.0),
    IntervalUnit.MILES: (Dimension.DISTANCE, 1.609344),
    IntervalUnit.CYCLES: (Dimension.CYCLES, 1.0),
}


def to_base(interval: Interval) -> tuple[Dimension, float]:
    dim, factor = _TO_BASE[interval.unit]
    return dim, interval.value * factor


def interval_map(task: MaintenanceTask) -> dict[Dimension, float]:
    """Collapse a task's intervals to {dimension: tightest value in base units}."""
    out: dict[Dimension, float] = {}
    for iv in task.intervals:
        dim, val = to_base(iv)
        out[dim] = min(val, out.get(dim, val))
    return out


# Map common verb variants onto one canonical action so "change" == "replace".
_ACTION_SYNONYMS: dict[str, str] = {
    "change": "replace",
    "renew": "replace",
    "swap": "replace",
    "check": "inspect",
    "examine": "inspect",
    "verify": "inspect",
    "test": "inspect",
    "grease": "lubricate",
    "lube": "lubricate",
    "oil": "lubricate",
    "clean": "clean",
    "flush": "flush",
    "drain": "flush",
    "adjust": "adjust",
    "torque": "adjust",
    "tighten": "adjust",
    "calibrate": "calibrate",
    "overhaul": "overhaul",
    "rebuild": "overhaul",
    "sample": "sample",
    "analyze": "sample",
    "analyse": "sample",
}

_STOPWORDS = {"the", "a", "an", "and", "of", "all", "for", "to", "on", "in", "if", "as", "required"}


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in _STOPWORDS]


def canonical_action(action: str) -> str:
    toks = _tokens(action)
    if not toks:
        return ""
    word = toks[0]
    known = set(_ACTION_SYNONYMS) | set(_ACTION_SYNONYMS.values())
    # crude stemming so "replacing"/"replaced"/"replaces" all match "replace"
    candidates = [word]
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            stem = word[: -len(suffix)]
            candidates += [stem, stem + "e"]
    for cand in candidates:
        if cand in known:
            return _ACTION_SYNONYMS.get(cand, cand)
    return word


def canonical_component(component: str) -> str:
    return " ".join(sorted(_tokens(component)))


def task_key(task: MaintenanceTask) -> str:
    return f"{canonical_component(task.component)}|{canonical_action(task.action)}"
