"""Loader for the clearly labeled synthetic sample set in data/samples/."""

from __future__ import annotations

from blueprint.config import ROOT
from blueprint.models import Finding, SourceKind
from blueprint.pipeline import Blueprint

SAMPLE_DIR = ROOT / "data" / "samples"
SAMPLE_ASSET = "SAMPLE-PUMP-01"
SAMPLE_VENDOR = "Example Services Ltd (fictional)"

_FILES = [
    ("sample_oem_spec.txt", SourceKind.OEM, None),
    ("sample_vendor_schedule.txt", SourceKind.VENDOR, SAMPLE_VENDOR),
    ("sample_field_log.txt", SourceKind.FIELD, SAMPLE_VENDOR),
]


def load_samples(bp: Blueprint) -> list[Finding]:
    for name, kind, vendor in _FILES:
        bp.ingest(name, (SAMPLE_DIR / name).read_bytes(), kind=kind, asset_id=SAMPLE_ASSET, vendor=vendor, is_sample=True)
    return bp.analyze(SAMPLE_ASSET)
