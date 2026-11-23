"""Streamlit UI for Project Blueprint.

Run with:  streamlit run app.py

Pages: About Us, Ingest, Baseline sign-off, Checklist entry, Gap report, Field wisdom, Ask, Methodology.
Configuration comes from environment variables or .env locally, and from st.secrets when hosted
(Streamlit Community Cloud). Set BLUEPRINT_APP_PASSWORD to require a password.
"""

from __future__ import annotations

import hmac
import os
import traceback
from contextlib import contextmanager
from datetime import date

import pandas as pd
import streamlit as st

from blueprint.config import get_settings
from blueprint.ingest import SUPPORTED_SUFFIXES
from blueprint.models import (
    BaselineStatus,
    ExtraWorkStatus,
    FindingType,
    MaintenanceTask,
    Severity,
    SourceKind,
    Ticket,
)
from blueprint.normalize import format_intervals, parse_intervals
from blueprint.pipeline import Blueprint
from blueprint.rag import source_label
from blueprint.tickets import CSV_TEMPLATE, parse_csv
from blueprint.ui_docs import render_about, render_methodology, show_notice

st.set_page_config(page_title="Project Blueprint", page_icon="🛠️", layout="wide", menu_items={})

KIND_LABELS = {
    SourceKind.OEM: "OEM manual / spec",
    SourceKind.VENDOR: "Vendor contract / schedule",
    SourceKind.FIELD: "Field report / email",
}
SEVERITY_ICON = {Severity.CRITICAL: "🔴", Severity.WARNING: "🟠", Severity.INFO: "🔵"}
STATUS_ICON = {ExtraWorkStatus.JUSTIFIED: "✅", ExtraWorkStatus.UNJUSTIFIED: "⛔", ExtraWorkStatus.UNKNOWN: "❔"}
SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
TYPE_LABELS = {
    FindingType.MISSING_TASK: "Missing task",
    FindingType.BEYOND_TOLERANCE: "Interval beyond tolerance",
    FindingType.LONGER_INTERVAL: "Longer interval (within tolerance)",
    FindingType.MISSING_INTERVAL_BASIS: "Interval basis not tracked",
    FindingType.SPEC_MISMATCH: "Part / fluid spec differs",
    FindingType.EXECUTION_GAP: "Done late or skipped",
    FindingType.NEEDS_REVIEW: "Needs review (counts as failed)",
    FindingType.TIGHTENED_INTERVAL: "Vendor services more often",
    FindingType.VENDOR_ADDITION: "Vendor extra task",
}
TYPE_HELP = {
    FindingType.MISSING_TASK: "The OEM requires this task but the vendor schedule has nothing matching it.",
    FindingType.BEYOND_TOLERANCE: "The vendor's interval is longer than the OEM's by more than the tolerance "
                                  "(zero for safety-critical tasks).",
    FindingType.LONGER_INTERVAL: "The vendor's interval is longer than the OEM's but still within tolerance.",
    FindingType.MISSING_INTERVAL_BASIS: "The OEM sets e.g. '500 hours or 6 months'; the vendor tracks only one, "
                                        "or states no interval.",
    FindingType.SPEC_MISMATCH: "Same task, different part number or fluid spec. Flagged as ambiguous for a person to check.",
    FindingType.EXECUTION_GAP: "The vendor's checklists show the task done late, or not done since a date.",
    FindingType.NEEDS_REVIEW: "The extractor wasn't sure about this OEM task and it wasn't resolved at sign-off.",
    FindingType.TIGHTENED_INTERVAL: "The vendor services more often than the OEM asks. See Field wisdom for why.",
    FindingType.VENDOR_ADDITION: "The vendor does work the OEM doesn't require. See Field wisdom for why.",
}
PROVIDER_NAMES = {"anthropic": "Claude", "openai": "OpenAI"}
# Sidebar labels: the workflow pages are numbered in the order a new user should visit them.
NAV_LABELS = {
    "About Us": "🏠 About Us (start here)",
    "Ingest": "1 · Load documents",
    "Baseline sign-off": "2 · Sign off OEM baseline",
    "Checklist entry": "3 · Log a vendor visit (optional)",
    "Gap report": "4 · Review compliance gaps",
    "Field wisdom": "5 · See why vendors do more",
    "Ask": "6 · Ask a question",
    "Methodology": "📘 Methodology",
}
NAV_CAPTIONS = {
    "About Us": "What the app does and how to use it",
    "Ingest": "Load the demo or upload manuals and contracts",
    "Baseline sign-off": "Check and approve the OEM task list",
    "Checklist entry": "Record tasks a vendor did on site",
    "Gap report": "Where the vendor does less than the OEM",
    "Field wisdom": "Reasons behind extra vendor work",
    "Ask": "Chat with documents and findings",
    "Methodology": "How it works, with flowcharts",
}
PAGES = ["About Us", "Ingest", "Baseline sign-off", "Checklist entry", "Gap report", "Field wisdom", "Ask",
         "Methodology"]


