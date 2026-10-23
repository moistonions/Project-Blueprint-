"""Streamlit UI for Project Blueprint.

Run with:  streamlit run app.py
"""

from __future__ import annotations

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

st.set_page_config(page_title="Project Blueprint", page_icon="🛠️", layout="wide")

KIND_LABELS = {
    SourceKind.OEM: "OEM manual / spec",
    SourceKind.VENDOR: "Vendor contract / schedule",
    SourceKind.FIELD: "Field report / email",
}
SEVERITY_ICON = {Severity.CRITICAL: "🔴", Severity.WARNING: "🟠", Severity.INFO: "🔵"}
STATUS_ICON = {ExtraWorkStatus.JUSTIFIED: "✅", ExtraWorkStatus.UNJUSTIFIED: "⛔", ExtraWorkStatus.UNKNOWN: "❔"}
PAGES = ["Ingest", "Baseline sign-off", "Checklist entry", "Gap report", "Field wisdom", "Ask"]


@st.cache_resource
def get_blueprint() -> Blueprint:
    return Blueprint.from_settings(get_settings())


try:
    bp = get_blueprint()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

st.sidebar.title("Project Blueprint")
st.sidebar.caption("OEM vs vendor maintenance compliance and field knowledge")
page = st.sidebar.radio("View", PAGES)
assets = bp.db.assets()


def asset_picker(key: str, allow_all: bool = False) -> str | None:
    options = (["All assets"] if allow_all else []) + assets
    if not options:
        st.info("No documents yet. Start on the Ingest page.")
        st.stop()
    choice = st.selectbox("Asset", options, key=key)
    return None if choice == "All assets" else choice


def sample_badge(is_sample: bool) -> str:
    return "🧪 SAMPLE · " if is_sample else ""


# ---------------------------------------------------------------- Ingest
if page == "Ingest":
    st.header("Ingest documents")
    st.write(
        "Upload OEM manuals, vendor contracts and field documents. OEM and vendor documents are "
        "parsed into structured tasks; every document is indexed for search. OEM task lists must be "
        "signed off on the **Baseline sign-off** page before any comparison runs."
    )
    with st.form("upload", clear_on_submit=True):
        files = st.file_uploader(
            "Files", type=[s.lstrip(".") for s in SUPPORTED_SUFFIXES], accept_multiple_files=True
        )
        kind = st.selectbox("Document type", list(SourceKind), format_func=KIND_LABELS.get)
        asset_id = st.text_input("Asset ID / tag", placeholder="e.g. GEN-01").strip()
        vendor = st.text_input("Vendor (required for vendor documents)").strip() or None
        submitted = st.form_submit_button("Ingest")

    if submitted:
        if not files or not asset_id:
            st.error("Add at least one file and an asset ID.")
        elif kind == SourceKind.VENDOR and not vendor:
            st.error("Vendor documents need a vendor name.")
        else:
            for f in files:
                with st.spinner(f"Processing {f.name}..."):
                    try:
                        _, n_tasks, n_chunks = bp.ingest(
                            f.name, f.getvalue(), kind=kind, asset_id=asset_id, vendor=vendor
                        )
                        st.success(f"{f.name}: {n_tasks} tasks extracted, {n_chunks} chunks indexed")
                    except ValueError as e:
                        st.error(f"{f.name}: {e}")
            with st.spinner("Running gap analysis..."):
                findings = bp.analyze(asset_id)
            st.info(f"{len(findings)} findings for {asset_id}. See the Gap report.")

    with st.expander("Upload vendor checklist tickets (CSV)"):
        st.caption("Provisional format, one row per task done at a visit. Or use the Checklist entry page.")
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
                for a in sorted({t.asset_id for t in tickets}):
                    bp.analyze(a)
                st.success(f"Imported {len(tickets)} checklist lines.")

    with st.expander("Synthetic sample data (for testing the pipeline only)"):
        st.write(
            "Loads a fictional generator (`SAMPLE-GEN-01`): an OEM spec, a vendor contract with 10 planted "
            "gaps, and checklist tickets. None of it is real OEM or vendor content, and it is tagged SAMPLE "
            "everywhere. Loading it also simulates the baseline sign-off for the sample."
        )
        if st.button("Load sample data"):
            from blueprint.samples import load_samples

            with st.spinner("Loading samples..."):
                load_samples(bp)
            st.rerun()

    docs = bp.db.documents()
    if docs:
        st.subheader("Documents on file")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "File": sample_badge(d.is_sample) + d.filename,
                        "Type": KIND_LABELS[d.kind],
                        "Asset": d.asset_id,
                        "Vendor": d.vendor or "",
                        "Baseline": d.baseline_status.value if d.kind == SourceKind.OEM else "",
                    }
                    for d in docs
                ]
            ),
            hide_index=True,
            width="stretch",
        )

