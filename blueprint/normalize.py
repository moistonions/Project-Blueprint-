"""Deterministic normalization of intervals and task identities.

Everything here is pure and rule-based so the compliance engine gives the same
answer every time for the same extracted data.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from enum import Enum

from blueprint.models import Interval, IntervalUnit, MaintenanceTask


class Dimension(str, Enum):
    """What an interval measures, so only like with like is compared."""
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
    """Convert an interval to its base unit (days, hours, km or cycles)."""
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
    "read": "inspect",  # "read out the fault memory"
    "diagnose": "inspect",
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
    """Map an action verb to a canonical verb (e.g. 'change' -> 'replace', 'check' -> 'inspect')."""
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


# Shorthand common in vendor schedules and checklists.
_ABBREVIATIONS = {
    "hyd": "hydraulic",
    "eng": "engine",
    "trans": "transmission",
    "alt": "alternator",
    "gen": "generator",
    "elem": "element",
    "brg": "bearing",
    "brgs": "bearing",
    "assy": "assembly",
    "e": "emergency",
}


def component_tokens(component: str) -> frozenset[str]:
    """Normalised word set for a component name (lower case, synonyms merged, filler words dropped)."""
    out = set()
    for w in _tokens(component):
        w = _ABBREVIATIONS.get(w, w)
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]  # filters -> filter, bearings -> bearing
        out.add(w)
    return frozenset(out)


def canonical_component(component: str) -> str:
    """Order-independent component name, used in task keys."""
    return " ".join(sorted(component_tokens(component)))


# Words that say what kind of part something is, not which one.
_GENERIC = {"filter", "element", "system", "device", "unit", "assembly", "kit", "hose", "belt", "valve", "pump"}


def component_similarity(a: str, b: str) -> float:
    """0-1 similarity of two component names.

    Token containment catches "hyd filters" vs "hydraulic return filter" and
    "coolant" vs "engine coolant"; a character ratio catches spelling variants.
    A one-word name made of a generic word ("filter") must match exactly, so it
    doesn't pair with every filter on the asset.
    """
    ta, tb = component_tokens(a), component_tokens(b)
    if not ta or not tb:
        return 0.0
    small = min(ta, tb, key=len)
    if len(small) == 1 and small <= _GENERIC:
        containment = float(ta == tb)
    else:
        containment = len(ta & tb) / len(small)
    ratio = SequenceMatcher(None, canonical_component(a), canonical_component(b)).ratio()
    return max(containment, ratio)


def task_key(task: MaintenanceTask) -> str:
    """Key identifying the same task across documents: 'component|action' after normalising."""
    return f"{canonical_component(task.component)}|{canonical_action(task.action)}"


def canonical_spec(spec: str | None) -> str:
    """'SAE 15W-40' == 'sae15w40'; empty when no spec is given."""
    return re.sub(r"[^a-z0-9]", "", (spec or "").lower())


def canonical_parts(part_ids: list[str]) -> set[str]:
    """Normalised part numbers, for matching tasks that share a part."""
    return {canonical_spec(p) for p in part_ids if canonical_spec(p)}


_UNIT_ALIASES: dict[str, IntervalUnit] = {
    **{a: IntervalUnit.HOURS for a in ("h", "hr", "hrs", "hour", "hours")},
    **{a: IntervalUnit.DAYS for a in ("d", "day", "days")},
    **{a: IntervalUnit.WEEKS for a in ("wk", "wks", "week", "weeks")},
    **{a: IntervalUnit.MONTHS for a in ("mo", "mos", "month", "months")},
    **{a: IntervalUnit.YEARS for a in ("y", "yr", "yrs", "year", "years")},
    **{a: IntervalUnit.KM for a in ("km", "kms")},
    **{a: IntervalUnit.MILES for a in ("mi", "mile", "miles")},
    **{a: IntervalUnit.CYCLES for a in ("cycle", "cycles", "starts")},
}


def format_intervals(intervals: list[Interval]) -> str:
    """[250 h, 1 month] -> '250 hours; 1 month' (singular for 1, so it reads naturally)."""
    def one(iv: Interval) -> str:
        """Format a single interval."""
        unit = iv.unit.value
        if iv.value == 1 and unit.endswith("s"):
            unit = unit[:-1]
        return f"{iv.value:g} {unit}"

    return "; ".join(one(iv) for iv in intervals)


def parse_intervals(text: str) -> list[Interval]:
    """'250 hours; 6 months' or '250 h or 6 mo' -> intervals. Raises ValueError on anything else."""
    out = []
    for part in re.split(r";|,|\bor\b", text or ""):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([a-zA-Z]+)", part)
        if not m or m.group(2).lower() not in _UNIT_ALIASES:
            raise ValueError(f"Can't read interval '{part}'. Use e.g. '250 hours; 6 months'.")
        out.append(Interval(value=float(m.group(1)), unit=_UNIT_ALIASES[m.group(2).lower()]))
    return out
