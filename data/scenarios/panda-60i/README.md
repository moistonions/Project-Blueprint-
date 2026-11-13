# Panda 60i scenario

Asset `PANDA-60I`: a Fischer Panda 60i PMS generator set with a Hatz 3H50/4H50 engine.

| File | What it is | Real or simulated |
|---|---|---|
| `proposed_baseline.json` | 22 OEM tasks for vendor comparison, each with page and quote | **Real** manual content. Hatz rows come from a **placeholder** engine manual. The list is **proposed**, waiting for a person to sign it off. |
| `vendor_contract_SIMULATED.txt` | Vendor planned-maintenance schedule | **Simulated** |
| `tickets_SIMULATED.csv` | 12 monthly vendor checklists for 2025, about 150 running hours a month | **Simulated** |
| `planted_gaps.json` | Answer key: 10 planted gaps and 2 expected informational findings | **Simulated** |
| `vendor_expected_tasks.json` | What a correct extraction of the contract returns, used by the offline test | **Simulated** |

These tasks are left out of the vendor baseline:
- Daily and weekly operator checks.
- The 50-hour full-load run.
- Storage and downtime preservation.
- One-off initial services.
- Tasks that are condition-based only ("regularly", "if necessary").

The person signing off should confirm these exclusions, the poly v belt version, and that the engine has a DPF and an EGR (the Hatz manual lists them for TIC/TICD engines only).

Regenerate the files with `python scripts/make_panda_scenario.py`.
- Score offline (the contract extraction is faked): `pytest tests/test_scenario_panda.py`.
- Score with real extraction (spends tokens): `python scripts/score_scenario.py panda-60i`.
