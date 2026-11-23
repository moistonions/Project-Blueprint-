# Project Blueprint

A proof-of-concept hybrid structured/unstructured RAG platform that compares
**OEM maintenance requirements** against **vendor service schedules**, in both
directions:

- **Vendor does less than OEM** (missed tasks, stretched intervals). A
  deterministic rules engine flags these as compliance gaps.
- **Vendor does more than OEM** (extra tasks, tighter intervals). An LLM agent
  searches field logs and vendor documents for the operating reason (heavy
  load, dust, heat...) and records it, so the "field wisdom" isn't lost.

Findings and rationales are indexed in a vector database alongside the source
documents, and a chat page lets engineers ask questions across all of it.

## How it works

```
OEM manual ──► extract tasks ──► person signs off baseline ─┐   (needs-review tasks = failed)
vendor contract ──► extract tasks ──────────────────────────┼─► rules engine ──► gap findings
vendor checklists (CSV or form) ──► tickets + meter hours ──┘   (deterministic)      │
        │ notes                                                                      │
        ▼                                                                            ▼
     Chroma ◄──────────── rationale agent (vendor does more: quote-verified) ◄── info findings
        ▲
        └── Ask page (RAG chat over documents, tickets, findings, rationales)
```

| Module | Role |
| --- | --- |
| `blueprint/ingest.py` | PDF/TXT/MD/CSV/EML to page text and overlapping chunks |
| `blueprint/extract.py` | LLM structured outputs (Claude by default): component, action, part IDs, fluid spec, intervals, source quote, page, needs-review flag |
| `blueprint/normalize.py` | Unit normalization (months to days, miles to km...), canonical task keys (`change` = `replace`), fuzzy component matching |
| `blueprint/rules.py` | **Deterministic** approved-OEM-baseline vs vendor schedule comparison. No LLM. |
| `blueprint/execution.py` | **Deterministic** late/skipped check from checklist tickets and hour-meter readings |
| `blueprint/tickets.py` | Vendor checklist CSV import (format provisional) |
| `blueprint/rationale.py` | Retrieval + LLM agent explaining vendor extras; keeps only quotes found verbatim in the evidence |
| `blueprint/rag.py` | Chat answers with numbered citations |
| `blueprint/llm.py` | Claude (default) and OpenAI clients, local or OpenAI embeddings |
| `blueprint/stores/structured.py` | SQLite: documents (with baseline status), tasks, tickets, findings, rationales |
| `blueprint/stores/vector.py` | `VectorStore` interface + `ChromaStore`. Add a `PgVectorStore` here to switch to pgvector. |
| `app.py` | Streamlit UI: Ingest, Baseline sign-off, Checklist entry, Gap report, Field wisdom, Ask |

### Baseline sign-off

Nothing is compared until a person approves the OEM task list extracted from a
manual (Baseline sign-off page). There they can fix extraction errors, mark
**safety-critical** tasks (zero tolerance) and resolve tasks the extractor
flagged **needs review** (garbled tables, "as required"). Unresolved needs-review
tasks count as failed in the report. Saving any edit returns the baseline to draft.

### What the engine flags

Intervals are "whichever comes first" across calendar time, running hours,
distance and cycles; every dimension is checked.

| Finding | Severity | Meaning |
| --- | --- | --- |
| `missing_task` | critical | OEM task with no matching vendor task |
| `beyond_tolerance` | critical | Vendor interval longer than OEM by more than the tolerance (10% by default, `BLUEPRINT_TOLERANCE`; 0 for safety-critical tasks) |
| `longer_interval` | warning | Vendor interval longer than OEM but within tolerance |
| `spec_mismatch` | warning | Different part number or fluid spec on a matched task (flagged as ambiguous) |
| `missing_interval_basis` | warning | OEM says "500 h **or** 6 months" but the vendor only tracks one, or states no interval |
| `execution_gap` | critical | Checklist tickets show the task done late, or not done since a date |
| `needs_review` | critical (failed) | OEM task the extractor wasn't sure about, not yet resolved at sign-off |
| `tightened_interval` | info | Vendor services more often than OEM. Sent to the rationale agent. |
| `vendor_addition` | info | Vendor task the OEM doesn't require. Sent to the rationale agent. |

