"""Load the synthetic sample documents in data/samples/ and run the analysis.

These files are fictional and exist only to test the pipeline end to end.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blueprint.config import get_settings  # noqa: E402
from blueprint.pipeline import Blueprint  # noqa: E402
from blueprint.samples import load_samples  # noqa: E402

if __name__ == "__main__":
    bp = Blueprint.from_settings(get_settings())
    findings = load_samples(bp)
    for f in findings:
        print(f"[{f.severity.value}] {f.type.value}: {f.message}")
