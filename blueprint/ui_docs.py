"""Documentation pages shown inside the Streamlit app: the disclaimer, About Us and Methodology.

Kept separate from app.py so the page text is easy to edit without touching app logic.
Flowcharts are Graphviz DOT strings, which st.graphviz_chart renders in the browser
(no system Graphviz install needed).
"""

from __future__ import annotations

import streamlit as st

NOTICE = """**IMPORTANT NOTICE:** This web application is developed as a proof-of-concept prototype. The information \
provided here is NOT intended for actual usage and should not be relied upon for making any decisions, especially \
those related to financial, legal, or healthcare matters.

Furthermore, please be aware that the LLM may generate inaccurate or incorrect information. You assume full \
responsibility for how you use any generated output.

Always consult with qualified professionals for accurate and personalised advice."""


def show_notice(expanded: bool = False) -> None:
    """The bootcamp's required disclaimer. Shown at the top of every page."""
    with st.expander("⚠️ IMPORTANT NOTICE", expanded=expanded):
        st.markdown(NOTICE)


# ---------------------------------------------------------------------------- About Us

def render_about() -> None:
    """Render the About Us page: problem, objectives, scope, data sources, features."""
    st.header("About Us")
    st.markdown(
        "**Project Blueprint** is a proof of concept (POC) that checks whether vendor maintenance matches what the "
        "equipment manufacturer (OEM) recommends, and keeps a record of *why* vendors sometimes do more.\n\n"
        "Prepared by **Angus Neo** and **Matthew Cheng** (HTX) for the **AI Champions Bootcamp**."
    )

    st.subheader("Problem")
    st.markdown(
        "- **Compliance risk.** Vendor schedules can miss OEM tasks or stretch service intervals, which leads to "
        "unplanned downtime, early failures and voided warranties. Checking schedules against long OEM manuals by hand "
        "is slow and error-prone.\n"
        "- **Lost field knowledge.** Vendors often do extra work to cope with real site conditions (dust, heat, heavy "
        "load). The reasons sit in ticket notes and emails, so later teams can't tell why a deviation exists."
    )

    st.subheader("Objectives")
    st.markdown(
        "1. Extract maintenance tasks and intervals from OEM manuals and a vendor contract, with a person signing off "
        "the OEM baseline before it is used.\n"
        "2. Flag where the vendor does **less** than the OEM (missing tasks, longer intervals, late or skipped work) "
        "using a deterministic rules engine, so results are repeatable and explainable.\n"
        "3. Capture where the vendor does **more** than the OEM, and the reason, backed by a verbatim source quote.\n"
        "4. Let engineers ask plain-English questions and get answers that cite their sources."
    )

    st.subheader("Scope")
    c1, c2 = st.columns(2)
    c1.markdown(
        "**In scope (POC)**\n"
        "- One demo asset: a Fischer Panda 60i marine generator\n"
        "- One OEM baseline, one simulated vendor contract and simulated checklists\n"
        "- Gap report, field-wisdom capture and Q&A\n"
        "- Human sign-off of the OEM baseline"
    )
    c2.markdown(
        "**Out of scope**\n"
        "- Live or confidential company data\n"
        "- Integration with maintenance or ERP systems\n"
        "- Approval workflows and user accounts\n"
        "- Every document format and edge case"
    )

    st.subheader("Data sources")
    st.markdown(
        "| Source | What it is | Status |\n"
        "| --- | --- | --- |\n"
        "| Fischer Panda 60i PMS manual | OEM generator maintenance schedule | Public OEM document |\n"
        "| Hatz 3H50/4H50 engine manual | OEM engine maintenance intervals | Public document, **placeholder** for the actual engine |\n"
        "| Vendor service contract | What the vendor commits to do | **Simulated**, fictional vendor, 10 planted gaps |\n"
        "| Vendor checklists (CSV) | Visits, tasks done, hour-meter readings, notes | **Simulated** |\n"
        "| Synthetic generator sample | Pipeline test data | **Synthetic**, tagged SAMPLE in the app |\n\n"
        "No confidential or operational data is used. Simulated and sample records are labelled throughout the app."
    )

    st.subheader("Features")
    st.markdown(
        "| Page | What you can do |\n"
        "| --- | --- |\n"
        "| **Ingest** | Upload OEM manuals, vendor contracts, field reports and checklist CSVs, or load the Panda 60i demo |\n"
        "| **Baseline sign-off** | Review and correct the tasks extracted from the OEM manual, mark safety-critical "
        "tasks (zero tolerance), then approve |\n"
        "| **Checklist entry** | Record a vendor site visit: tasks done, time spent, hour-meter reading, notes |\n"
        "| **Gap report** | See every compliance gap, sorted by severity, with the OEM and vendor source quotes side by side; download as CSV |\n"
        "| **Field wisdom** | See why the vendor does extra work, found by an AI agent that searches the notes itself; verified quotes, or \"unconfirmed\" when there is no evidence, plus the agent's search steps |\n"
        "| **Ask** | Ask questions across documents, findings and rationales; answers cite numbered sources |\n"
        "| **Methodology** | How the data flows and how each use case works |"
    )

    st.subheader("Intended users")
    st.markdown(
        "Maintenance and reliability engineers, contract and procurement teams reviewing vendor contracts, and field "
        "engineers or new team members looking up past decisions."
    )


