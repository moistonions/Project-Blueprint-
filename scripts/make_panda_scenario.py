"""Generate the Panda 60i scenario: a proposed OEM baseline built from the real
manuals, plus a SIMULATED vendor contract, checklists and planted-gap answer key.

The baseline tasks, intervals, pages and quotes come from the extraction of the
real Fischer Panda 60i manual and the Hatz 3H50/4H50 manual (a placeholder for the
actual engine documents). Everything about the vendor is invented and labelled.
Run once; the output files are committed under data/scenarios/panda-60i/.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "scenarios" / "panda-60i"
ASSET = "PANDA-60I"
VENDOR = "Example Marine Services (fictional)"
PANDA = "Panda_60i_PMS_System_eng.R05.1"
HATZ = "Hatz_3H50_4H50_manual_PLACEHOLDER"
H500 = [(500, "hours"), (12, "months")]
H500_Q = "Every 500 operating hours or every 12 months ..."

# (key, source, page, component, action, intervals, spec, safety_critical, quote)
BASELINE = [
    ("P1", PANDA, 81, "exhaust line pipes and hoses", "inspect", [(1, "months")], None, True,
     "the pipes must be checked for corrosion regularly (at the latest once a month) and replaced if necessary"),
    ("P2", PANDA, 113, "PMGi inverter heat sinks", "inspect", [(6, "months")], None, False,
     "Every 6 months it is necessary to visual inspect the heat sinks and clean it with compressed air."),
    ("P3", PANDA, 113, "PMGi inverter heat sinks", "clean", [(6, "months")], "compressed air", False,
     "Every 6 months it is necessary to visual inspect the heat sinks and clean it with compressed air."),
    ("P4", PANDA, 47, "starter battery", "charge", [(2, "months")], None, False,
     "It is recommended that the starter battery be regularly charged by a suitable battery-charging device "
     "(i.e., at least every 2 Months)."),
    ("H1", HATZ, 84, "engine management fault memory", "inspect", H500, None, False,
     f"{H500_Q} Diagnosis of engine management"),
    ("H2", HATZ, 84, "engine control unit software", "update", H500, None, False,
     f"{H500_Q} Update of the engine control unit"),
    ("H3", HATZ, 84, "engine and radiator fins", "clean", H500, None, False, f"{H500_Q} Clean the engine"),
    ("H4", HATZ, 84, "coolant anti-freeze concentration", "inspect", H500, None, False,
     f"{H500_Q} Check the anti-freeze concentration of the coolant"),
    ("H5", HATZ, 84, "engine oil and oil filter", "replace", H500, "ACEA E6", False,
     f"{H500_Q} Change the engine oil and oil filter"),
    ("H6", HATZ, 84, "poly v belt", "inspect", H500, None, False, f"{H500_Q} Check the poly v belt"),
    ("H7", HATZ, 84, "crankcase ventilation oil separator", "replace", H500, None, False,
     f"{H500_Q} Change the crankcase ventilation oil separator"),
    ("H8", HATZ, 84, "screw connections", "inspect", H500, None, False, f"{H500_Q} Check the screw connections"),
    ("H9", HATZ, 84, "fuel prefilter", "replace", H500, None, False, f"{H500_Q} Change the fuel prefilter"),
    ("H10", HATZ, 84, "main fuel filter", "replace", H500, None, False, f"{H500_Q} Change the main fuel filter"),
    ("H11", HATZ, 84, "charge air cooler", "drain", H500, None, False, f"{H500_Q} Drain the charge air cooler"),
    ("H12", HATZ, 84, "air filter primary cartridge", "replace", H500, None, False,
     f"{H500_Q} Change the air filter cartridge (primary filter)"),
    ("H13", HATZ, 85, "air filter secondary element", "replace", [(2, "years")], None, False,
     "The secondary filter must be replaced after every fifth replacement of the primary filter, though no later than every two years."),
    ("H14", HATZ, 85, "fuel water separator", "drain", [(12, "months")], None, False,
     "When indicated, at least every 12 months Drain the water separator"),
    ("H15", HATZ, 85, "engine coolant", "replace", [(4, "years")], "Mitan C12+", False, "Every 4 years Change the coolant"),
    ("H16", HATZ, 85, "poly v belt", "replace", [(3000, "hours")], None, False,
     "If necessary, but every 3,000 operating hours at the latest ... Change the poly v belt"),
    ("H17", HATZ, 85, "exhaust gas recirculation main radiator", "clean", [(4000, "hours")], None, False,
     "Every 4,000 operating hours ... Clean the main radiator of the exhaust gas recirculation (EGR)"),
    ("H18", HATZ, 85, "diesel particulate filter", "clean", [(4000, "hours")], None, False,
     "Every 4,000 operating hours ... Clean the diesel particulate filter (DPF)"),
]

# Vendor schedule: same as OEM except the planted differences. (component, action, intervals, spec, contract line)
CONTRACT = [
    ("exhaust line pipes and hoses", "inspect", [(32, "days")], None,
     "Inspect exhaust line pipes and hoses for corrosion every 32 days."),
    ("PMGi inverter heat sinks", "inspect", [(6, "months")], None, "Inspect PMGi inverter heat sinks every 6 months."),
    ("PMGi inverter heat sinks", "clean", [(6, "months")], "compressed air",
     "Clean PMGi inverter heat sinks with compressed air every 6 months."),
    ("starter battery", "charge", [(1, "months")], None, "Charge the starter battery every month."),
    ("engine management fault memory", "inspect", H500, None,
     "Read out the engine management fault memory every 500 hours or 12 months."),
    ("engine control unit software", "update", H500, None, "Update the engine control unit software every 500 hours or 12 months."),
    ("engine and radiator fins", "clean", H500, None, "Clean the engine and radiator fins every 500 hours or 12 months."),
    ("coolant anti-freeze concentration", "inspect", H500, None,
     "Check the coolant anti-freeze concentration every 500 hours or 12 months."),
    ("engine oil and oil filter", "replace", H500, "API CH-4",
     "Change the engine oil and oil filter with API CH-4 oil every 500 hours or 12 months."),
    ("poly v belt", "inspect", H500, None, "Check the poly v belt every 500 hours or 12 months."),
    ("crankcase ventilation oil separator", "replace", H500, None,
     "Change the crankcase ventilation oil separator every 500 hours or 12 months."),
    ("screw connections", "inspect", H500, None, "Check the screw connections every 500 hours or 12 months."),
    ("fuel prefilter", "replace", [(500, "hours")], None, "Change the fuel prefilter every 500 hours."),
    ("main fuel filter", "replace", [(540, "hours"), (12, "months")], None,
     "Change the main fuel filter every 540 hours or 12 months."),
    ("charge air cooler", "drain", H500, None, "Drain the charge air cooler every 500 hours or 12 months."),
    ("air filter primary cartridge", "replace", [(750, "hours"), (12, "months")], None,
     "Change the air filter primary cartridge every 750 hours or 12 months."),
    ("air filter secondary element", "replace", [(2, "years")], None, "Change the air filter secondary element every 2 years."),
    ("fuel water separator", "drain", [(12, "months")], None, "Drain the fuel water separator every 12 months."),
    ("engine coolant", "replace", [(4, "years")], "generic IAT green coolant",
     "Replace the engine coolant every 4 years with generic IAT green coolant."),
    ("poly v belt", "replace", [(3000, "hours")], None, "Replace the poly v belt every 3000 hours."),
    ("exhaust mixing elbow", "descale", [(6, "months")], None, "Descale the exhaust mixing elbow every 6 months."),
]

GAPS = [
    ("G1", "missing_task", "diesel particulate filter", "OEM 4000 h DPF cleaning is not in the contract"),
    ("G2", "missing_task", "exhaust gas recirculation main radiator", "OEM 4000 h EGR radiator cleaning is not in the contract"),
    ("G3", "longer_interval", "main fuel filter", "540 h vs 500 h, 8% over, within the 10% tolerance"),
    ("G4", "beyond_tolerance", "air filter primary cartridge", "750 h vs 500 h"),
    ("G5", "beyond_tolerance", "exhaust line pipes and hoses", "32 days vs 1 month; safety-critical, so zero tolerance"),
    ("G6", "missing_interval_basis", "fuel prefilter", "contract has 500 h only, OEM also says 12 months"),
    ("G7", "spec_mismatch", "engine oil and oil filter", "API CH-4 is not on the Hatz oil list (ACEA E6 recommended)"),
    ("G8", "spec_mismatch", "engine coolant", "generic IAT coolant vs Mitan C12+ or a Hatz-approved alternative"),
    ("G9", "execution_gap", "engine oil and oil filter", "changed 2025-01-15 then 2025-06-15, 750 running hours vs 500"),
    ("G10", "execution_gap", "PMGi inverter heat sinks", "cleaned 2025-01-15, not again by 2025-12-15 (6 months)"),
]


def iv(pairs):
    """Build an interval list from (value, unit) pairs."""
    return [{"value": v, "unit": u} for v, u in pairs]


def tickets():
    """Monthly visits through 2025 at about 150 running hours a month."""
    rows = []
    visits = [(date(2025, m, 15), 3000 + 150 * (m - 1)) for m in range(1, 13)]
    quarterly = {1, 4, 7, 10}
    h500 = ["engine management fault memory|inspect", "engine control unit software|update",
            "engine and radiator fins|clean", "coolant anti-freeze concentration|inspect", "poly v belt|inspect",
            "crankcase ventilation oil separator|replace", "screw connections|inspect", "fuel prefilter|replace",
            "main fuel filter|replace", "charge air cooler|drain", "air filter primary cartridge|replace"]
    for d, hrs in visits:
        m = d.month
        lines = [("exhaust line pipes and hoses|inspect", 0.5, ""), ("starter battery|charge", 0.3, "")]
        if m == 1:
            lines[1] = ("starter battery|charge", 0.3,
                        "Owner asked for monthly charging after the generator failed to start twice in 2024 "
                        "when the vessel sat alongside for several weeks with the battery discharged.")
        if m in quarterly:
            lines += [(t, 0.5, "") for t in h500]
        if m in (1, 6, 9):  # oil change skipped in April: Jan -> Jun is 750 h
            lines.append(("engine oil and oil filter|replace", 1.5, ""))
        if m in (1, 7):
            lines.append(("PMGi inverter heat sinks|inspect", 0.3, ""))
            lines.append(("exhaust mixing elbow|descale", 2.0,
                          "Mixing elbow half blocked with salt scale at the 2024 overhaul; high exhaust "
                          "back-pressure alarms. Owner agreed six-monthly descaling." if m == 1 else ""))
        if m == 1:
            lines.append(("PMGi inverter heat sinks|clean", 0.5, ""))
            lines.append(("fuel water separator|drain", 0.2, ""))
        for job, spent, note in lines:
            comp, action = job.split("|")
            rows.append([d.isoformat(), ASSET, VENDOR, comp, action, hrs, spent, ("SIMULATED. " + note).strip()])
    return rows


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    baseline = {
        "_note": ("PROPOSED baseline for sign-off, not yet approved by a person. Tasks, intervals, pages and quotes "
                  f"come from the real {PANDA} manual and the {HATZ} manual (placeholder for the actual engine "
                  "documents). Daily/weekly operator checks, storage/downtime measures, one-off initial services and "
                  "condition-only tasks are left out of the vendor baseline. In quotes, ' ... ' joins a table's interval header "
                  "to the row it applies to."),
        "asset_id": ASSET,
        "tasks": [
            {"key": k, "source": src, "page": pg, "component": c, "action": a, "intervals": iv(ivs),
             "spec": spec, "safety_critical": sc, "source_quote": q, "placeholder": src == HATZ}
            for k, src, pg, c, a, ivs, spec, sc, q in BASELINE
        ],
    }
    (OUT / "proposed_baseline.json").write_text(json.dumps(baseline, indent=2) + "\n")

    contract = [
        "SIMULATED VENDOR CONTRACT - NOT A REAL DOCUMENT. FOR POC TESTING ONLY.",
        "Gaps against the PANDA-60I baseline are planted on purpose; see planted_gaps.json.",
        "",
        f"{VENDOR} - Schedule B: Planned Maintenance, asset {ASSET} (Fischer Panda 60i generator set)",
        "Intervals are whichever comes first.",
        "",
    ] + [f"B.{i} {line}" for i, (*_, line) in enumerate(CONTRACT, 1)]
    (OUT / "vendor_contract_SIMULATED.txt").write_text("\n".join(contract) + "\n")
    (OUT / "vendor_expected_tasks.json").write_text(json.dumps(
        [{"component": c, "action": a, "intervals": iv(ivs), "spec": s} for c, a, ivs, s, _ in CONTRACT], indent=2) + "\n")

    with open(OUT / "tickets_SIMULATED.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "asset_id", "vendor", "component", "action", "meter_hours", "time_spent_hours", "notes"])
        w.writerows(tickets())

    key = {
        "_note": "SIMULATED answer key. Success = every gap below is found and no other gap is reported.",
        "asset_id": ASSET,
        "vendor": VENDOR,
        "safety_critical_components": [c for _, _, _, c, _, _, _, sc, _ in BASELINE if sc],
        "gaps": [{"id": i, "type": t, "component": c, "why": w} for i, t, c, w in GAPS],
        "expected_info": [
            {"type": "tightened_interval", "component": "starter battery", "why": "monthly vs 2 months; reason in ticket notes"},
            {"type": "vendor_addition", "component": "exhaust mixing elbow", "why": "not in OEM; reason in ticket notes"},
        ],
    }
    (OUT / "planted_gaps.json").write_text(json.dumps(key, indent=2) + "\n")
    print("written to", OUT)