def load_secrets_into_env() -> None:
    """On Streamlit Community Cloud, keys are pasted as secrets; copy top-level ones into the
    environment so blueprint.config reads them like a local .env. Real env vars win."""
    try:
        items = dict(st.secrets)
    except Exception:  # noqa: BLE001  (no secrets.toml locally is normal)
        return
    for k, v in items.items():
        if isinstance(v, (str, int, float, bool)):
            os.environ.setdefault(k, str(v))


def password_ok() -> bool:
    """Simple shared-password gate, on when BLUEPRINT_APP_PASSWORD is set."""
    expected = os.getenv("BLUEPRINT_APP_PASSWORD")
    if not expected or st.session_state.get("authed"):
        return True
    st.title("Project Blueprint")
    show_notice(expanded=True)
    pw = st.text_input("Password", type="password", help="Ask the project team for the password.")
    if pw:
        if hmac.compare_digest(pw.encode(), expected.encode()):
            st.session_state["authed"] = True
            st.rerun()
        st.error("Wrong password.")
    return False


load_secrets_into_env()
if not password_ok():
    st.stop()


@st.cache_resource
def get_blueprint() -> Blueprint:
    return Blueprint.from_settings(get_settings())


try:
    bp = get_blueprint()
except RuntimeError as e:
    st.error(f"The app couldn't start: {e}")
    st.info("Set the API key in `.env` (see `.env.example`) or as an environment variable, then restart the app.")
    st.stop()

st.sidebar.title("Project Blueprint")
st.sidebar.caption("Check vendor maintenance against OEM requirements, and keep the reasons behind any differences.")
page = st.sidebar.radio(
    "Go to",
    PAGES,
    key="nav",
    format_func=NAV_LABELS.get,
    captions=[NAV_CAPTIONS[p] for p in PAGES],
    help="New here? Start with About Us, then follow steps 1 to 6 in order.",
)
assets = bp.db.assets()

# A small progress tracker so a new user can see where they are in the workflow.
_docs = bp.db.documents()
_has_oem = any(d.kind == SourceKind.OEM for d in _docs)
_approved = any(d.kind == SourceKind.OEM and d.baseline_status == BaselineStatus.APPROVED for d in _docs)
_has_vendor = any(d.kind == SourceKind.VENDOR for d in _docs)
_n_findings = sum(len(bp.db.findings(a)) for a in assets)
st.sidebar.divider()
st.sidebar.markdown("**Your progress**")
st.sidebar.markdown(
    f"{'✅' if _has_oem and _has_vendor else '⬜'} Documents loaded (OEM + vendor)  \n"
    f"{'✅' if _approved else '⬜'} OEM baseline approved  \n"
    f"{'✅' if _n_findings else '⬜'} Gap analysis run"
    + (f" ({_n_findings} findings)" if _n_findings else "")
)
if not _docs:
    st.sidebar.caption("👉 Quickest start: **1 · Load documents** → Load Panda 60i demo.")
st.sidebar.divider()
st.sidebar.caption(
    f"🟢 LLM: {PROVIDER_NAMES.get(bp.settings.llm_provider, bp.settings.llm_provider)} "
    f"({bp.settings.chat_model}), key loaded"
)


@contextmanager
def llm_guard(what: str):
    """Show a readable error instead of a traceback when an LLM or network call fails."""
    try:
        yield
    except ValueError as e:  # bad input (e.g. an over-long question), not an outage
        st.warning(str(e))
    except Exception as e:  # noqa: BLE001  (Streamlit's own stop/rerun signals are BaseException)
        st.error(
            f"{what} didn't finish: {e}. This step calls the LLM, so check the API key and the "
            "network connection, then try again."
        )
        with st.expander("Technical details"):
            st.code(traceback.format_exc())


def run_analysis(asset_id: str):
    """Run the gap analysis (and the rationale agent). Returns the findings, or None on failure."""
    with llm_guard("Gap analysis"):
        with st.spinner("Running gap analysis..."):
            return bp.analyze(asset_id)
    return None


def task_label(action: str, component: str) -> str:
    return f"{action} {component}".strip()