# ---------------------------------------------------------------------------- Methodology

_OVERVIEW = """
digraph {
  rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#F2F5F9", fontname="Helvetica", fontsize=11];
  edge [fontname="Helvetica", fontsize=9];
  oem [label="OEM manual\\n(PDF/TXT)"]; ven [label="Vendor contract"]; tix [label="Vendor checklists\\n(CSV or form)"];
  fld [label="Field reports /\\nemails"];
  ext [label="LLM extraction\\n(structured output)", fillcolor="#DCE8F5"];
  sign [label="Human sign-off\\nof OEM baseline", fillcolor="#FFF4D6"];
  sql [label="SQLite\\ntasks, tickets,\\nfindings, rationales", shape=cylinder];
  vec [label="Chroma\\nvector index", shape=cylinder];
  rules [label="Deterministic\\nrules engine", fillcolor="#E3F2E1"];
  agent [label="Rationale agent\\n(LLM + search tools)", fillcolor="#DCE8F5"];
  rag [label="Ask (RAG chat)", fillcolor="#DCE8F5"];
  oem -> ext; ven -> ext; ext -> sign [label="OEM tasks"]; sign -> sql; ext -> sql [label="vendor tasks"];
  tix -> sql; oem -> vec [label="chunks"]; ven -> vec; fld -> vec; tix -> vec [label="notes"];
  sql -> rules -> sql [label="gap findings"]; rules -> agent [label="vendor does more"];
  vec -> agent; agent -> sql [label="rationale + quotes"]; agent -> vec; rules -> vec;
  vec -> rag;
}
"""

_GAP_FLOW = """
digraph {
  rankdir=TB; node [shape=box, style="rounded,filled", fillcolor="#F2F5F9", fontname="Helvetica", fontsize=11];
  a [label="Upload OEM manual + vendor contract"];
  b [label="Split into page-tagged windows"];
  c [label="LLM extracts tasks: component, action,\\nintervals, part no., spec, source quote, page", fillcolor="#DCE8F5"];
  d [label="Code checks: drop intervals not in the quote,\\nflag 'as required' as needs review"];
  e [label="Engineer reviews + approves OEM baseline", fillcolor="#FFF4D6"];
  f [label="Normalise units + match OEM to vendor tasks\\n(same task > shared part no. > similar name)"];
  g [label="Rules: missing task, longer interval,\\nbeyond tolerance, spec mismatch, basis not tracked", fillcolor="#E3F2E1"];
  h [label="Checklists: done late or skipped\\n(calendar + hour meter)", fillcolor="#E3F2E1"];
  i [label="Gap report with severity,\\nmatch confidence and source quotes"];
  a -> b -> c -> d -> e -> f -> g -> i; f -> h -> i;
}
"""

_WISDOM_FLOW = """
digraph {
  rankdir=TB; node [shape=box, style="rounded,filled", fillcolor="#F2F5F9", fontname="Helvetica", fontsize=11];
  a [label="Rules engine finds the vendor doing MORE\\n(extra task or tighter interval)"];
  b [label="Claude agent decides what to do next", fillcolor="#DCE8F5"];
  t [label="Tools (run by the app):\\nsearch_field_notes · search_vendor_documents\\nget_oem_requirement  (max 4 searches)", shape=box3d];
  s [label="submit_rationale: reason, status,\\nconditions, quotes, confidence", fillcolor="#DCE8F5"];
  d [label="Code verifies each quote appears\\nverbatim in what the tools returned"];
  e [label="Confirmed: rationale + quotes", fillcolor="#E3F2E1"];
  f [label="Unconfirmed: status set to unknown", fillcolor="#FFF4D6"];
  g [label="Stored in SQLite + indexed for Ask;\\nshown on Field wisdom"];
  a -> b; b -> t [label="tool call"]; t -> b [label="results"]; b -> s [label="done"]; s -> d; d -> e [label="quote found"]; d -> f [label="no quote"]; e -> g; f -> g;
}
"""

