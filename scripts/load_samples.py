"""Load the synthetic sample generator set, run the analysis and score it
against the planted gaps in data/samples/planted_gaps.json.

This uses the real OpenAI extraction, so it is the end-to-end success test:
every planted gap found, no false alarms. The sample files are fictional.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blueprint.config import get_settings  # noqa: E402
from blueprint.pipeline import Blueprint  # noqa: E402
from blueprint.samples import load_samples, score  # noqa: E402

if __name__ == "__main__":
    bp = Blueprint.from_settings(get_settings())
    result = score(load_samples(bp))
    for g, f in result["found"]:
        print(f"FOUND   {g['id']:<4} {g['type']:<17} {f.message}")
    for g in result["missed"]:
        print(f"MISSED  {g['id']:<4} {g['type']:<17} {g['component']}: {g['why']}")
    for f in result["false_alarms"]:
        print(f"FALSE   {'':<4} {f.type.value:<17} {f.message}")
    n = len(result["found"]) + len(result["missed"])
    print(f"\n{len(result['found'])}/{n} planted gaps found, {len(result['false_alarms'])} false alarms")
    sys.exit(0 if not result["missed"] and not result["false_alarms"] else 1)