def asset_picker(key: str, allow_all: bool = False) -> str | None:
    options = (["All assets"] if allow_all else []) + assets
    if not options:
        st.info("Nothing to show yet: no documents have been loaded.")
        st.button("Go to 1 · Load documents →", on_click=go_to, args=("Ingest",), key=f"empty_{key}", type="primary")
        st.stop()
    choice = st.selectbox(
        "Asset", options, key=key,
        help="An asset is one machine (e.g. PANDA-60I). Its OEM manual, vendor contract and checklists share this ID.",
    )
    return None if choice == "All assets" else choice


def go_to(target: str) -> None:
    """Button callback: switch the sidebar page (runs before the rerun, so it may set the widget's state)."""
    st.session_state["nav"] = target


def page_intro(what: str, steps: list[str]) -> None:
    """A short 'what is this page / what do I do here' box at the top of each page."""
    with st.container(border=True):
        st.markdown(f"**What this page is for:** {what}")
        st.markdown("**How to use it:**\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)))


def next_step(target: str, why: str) -> None:
    """A clear pointer to the next page in the workflow."""
    st.divider()
    c1, c2 = st.columns([3, 2])
    c1.markdown(f"**Next:** {why}")
    c2.button(f"Go to {NAV_LABELS[target]} →", on_click=go_to, args=(target,), key=f"next_{target}",
              type="primary", width="stretch")


def sample_badge(is_sample: bool) -> str:
    return "🧪 SAMPLE · " if is_sample else ""


show_notice(expanded=page == "About Us")

# ---------------------------------------------------------------- About Us
if page == "About Us":
    with st.container(border=True):
        st.markdown(
            "**New here? A 2-minute tour**\n"
            "1. **Load documents**: click *Load Panda 60i demo* (or upload your own files).\n"
            "2. **Sign off OEM baseline**: see the task list taken from the manual. The demo is already approved.\n"
            "3. **Log a vendor visit** (optional): try recording a site visit.\n"
            "4. **Review compliance gaps**: click any row to see the OEM and vendor wording side by side.\n"
            "5. **See why vendors do more**: reasons for extra work, with source quotes.\n"
            "6. **Ask a question**: e.g. *Which OEM tasks is the vendor missing?*\n\n"
            "Use the numbered menu on the left to move between steps. Each page also has a **Next** button at the bottom."
        )
        st.button("Start: 1 · Load documents →", on_click=go_to, args=("Ingest",), type="primary", key="start_tour")
    render_about()
    next_step("Ingest", "load the demo or your own documents.")

# ---------------------------------------------------------------- Methodology
elif page == "Methodology":
    st.caption("This page explains how the app works behind the scenes. You don't need it to use the app.")
    render_methodology()
    next_step("About Us", "back to the start.")

# ---------------------------------------------------------------- Ingest
elif page == "Ingest":
    st.header("Step 1 · Load documents")
    if flash := st.session_state.pop("flash", None):
        st.success(flash)
    page_intro(
        "getting documents into the app. OEM manuals and vendor contracts are read by the LLM and turned into "
        "task lists; every document is also indexed so you can search it on the Ask page.",
        [
            "**Quickest:** click **Load Panda 60i demo** below. It loads a ready-made generator example.",
            "**Or** upload your own files under *Option B*: pick the files, say what kind of document they are, "
            "and give the machine an asset ID.",
            "Then go to **2 · Sign off OEM baseline** to check the OEM task list before any comparison runs.",
        ],
    )

    st.subheader("Option A: load the demo (recommended)")
    with st.container(border=True):
        st.write(
            "The **Panda 60i generator** example (`PANDA-60I`): an OEM task list reviewed from the real Panda and "
            "engine manuals (the engine manual is a placeholder), plus a **simulated** vendor contract and "
            "checklists with 10 planted gaps. The vendor side is fictional and tagged SAMPLE. The baseline "
            "is signed off for you."
        )
        st.caption("Takes about a minute: the LLM reads the simulated contract and explains vendor extras. "
                   "Loading it again is safe. The hosted app clears its data when it restarts, so reload before a demo.")
        if st.button("Load Panda 60i demo", type="primary"):
            from blueprint.scenarios import load_scenario

            with llm_guard("Loading the Panda 60i demo"):
                with st.spinner("Reading the simulated vendor contract and running the analysis..."):
                    findings = load_scenario(bp, "panda-60i")
                st.session_state["flash"] = (
                    f"Panda 60i demo loaded: {len(findings)} findings. Next, open **4 · Review compliance gaps** "
                    "(or check the task list on **2 · Sign off OEM baseline** first)."
                )
                st.rerun()

    st.subheader("Option B: upload your own documents")
    with st.form("upload", clear_on_submit=True):
        files = st.file_uploader(
            "Files", type=[s.lstrip(".") for s in SUPPORTED_SUFFIXES], accept_multiple_files=True,
            help="Text-based PDFs work best. Scanned PDFs need OCR first.",
        )
        kind = st.selectbox(
            "Document type", list(SourceKind), format_func=KIND_LABELS.get,
            help="OEM manual: what the manufacturer requires. Vendor contract: what the vendor commits to do. "
                 "Field report: notes and emails that may explain why the vendor does extra work.",
        )
        asset_id = st.text_input(
            "Asset ID / tag", placeholder="e.g. GEN-01",
            help="Use the same ID for every document about the same machine, so they get compared with each other.",
        ).strip()
        vendor = st.text_input(
            "Vendor (required for vendor documents)", placeholder="e.g. Example Marine Services",
            help="Leave empty for OEM manuals.",
        ).strip() or None
        st.caption("Upload the OEM manual and the vendor contract for the same asset ID. Each file takes a minute or so.")
        submitted = st.form_submit_button("Upload and process", type="primary")

    if submitted:
        if not files or not asset_id:
            st.error("Add at least one file and an asset ID.")
        elif kind == SourceKind.VENDOR and not vendor:
            st.error("Vendor documents need a vendor name.")
        else:
            for f in files:
                with st.spinner(f"Processing {f.name}..."), llm_guard(f"Processing {f.name}"):
                    try:
                        _, n_tasks, n_chunks = bp.ingest(
                            f.name, f.getvalue(), kind=kind, asset_id=asset_id, vendor=vendor
                        )
                        st.success(f"{f.name}: {n_tasks} tasks extracted, {n_chunks} chunks indexed")
                    except ValueError as e:
                        st.error(f"{f.name}: {e}")
            findings = run_analysis(asset_id)
            if findings is not None:
                st.info(f"{len(findings)} findings for {asset_id}. Next: check the task list on "
                        "**2 · Sign off OEM baseline**, then open **4 · Review compliance gaps**.")

    with st.expander("More: upload vendor checklists as a CSV"):
        st.caption("For many visits at once. One row per task done at a visit (format is provisional). "
                   "To enter a single visit by hand, use **3 · Log a vendor visit** instead.")
        st.download_button("Download CSV template", CSV_TEMPLATE, file_name="checklist-template.csv")
        csv_file = st.file_uploader("Checklist CSV", type=["csv"], key="tickets_csv")
        csv_vendor = st.text_input("Vendor (if not in the CSV)", key="tickets_vendor").strip() or None
        if csv_file and st.button("Import tickets"):
            try:
                tickets = parse_csv(csv_file.getvalue(), vendor=csv_vendor)
            except ValueError as e:
                st.error(str(e))
            else:
                bp.add_tickets(tickets)
                st.success(f"Imported {len(tickets)} checklist lines.")
                for a in sorted({t.asset_id for t in tickets}):
                    run_analysis(a)

    with st.expander("More: synthetic test data (developers only)"):
        st.write(
            "Loads a fictional generator (`SAMPLE-GEN-01`): an OEM spec, a vendor contract with 10 planted "
            "gaps, and checklist tickets. None of it is real OEM or vendor content, and it is tagged SAMPLE "
            "everywhere. Loading it also simulates the baseline sign-off for the sample."
        )
        if st.button("Load sample data"):
            from blueprint.samples import load_samples

            with llm_guard("Loading sample data"):
                with st.spinner("Loading samples..."):
                    load_samples(bp)
                st.rerun()

    docs = bp.db.documents()
    if docs:
        st.subheader("Documents on file")
        st.caption("Everything loaded so far. 🧪 SAMPLE marks simulated or synthetic data.")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "File": sample_badge(d.is_sample) + d.filename,
                        "Type": KIND_LABELS[d.kind],
                        "Asset": d.asset_id,
                        "Vendor": d.vendor or "",
                        "Baseline": d.baseline_status.value.title() if d.kind == SourceKind.OEM else "",
                    }
                    for d in docs
                ]
            ),
            hide_index=True,
            width="stretch",
        )