# ---------------------------------------------------------------- Baseline sign-off
elif page == "Baseline sign-off":
    st.header("OEM baseline sign-off")
    st.write(
        "Check the tasks extracted from each OEM manual against the source, fix anything wrong, mark "
        "safety-critical tasks (zero tolerance), then approve. Tasks marked **needs review** count as "
        "failed in the gap report until you resolve them. Saving any edit returns the baseline to draft."
    )
    oem_docs = bp.db.documents(SourceKind.OEM)
    if not oem_docs:
        st.info("No OEM documents yet. Upload one on the Ingest page.")
        st.stop()
    doc = st.selectbox(
        "OEM document", oem_docs,
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
            "intervals": st.column_config.TextColumn(help="Whichever comes first, e.g. '250 hours; 6 months'"),
            "safety_critical": st.column_config.CheckboxColumn("safety critical"),
            "needs_review": st.column_config.CheckboxColumn("needs review"),
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
        with st.spinner("Running gap analysis..."):
            bp.analyze(doc.asset_id)
        st.rerun()
    if n_review:
        st.caption(f"{n_review} task(s) still need review and will count as failed.")

# ---------------------------------------------------------------- Checklist entry
elif page == "Checklist entry":
    st.header("Vendor checklist entry")
    st.caption("Provisional form. One submission = one site visit; tick each task done.")
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
        meter = c3.number_input("Hour-meter reading", min_value=0.0, step=1.0, value=None)
        done = []
        # Inside a form nothing reruns until submit, so every row shows its inputs up front.
        for i, t in enumerate(schedule):
            cols = st.columns([4, 1, 4])
            ticked = cols[0].checkbox(
                f"{t.action} {t.component} ({format_intervals(t.intervals) or 'no interval'})", key=f"chk_{i}"
            )
            hrs = cols[1].number_input("time spent (h)", min_value=0.0, step=0.25, key=f"hrs_{i}",
                                       label_visibility="collapsed")
            note = cols[2].text_input("notes", key=f"note_{i}", label_visibility="collapsed",
                                      placeholder="Notes: why, conditions found...")
            if ticked:
                done.append((t, hrs, note))
        st.markdown("**Other task done**")
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
                bp.analyze(asset_id)
                st.success(f"Recorded {len(tickets)} task(s).")
            else:
                st.error("Tick at least one task.")

    recent = bp.db.tickets(asset_id)[-30:]
    if recent:
        st.subheader("Recent checklist lines")
        st.dataframe(pd.DataFrame([
            {"Date": t.date, "Task": f"{t.action} {t.component}", "Meter h": t.meter_hours,
             "Time h": t.time_spent_hours, "Vendor": t.vendor or "", "Notes": sample_badge(t.is_sample) + t.notes}
            for t in reversed(recent)
        ]), hide_index=True, width="stretch")

# ---------------------------------------------------------------- Gap report
elif page == "Gap report":
    st.header("Compliance gap report")
    st.caption(
        f"Produced by the deterministic rules engine against the approved OEM baseline. Tolerance "
        f"{bp.settings.tolerance:.0%} on recurring tasks, zero for safety-critical tasks."
    )
    asset_id = asset_picker("gap_asset")
    oem_docs = [d for d in bp.db.documents(SourceKind.OEM) if d.asset_id == asset_id]
    if not any(d.baseline_status == BaselineStatus.APPROVED for d in oem_docs):
        st.warning("No approved OEM baseline for this asset, so no comparison has run. "
                   "Approve it on the Baseline sign-off page.")
    rate = bp.usage_rate(asset_id)
    if rate is not None:
        st.caption(f"Usage rate from vendor checklists: {rate:.0f} running hours / month")
    if st.button("Re-run analysis"):
        with st.spinner("Analyzing..."):
            bp.analyze(asset_id)

    findings = bp.db.findings(asset_id)
    if not findings:
        st.info("No findings. The asset needs an approved OEM baseline and a vendor schedule or tickets.")
        st.stop()

    failed = sum(f.type == FindingType.NEEDS_REVIEW for f in findings)
    cols = st.columns(4)
    for col, sev in zip(cols, Severity):
        col.metric(f"{SEVERITY_ICON[sev]} {sev.value.title()}", sum(f.severity == sev for f in findings))
    cols[3].metric("Needs review (failed)", failed)

    show = st.multiselect("Severity", list(Severity), default=[Severity.CRITICAL, Severity.WARNING],
                          format_func=lambda s: s.value.title())
    rows = [
        {
            "Severity": f"{SEVERITY_ICON[f.severity]} {f.severity.value}",
            "Type": f.type.value.replace("_", " "),
            "Finding": f.message,
            "Match": (f"{f.match_basis.value} ({f.match_confidence:.0%})" if f.match_basis else ""),
            "Vendor": f.vendor or "",
            "OEM source": (f.oem_task.source_quote if f.oem_task else ""),
            "Vendor source": (f.vendor_task.source_quote if f.vendor_task else ""),
        }
        for f in findings
        if f.severity in show
    ]
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, width="stretch")
    st.caption("Match shows how an OEM task was paired with the vendor's; lower confidence deserves a manual check.")
    st.download_button("Download CSV", df.to_csv(index=False), file_name=f"gap-report-{asset_id}.csv")