_ASK_FLOW = """
digraph {
  rankdir=TB; node [shape=box, style="rounded,filled", fillcolor="#F2F5F9", fontname="Helvetica", fontsize=11];
  a [label="User question (+ optional asset filter)"];
  b [label="Input check: length limit, trim"];
  c [label="Embed question, search Chroma\\n(documents, tickets, findings, rationales)"];
  d [label="Top 8 chunks numbered [1]..[8]\\nand wrapped as untrusted data"];
  e [label="LLM answers only from context,\\ncites [n], declines off-topic", fillcolor="#DCE8F5"];
  f [label="Answer + expandable sources\\nwith similarity scores"];
  a -> b -> c -> d -> e -> f;
}
"""


def render_methodology() -> None:
    """Render the Methodology page: data flow, one flowchart per use case, safeguards, evaluation."""
    st.header("Methodology")
    st.markdown(
        "Project Blueprint is a hybrid structured / unstructured RAG pipeline. The LLM reads documents and explains; "
        "the compliance decision itself is made by deterministic code, so every gap can be traced and reproduced."
    )

    st.subheader("Overall data flow")
    st.graphviz_chart(_OVERVIEW, width="stretch")
    st.markdown(
        "- **Structured store (SQLite):** documents with baseline status, extracted tasks, checklist tickets, findings, rationales.\n"
        "- **Vector store (Chroma):** overlapping text chunks from every document, plus ticket notes, findings and "
        "rationales, embedded with a small local model (all-MiniLM-L6-v2). The store sits behind an interface so pgvector can replace it.\n"
        "- **LLM:** Claude by default (OpenAI optional), used for extraction, the rationale agent and chat."
    )

    st.subheader("Use case 1: Compliance gap detection")
    st.graphviz_chart(_GAP_FLOW)
    st.markdown(
        "- **Prompt engineering:** the extraction prompt defines each field, a fixed list of verbs, units and the "
        "'whichever comes first' rule, tells the model not to infer from general knowledge, and asks it to flag "
        "rather than guess. Output is forced into a Pydantic schema (structured outputs).\n"
        "- **Guardrails in code:** intervals that don't appear in the quoted source are removed and the task is flagged "
        "for review; uncertain tasks count as failed until a person resolves them.\n"
        "- **Rules:** intervals are normalised (months to days, miles to km) and compared on every dimension. "
        "Tolerance is 10% on recurring tasks and zero for tasks marked safety-critical at sign-off."
    )

    st.subheader("Use case 2: Capturing field wisdom")
    st.graphviz_chart(_WISDOM_FLOW)
    st.markdown(
        "- **Prompt chaining:** extraction feeds the rules engine; only its \"vendor does more\" findings go to the "
        "rationale agent.\n"
        "- **LLM agent with tools:** Claude decides which searches to run (field notes, vendor documents, the OEM "
        "requirement) and when it has enough, then calls `submit_rationale`. Tool inputs are schema-checked "
        "(strict tools), searches are capped at 4 and the loop at 6 requests to bound cost, and every tool call is "
        "logged and shown on the Field wisdom page. If the agent doesn't submit, a fixed retrieve-then-ask chain runs instead.\n"
        "- **Grounding:** a reason only counts as confirmed when its quote is found verbatim in the retrieved text; "
        "otherwise it is shown as unconfirmed with status \"unknown\"."
    )

    st.subheader("Use case 3: Ask (RAG chat)")
    st.graphviz_chart(_ASK_FLOW)
    st.markdown(
        "Answers come only from retrieved context and cite numbered sources, which the user can expand to check. "
        "If nothing relevant is indexed, the app says so instead of guessing."
    )

    st.subheader("Safeguards")
    st.markdown(
        "- **Prompt injection:** uploaded text, retrieved evidence and user questions are wrapped in labelled tags "
        "(tags inside the text are stripped), and every system prompt tells the model to treat them as data and ignore "
        "instructions inside them. The chat is limited to maintenance topics and questions are length-capped.\n"
        "- **Limited blast radius:** the LLM can't take actions: it only returns text or schema-checked data. "
        "Compliance gaps never depend on LLM judgement.\n"
        "- **Verification:** source quotes are checked against the documents; humans sign off the OEM baseline.\n"
        "- **Access:** the deployed app is password protected; API keys live in server-side secrets, never in code.\n"
        "- **Data:** only public manuals and clearly labelled simulated data are used."
    )

    st.subheader("Evaluation")
    st.markdown(
        "The Panda 60i scenario plants 10 known gaps in the simulated vendor contract and checklists. A scoring script "
        "(`scripts/score_scenario.py`) checks that all 10 are found with no false alarms; the latest run with Claude "
        "found 10/10 with 0 false alarms. Automated tests cover extraction checks, normalisation, matching, rules, "
        "the rationale agent (with a scripted model) and every app page."
    )

    st.subheader("Limitations")
    st.markdown(
        "POC only: one asset, simulated vendor data, a placeholder engine manual, and storage that resets when the "
        "hosted app restarts (reload the demo from the Ingest page). Not for operational decisions."
    )