# ---------------------------------------------------------------- Baseline sign-off
elif page == "Baseline sign-off":
    st.header("Step 2 · Sign off the OEM baseline")
    page_intro(
        "making sure the task list taken from the OEM manual is right before the vendor is judged against it. "
        "Nothing is compared until a person approves it.",
        [
            "Pick the OEM document below.",
            "Read each row against its **Source quote** (scroll the table right). Click a cell to fix it.",
            "Tick **Safety critical** for tasks that allow no slack (any longer vendor interval becomes critical).",
            "Untick **Needs review** once you've resolved a flagged row. Flagged rows count as failed until then.",
            "Click **Save edits** if you changed anything, then **Approve baseline**.",
        ],
    )
    oem_docs = bp.db.documents(SourceKind.OEM)
    if not oem_docs:
        st.info("No OEM manual loaded yet. Load the Panda 60i demo or upload an OEM manual first.")
        st.button("Go to 1 · Load documents →", on_click=go_to, args=("Ingest",), key="empty_baseline", type="primary")
        st.stop()
    doc = st.selectbox(
        "OEM document", oem_docs,
        help="One task list per OEM manual. The status in brackets shows whether it's approved.",
        format_func=lambda d: f"{sample_badge(d.is_sample)}{d.asset_id} · {d.filename} ({d.baseline_status.value})",
    )
    tasks = bp.db.document_tasks(doc.doc_id)
    if doc.baseline_status == BaselineStatus.APPROVED:
        st.success("Approved. Comparisons use this task list.")
    else:
        st.warning("Draft. No comparison runs for this asset until it is approved.")

    df = pd.DataFrame(
        [
            {
                "component": t.component,
                "action": t.action,
                "intervals": format_intervals(t.intervals),
                "part_ids": ", ".join(t.part_ids),
                "spec": t.spec or "",
                "safety_critical": t.safety_critical,
                "needs_review": t.needs_review,
                "review_note": t.review_note,
                "source_quote": t.source_quote,
                "page": t.page,
            }
            for t in tasks
        ],
        columns=["component", "action", "intervals", "part_ids", "spec", "safety_critical",
                 "needs_review", "review_note", "source_quote", "page"],
    )
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        disabled=["source_quote", "page"],
        column_config={
            "component": st.column_config.TextColumn("Component", width="medium"),
            "action": st.column_config.TextColumn("Action", width="small"),
            "intervals": st.column_config.TextColumn(
                "Interval (whichever first)", help="Whichever comes first, e.g. '250 hours; 6 months'"
            ),
            "part_ids": st.column_config.TextColumn("Part numbers", help="Comma-separated"),
            "spec": st.column_config.TextColumn("Fluid / part spec"),
            "safety_critical": st.column_config.CheckboxColumn(
                "Safety critical", help="Zero tolerance: any longer vendor interval is a critical gap"
            ),
            "needs_review": st.column_config.CheckboxColumn(
                "Needs review", help="Counts as failed in the gap report until unticked"
            ),
            "review_note": st.column_config.TextColumn("Review note", width="medium"),
            "source_quote": st.column_config.TextColumn("Source quote (from manual)", width="large"),
            "page": st.column_config.NumberColumn("Page", width="small"),
        },
        key=f"baseline_{doc.doc_id}",
    )
    col1, col2 = st.columns(2)
    if col1.button("Save edits"):
        try:
            new_tasks = [
                MaintenanceTask(
                    asset_id=doc.asset_id,
                    component=str(r.component).strip(),
                    action=str(r.action).strip(),
                    intervals=parse_intervals(str(r.intervals or "")),
                    part_ids=[p.strip() for p in str(r.part_ids or "").split(",") if p.strip()],
                    spec=(str(r.spec).strip() or None) if pd.notna(r.spec) else None,
                    safety_critical=bool(r.safety_critical),
                    needs_review=bool(r.needs_review),
                    review_note=str(r.review_note or "") if pd.notna(r.review_note) else "",
                    source_quote=str(r.source_quote or "") if pd.notna(r.source_quote) else "",
                    page=int(r.page) if pd.notna(r.page) else None,
                )
                for r in edited.itertuples()
                if pd.notna(r.component) and str(r.component).strip()
            ]
        except ValueError as e:
            st.error(str(e))
        else:
            bp.db.replace_document_tasks(doc.doc_id, new_tasks)
            st.success("Saved. Baseline is back to draft; approve it when ready.")
            st.rerun()
    n_review = sum(t.needs_review for t in tasks)
    if col2.button("Approve baseline", type="primary", disabled=doc.baseline_status == BaselineStatus.APPROVED):
        bp.approve_baseline(doc.doc_id)
        if run_analysis(doc.asset_id) is not None:
            st.rerun()
    if n_review:
        st.caption(f"{n_review} task(s) still need review and will count as failed.")
    st.caption("Hover a column heading for help. Saving edits returns the baseline to draft, so approve it again after.")
    if doc.baseline_status == BaselineStatus.APPROVED:
        next_step("Gap report", "this baseline is approved, so see where the vendor falls short.")
    else:
        st.info("Approve the baseline above to run the comparison.")

