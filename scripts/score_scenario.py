"""Run a scenario end to end and score it against its planted gaps.

    python scripts/score_scenario.py panda-60i

Uses real LLM extraction for the simulated vendor contract, so it spends tokens.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blueprint.config import get_settings  # noqa: E402
from blueprint.pipeline import Blueprint  # noqa: E402
from blueprint.samples import score  # noqa: E402
from blueprint.scenarios import answer_key, load_scenario  # noqa: E402

if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "panda-60i"
    bp = Blueprint.from_settings(get_settings())
    findings = load_scenario(bp, name)
    result = score(findings, answer_key(name))
    for g, f in result["found"]:
        print(f"FOUND   {g['id']:<4} {g['type']:<22} {f.message}")
    for g in result["missed"]:
        print(f"MISSED  {g['id']:<4} {g['type']:<22} {g['component']}: {g['why']}")
    for f in result["false_alarms"]:
        print(f"FALSE   {'':<4} {f.type.value:<22} {f.message}")
    for f in findings:
        if f.type.value in ("vendor_addition", "tightened_interval"):
            print(f"INFO         {f.type.value:<22} {f.message}")
    n = len(result["found"]) + len(result["missed"])
    print(f"\n{len(result['found'])}/{n} planted gaps found, {len(result['false_alarms'])} false alarms")
    sys.exit(0 if not result["missed"] and not result["false_alarms"] else 1)