Tasks are paired one-to-one per asset: identical task, then shared part number,
then similar component name (handles "hyd filters" vs "hydraulic return filter").
Each finding records the **match basis and confidence**, shown in the report.
Anything that fails to match shows up as a missing task, never silently dropped.

Execution checks use the window from an asset's first to its latest checklist
ticket. Running hours come from the meter readings on tickets, which also give
the asset's usage rate (hours per month).

### Why vendors do extra work

For each `vendor_addition` / `tightened_interval`, the rationale agent searches
ticket notes and field documents and returns a reason with quotes. Quotes are
checked against the retrieved text; a reason with no verified quote is stored as
**unconfirmed**. Each item also gets a status, justified / unjustified / unknown
(only "unknown" without a verified quote). The POC shows the status; it does not
include an approval flow for extra work.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add ANTHROPIC_API_KEY
streamlit run app.py
```

For a demo, open **Ingest → Demo scenario: Panda 60i generator** and click
**Load Panda 60i demo** (a few LLM calls to read the simulated contract), then
open the **Gap report** and click a row to see the OEM and vendor source quotes.

By default the app uses **Claude** (`claude-opus-5-5`) for extraction, the
rationale agent and chat, so you only need an `ANTHROPIC_API_KEY`. Claude has
no embeddings API, so the search index uses a small local embedding model
(all-MiniLM-L6-v2, about 80 MB, downloaded once on first run; no key needed).
Claude requests opt into server-side refusal fallbacks (`fallbacks: "default"`).

To use OpenAI instead, set `BLUEPRINT_LLM_PROVIDER=openai` and `OPENAI_API_KEY`
(OpenAI embeddings are then the default). Models and embeddings can be overridden
in `.env`; see `.env.example`. Switching embeddings starts a fresh search
index, because vectors from different models can't be mixed. Data is stored
under `storage/` (git-ignored).

### Adding real documents

- **OEM manuals:** drop them in [`data/oem_manuals/`](data/oem_manuals/README.md)
  and upload on the Ingest page, or bulk-load:
  `python scripts/ingest_folder.py data/oem_manuals/PUMP-P101 --kind oem --asset PUMP-P101`
- **Vendor schedules and field documents:** see [`data/vendor_docs/`](data/vendor_docs/README.md).

Both folders are git-ignored so manuals and contracts stay local. Scanned PDFs
need OCR before upload.

### Vendor checklists

Enter a visit on the **Checklist entry** page, or upload a CSV on the Ingest page
(template downloadable there; columns `date, asset_id, vendor, component, action,
meter_hours, time_spent_hours, notes`). The checklist format is still provisional.

### Synthetic sample data and the success test

[`data/samples/`](data/samples/README.md) holds a **fictional** generator
(`SAMPLE-GEN-01`): an OEM spec, a vendor contract and checklist tickets with
**10 planted gaps across all five gap types**, plus an answer key
(`planted_gaps.json`). It stands in for a real manual until the real ones arrive
and is tagged SAMPLE everywhere. It is not real maintenance guidance.

```bash
python scripts/load_samples.py   # real Claude extraction, scored against the answer key
```

Success = every planted gap found and no false alarms. The script exits non-zero otherwise.

## Tests

```bash
pytest
```

Tests run offline: the LLM calls are replaced with fakes and Chroma runs
in memory. They cover the rules and execution engines, normalization, ticket
import, the full pipeline scored against the planted gaps, and every Streamlit page.

## Known POC limits / next steps

- Asset ID is entered at upload time; multi-asset manuals need one upload per asset for now.
- No OCR for scanned manuals; no table-specific PDF parsing yet (text extraction handles most digital tables).
- Rationale agent is a single retrieve-then-reason step; it can become a tool-calling agent later.
- Checklist format is provisional; execution checks compare against the OEM baseline, not the contract.
- No approval flow for vendor extra work yet (status is display-only).
- No auth or multi-user separation.
- pgvector backend: implement `VectorStore` in `blueprint/stores/vector.py` and set `BLUEPRINT_VECTOR_BACKEND=pgvector`.