# ---------------------------------------------------------------- Field wisdom
elif page == "Field wisdom":
    st.header("Field wisdom: why vendors do more than OEM")
    st.caption(
        "Captured by the rationale agent from ticket notes and field documents. A reason without a "
        "verified source quote is shown as unconfirmed. Status is shown only; there is no approval flow yet."
    )
    asset_id = asset_picker("wisdom_asset", allow_all=True)
    rationales = bp.db.rationales(asset_id)
    if not rationales:
        st.info("No vendor additions or tightened intervals recorded yet.")
    for r in rationales:
        with st.container(border=True):
            st.markdown(
                f"**{r.asset_id} · {r.vendor or 'n/a'}** · `{r.task_key}` · "
                f"{STATUS_ICON[r.status]} {r.status.value}"
            )
            if r.confirmed:
                st.write(r.rationale)
            else:
                st.warning(f"Unconfirmed: {r.rationale}")
            if r.conditions:
                st.write("Conditions: " + ", ".join(r.conditions))
            for quote in r.evidence:
                st.markdown(f"> {quote}")
            st.caption(f"Confidence {r.confidence:.0%}")

# ---------------------------------------------------------------- Ask
elif page == "Ask":
    st.header("Ask about assets, gaps and decisions")
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
            with st.spinner("Searching..."):
                answer = bp.ask(question, asset_id)
            st.markdown(answer.text)
            if answer.sources:
                with st.expander("Sources"):
                    for i, h in enumerate(answer.sources, 1):
                        st.markdown(f"**[{i}] {source_label(h)}** (similarity {h.score:.2f})")
                        st.caption(h.text[:500])
        history.append({"role": "assistant", "content": answer.text})