# ---------------------------------------------------------------- Checklist entry
elif page == "Checklist entry":
    st.header("Step 3 · Log a vendor visit (optional)")
    page_intro(
        "recording what the vendor actually did on a site visit. This step is optional: the demo already includes "
        "simulated visits. The dates and hour-meter readings are used to spot tasks done late or skipped.",
        [
            "Pick the asset, then fill in the vendor, visit date and the machine's hour-meter reading.",
            "Tick each task done. Optionally add the time spent and a note on *why* or what was found "
            "(notes feed the **Field wisdom** page).",
            "Use **Other task done** for work not on the list, then click **Submit checklist**. The gap analysis re-runs.",
        ],
    )
    asset_id = asset_picker("chk_asset")
    vendors = bp.db.vendors(asset_id)
    schedule = (
        bp.db.tasks(asset_id, SourceKind.VENDOR, vendors[0]) if vendors
        else bp.db.tasks(asset_id, SourceKind.OEM, approved_only=True)
    )
    with st.form("checklist", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        vendor = c1.selectbox("Vendor", vendors) if vendors else c1.text_input("Vendor")
        visit = c2.date_input("Visit date", value=date.today())
        meter = c3.number_input("Hour-meter reading", min_value=0.0, step=1.0, value=None,
                                help="Running hours shown on the machine's meter at this visit.")
        done = []
        h = st.columns([6, 1.3, 4])
        h[0].markdown("**Task done** :gray[(interval)]")
        h[1].markdown("**Time spent (h)**")
        h[2].markdown("**Notes**")
        # Inside a form nothing reruns until submit, so every row shows its inputs up front.
        for i, t in enumerate(schedule):
            cols = st.columns([6, 1.3, 4])
            interval = format_intervals(t.intervals) or "no interval"
            ticked = cols[0].checkbox(
                f"{task_label(t.action, t.component)} :gray[({interval})]", key=f"chk_{i}"
            )
            hrs = cols[1].number_input("time spent (h)", min_value=0.0, step=0.25, key=f"hrs_{i}",
                                       label_visibility="collapsed")
            note = cols[2].text_input("notes", key=f"note_{i}", label_visibility="collapsed",
                                      placeholder="Notes: why, conditions found...")
            if ticked:
                done.append((t, hrs, note))
        st.markdown("**Other task done** :gray[(not on the list above)]")
        o1, o2, o3 = st.columns([2, 1, 4])
        other_comp = o1.text_input("Component")
        other_action = o2.text_input("Action", value="inspect")
        other_note = o3.text_input("Notes", key="other_note")
        if st.form_submit_button("Submit checklist"):
            tickets = [
                Ticket(asset_id=asset_id, vendor=vendor or None, date=visit, component=t.component, action=t.action,
                       meter_hours=meter, time_spent_hours=hrs or None, notes=note)
                for t, hrs, note in done
            ]
            if other_comp.strip():
                tickets.append(Ticket(asset_id=asset_id, vendor=vendor or None, date=visit,
                                      component=other_comp.strip(), action=other_action.strip() or "inspect",
                                      meter_hours=meter, notes=other_note))
            if tickets:
                bp.add_tickets(tickets)
                st.success(f"Recorded {len(tickets)} task(s).")
                run_analysis(asset_id)
            else:
                st.error("Tick at least one task.")

    if not schedule:
        st.caption("No task list for this asset yet: approve the OEM baseline or load a vendor contract first.")
    recent = bp.db.tickets(asset_id)[-30:]
    if recent:
        st.subheader("Recent checklist lines")
        st.dataframe(pd.DataFrame([
            {"Date": t.date, "Task": task_label(t.action, t.component), "Meter h": t.meter_hours,
             "Time h": t.time_spent_hours, "Vendor": t.vendor or "", "Notes": sample_badge(t.is_sample) + t.notes}
            for t in reversed(recent)
        ]), hide_index=True, width="stretch")
    next_step("Gap report", "see how this visit changes the compliance picture.")

# ---------------------------------------------------------------- Gap report
elif page == "Gap report":
    st.header("Step 4 · Compliance gap report")
    page_intro(
        "seeing where the vendor does **less** than the OEM requires: missing tasks, intervals that are too long, "
        "different parts or fluids, and work done late or skipped. These are found by fixed rules, not by the LLM, "
        f"so the same input always gives the same result. Tolerance is {bp.settings.tolerance:.0%} on recurring "
        "tasks and zero for safety-critical ones.",
        [
            "Pick the asset. The four numbers give the totals by severity.",
            "Not sure what a finding type means? Open **What do the finding types mean?**",
            "**Click the box at the start of any row** to see the full finding with the OEM and vendor wording side by side.",
            "Use **Download CSV** to share the report.",
        ],
    )
    asset_id = asset_picker("gap_asset")
    oem_docs = [d for d in bp.db.documents(SourceKind.OEM) if d.asset_id == asset_id]
    if not any(d.baseline_status == BaselineStatus.APPROVED for d in oem_docs):
        st.warning("No approved OEM baseline for this asset, so no comparison has run yet.")
        st.button("Go to 2 · Sign off OEM baseline →", on_click=go_to, args=("Baseline sign-off",),
                  key="gap_to_baseline")
    rate = bp.usage_rate(asset_id)
    if rate is not None:
        st.caption(f"Usage rate from vendor checklists: {rate:.0f} running hours / month")
    if st.button("Re-run analysis", help="Only needed after you change documents outside this app; it re-runs "
                 "automatically after uploads, sign-off and checklist entries."):
        run_analysis(asset_id)

    findings = sorted(
        bp.db.findings(asset_id),
        key=lambda f: (SEVERITY_ORDER[f.severity], list(FindingType).index(f.type)),
    )
    if not findings:
        st.info("No findings yet. This asset needs an approved OEM baseline **and** a vendor contract or checklists.")
        st.button("Go to 1 · Load documents →", on_click=go_to, args=("Ingest",), key="gap_empty", type="primary")
        st.stop()

    failed = sum(f.type == FindingType.NEEDS_REVIEW for f in findings)
    cols = st.columns(4)
    for col, sev in zip(cols, Severity):
        col.metric(f"{SEVERITY_ICON[sev]} {sev.value.title()}", sum(f.severity == sev for f in findings))
    cols[3].metric("Needs review (failed)", failed)

    with st.expander("What do the finding types mean?"):
        present = {f.type for f in findings}
        st.markdown("\n".join(
            f"- **{TYPE_LABELS[t]}**: {TYPE_HELP[t]}" for t in FindingType if t in present
        ))

    show = st.multiselect("Severity", list(Severity), default=[Severity.CRITICAL, Severity.WARNING],
                          format_func=lambda s: s.value.title(),
                          help="Critical: a clear compliance gap. Warning: worth a check. "
                               "Info: the vendor does more than the OEM (explained on step 5).")
    if Severity.INFO not in show and any(f.severity == Severity.INFO for f in findings):
        st.caption("Info findings (vendor does more than OEM) are hidden; add Info above, or see **Field wisdom**.")
    shown = [f for f in findings if f.severity in show]

    def quote(t: MaintenanceTask | None) -> str:
        return t.source_quote if t else ""

    df = pd.DataFrame(
        [
            {
                "Severity": f"{SEVERITY_ICON[f.severity]} {f.severity.value.title()}",
                "Type": TYPE_LABELS[f.type],
                "Finding": f.message,
                "Match": (f"{f.match_basis.value.replace('_', ' ')} ({f.match_confidence:.0%})"
                          if f.match_basis else ""),
                "Vendor": f.vendor or "",
                "OEM source": quote(f.oem_task),
                "Vendor source": quote(f.vendor_task),
            }
            for f in shown
        ],
        columns=["Severity", "Type", "Finding", "Match", "Vendor", "OEM source", "Vendor source"],
    )
    event = st.dataframe(
        df[["Severity", "Type", "Finding", "Match"]],
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"gap_table_{asset_id}",
        column_config={
            "Severity": st.column_config.TextColumn(width="small"),
            "Type": st.column_config.TextColumn(width="medium"),
            "Finding": st.column_config.TextColumn(width="large"),
            "Match": st.column_config.TextColumn(
                width="small", help="How the OEM task was paired with the vendor's; low confidence deserves a check"
            ),
        },
    )
    selected = event.selection.rows if event and event.selection else []
    if not selected:
        st.caption("👆 Tick the box at the start of a row to see the full finding with the OEM and vendor source quotes side by side.")
    else:
        f = shown[selected[0]]
        with st.container(border=True):
            st.markdown(f"{SEVERITY_ICON[f.severity]} **{TYPE_LABELS[f.type]}**")
            st.write(f.message)
            st.caption(TYPE_HELP[f.type])
            left, right = st.columns(2)
            for col, title, t in ((left, "OEM requirement", f.oem_task), (right, f"Vendor ({f.vendor or 'n/a'})", f.vendor_task)):
                col.markdown(f"**{title}**")
                if t is None:
                    col.caption("No matching task.")
                    continue
                col.write(f"{task_label(t.action, t.component)}, every {format_intervals(t.intervals) or 'no interval'}")
                if t.spec or t.part_ids:
                    col.caption(" · ".join(x for x in [t.spec or "", ", ".join(t.part_ids)] if x))
                if t.source_quote:
                    col.markdown(f"> {t.source_quote}")
                if t.page:
                    col.caption(f"Page {t.page}")
            if f.match_basis:
                st.caption(f"Matched by {f.match_basis.value.replace('_', ' ')}, confidence {f.match_confidence:.0%}.")
    st.download_button("Download CSV", df.to_csv(index=False), file_name=f"gap-report-{asset_id}.csv",
                       help="All findings shown above, including the OEM and vendor source quotes.")
    next_step("Field wisdom", "the other direction: where the vendor does more than the OEM, and why.")

# ---------------------------------------------------------------- Field wisdom
elif page == "Field wisdom":
    st.header("Step 5 · Field wisdom: why vendors do more")
    page_intro(
        "keeping the reasons behind extra vendor work (more often than the OEM asks, or tasks the OEM doesn't "
        "require), so the next team knows why. The LLM reads ticket notes and field reports and proposes a reason.",
        [
            "Each card is one extra task, with its status: ✅ justified, ⛔ unjustified or ❔ unknown.",
            "A reason counts as confirmed only when its quote is found word for word in the source, shown as a "
            "grey quote block. Otherwise it's marked **Unconfirmed**.",
            "To add evidence, upload a field report on step 1 or add notes on step 3.",
        ],
    )
    asset_id = asset_picker("wisdom_asset", allow_all=True)
    rationales = bp.db.rationales(asset_id)
    if not rationales:
        st.info("No extra vendor work found yet. Cards appear here once the gap analysis finds the vendor doing "
                "more than the OEM (Info findings on step 4).")

    # Show the vendor's own wording for each task rather than the internal matching key.
    names: dict[tuple[str, str], tuple[str, str]] = {}
    for a in {r.asset_id for r in rationales}:
        for f in bp.db.findings(a):
            t = f.vendor_task or f.oem_task
            if t:
                names.setdefault((a, f.task_key), (task_label(t.action, t.component),
                                                   format_intervals(t.intervals)))

    def fallback_label(key: str) -> str:
        component, _, action = key.partition("|")
        return task_label(action, component)

    for r in rationales:
        label, interval = names.get((r.asset_id, r.task_key), (fallback_label(r.task_key), ""))
        with st.container(border=True):
            st.markdown(
                f"**{label[:1].upper() + label[1:]}**" + (f" :gray[every {interval}]" if interval else "")
                + f" · {STATUS_ICON[r.status]} {r.status.value.title()}"
            )
            st.caption(f"{r.asset_id} · {r.vendor or 'vendor not recorded'}")
            if r.confirmed:
                st.write(r.rationale)
            else:
                st.warning(f"Unconfirmed: {r.rationale}")
            if r.conditions:
                st.write("Conditions: " + ", ".join(r.conditions))
            for q in r.evidence:
                st.markdown(f"> {q}")
            st.caption(f"Confidence {r.confidence:.0%}")
    next_step("Ask", "ask questions across all the documents, gaps and reasons.")

# ---------------------------------------------------------------- Ask
elif page == "Ask":
    st.header("Step 6 · Ask about assets, gaps and decisions")
    page_intro(
        "asking plain-English questions about the manuals, the vendor contract, checklists, gaps and reasons. "
        "Answers only use what's been loaded, and cite numbered sources you can open to check.",
        [
            "Optionally narrow the search to one asset.",
            "Type a question in the box at the bottom of the page and press Enter.",
            "Open **Sources** under an answer to see where it came from.",
        ],
    )
    st.caption("Try: *Which OEM tasks is the vendor missing?* · *How often must the exhaust pipes be inspected?* · "
               "*Why does the vendor descale the exhaust mixing elbow?*")
    asset_id = asset_picker("ask_asset", allow_all=True)
    history = st.session_state.setdefault("chat", [])
    for msg in history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if question := st.chat_input("e.g. Why does the vendor clean the radiator fins every 3 months?"):
        history.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            answer = None
            with llm_guard("Answering"), st.spinner("Searching..."):
                answer = bp.ask(question, asset_id)
            if answer is not None:
                st.markdown(answer.text)
                if answer.sources:
                    with st.expander("Sources"):
                        for i, h in enumerate(answer.sources, 1):
                            st.markdown(f"**[{i}] {source_label(h)}** (similarity {h.score:.2f})")
                            st.caption(h.text[:500])
        if answer is not None:
            history.append({"role": "assistant", "content": answer.text})
        else:
            history.pop()  # don't keep a question that got no answer
