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
upload ──► read pages ──► OpenAI structured extraction ──► SQLite (tasks)
   │                         (OEM + vendor docs only)            │
   │                                                             ▼
   └──► chunk + embed ──► Chroma ◄── findings ◄── rules engine (deterministic)
                            ▲  │                         │
                            │  └──► rationale agent ◄────┘ vendor additions /
                            │            │                 tightened intervals
                            └── rationales
                            ▲
           Ask page (RAG chat) queries everything above
```

| Module | Role |
| --- | --- |
| `blueprint/ingest.py` | PDF/TXT/MD/CSV/EML to page text and overlapping chunks |
| `blueprint/extract.py` | OpenAI structured outputs: asset, component, action, part IDs, intervals, source quote, page |
| `blueprint/normalize.py` | Unit normalization (months to days, miles to km...) and canonical task keys (`change` = `replace`) |
| `blueprint/rules.py` | **Deterministic** OEM vs vendor comparison. No LLM. |
| `blueprint/rationale.py` | Retrieval + LLM agent explaining vendor additions; marks them `UNDOCUMENTED` when no evidence exists |
| `blueprint/rag.py` | Chat answers with numbered citations |
| `blueprint/stores/structured.py` | SQLite: documents, tasks, findings, rationales |
| `blueprint/stores/vector.py` | `VectorStore` interface + `ChromaStore`. Add a `PgVectorStore` here to switch to pgvector. |
| `app.py` | Streamlit UI: Ingest, Gap report, Field wisdom, Ask |

### What the rules engine flags

| Finding | Severity | Meaning |
| --- | --- | --- |
| `missing_task` | critical | OEM task with no matching vendor task |
| `extended_interval` | critical | Vendor interval longer than OEM in any dimension (calendar, hours, distance, cycles), beyond a 2% unit-conversion tolerance |
| `missing_interval_basis` | warning | OEM says "500 h **or** 6 months" but the vendor only tracks one of them, or states no interval |
| `tightened_interval` | info | Vendor services more often than OEM. Sent to the rationale agent. |
| `vendor_addition` | info | Vendor task the OEM doesn't require. Sent to the rationale agent. |

Tasks are paired one-to-one per asset by exact task key, then same action +
shared part number, then same action + similar component name. Matching is the
part most likely to need tuning on real manuals; anything that fails to match
shows up as a missing task (never silently dropped), so the engine errs toward
over-flagging.

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add OPENAI_API_KEY
streamlit run app.py
```

Models are configurable in `.env` (defaults: `gpt-5-mini` for extraction, the
agent and chat, `text-embedding-3-small` for embeddings). Data is stored under
`storage/` (git-ignored).

### Adding real documents

- **OEM manuals:** drop them in [`data/oem_manuals/`](data/oem_manuals/README.md)
  and upload on the Ingest page, or bulk-load:
  `python scripts/ingest_folder.py data/oem_manuals/PUMP-P101 --kind oem --asset PUMP-P101`
- **Vendor schedules and field documents:** see [`data/vendor_docs/`](data/vendor_docs/README.md).

Both folders are git-ignored so manuals and contracts stay local. Scanned PDFs
need OCR before upload.

### Synthetic sample data

[`data/samples/`](data/samples/README.md) holds three **fictional** documents
used only to test the pipeline. They contain one of each finding type. Load
them with the button on the Ingest page or `python scripts/load_samples.py`.
They are tagged SAMPLE in the app and are not real maintenance guidance.

## Tests

```bash
pytest
```

Tests run offline: the OpenAI calls are replaced with fakes and Chroma runs
in memory. They cover the rules engine, normalization, chunking, the full
pipeline on the sample data, and a smoke test of every Streamlit page.

## Known POC limits / next steps

- Asset ID is entered at upload time; multi-asset manuals need one upload per asset for now.
- No OCR for scanned manuals; no table-specific PDF parsing yet (text extraction handles most digital tables).
- Rationale agent is a single retrieve-then-reason step; it can become a tool-calling agent later.
- No auth or multi-user separation.
- pgvector backend: implement `VectorStore` in `blueprint/stores/vector.py` and set `BLUEPRINT_VECTOR_BACKEND=pgvector`.
