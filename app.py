"""Streamlit UI for Project Blueprint.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from blueprint.config import get_settings
from blueprint.ingest import SUPPORTED_SUFFIXES
from blueprint.models import Severity, SourceKind
from blueprint.pipeline import Blueprint
from blueprint.rag import source_label

st.set_page_config(page_title="Project Blueprint", page_icon="🛠️", layout="wide")

KIND_LABELS = {
    SourceKind.OEM: "OEM manual / spec",
    SourceKind.VENDOR: "Vendor contract / schedule",
    SourceKind.FIELD: "Field log / work order / email",
}
SEVERITY_ICON = {Severity.CRITICAL: "🔴", Severity.WARNING: "🟠", Severity.INFO: "🔵"}


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
page = st.sidebar.radio("View", ["Ingest", "Gap report", "Field wisdom", "Ask"])
assets = bp.db.assets()


def asset_picker(key: str, allow_all: bool = False) -> str | None:
    options = (["All assets"] if allow_all else []) + assets
    if not options:
        st.info("No documents yet. Start on the Ingest page.")
        st.stop()
    choice = st.selectbox("Asset", options, key=key)
    return None if choice == "All assets" else choice


# ---------------------------------------------------------------- Ingest
if page == "Ingest":
    st.header("Ingest documents")
    st.write(
        "Upload OEM manuals, vendor schedules and field documents. OEM and vendor documents are "
        "parsed into structured tasks; every document is indexed for search. The gap check reruns "
        "for the asset after each upload."
    )
    with st.form("upload", clear_on_submit=True):
        files = st.file_uploader(
            "Files", type=[s.lstrip(".") for s in SUPPORTED_SUFFIXES], accept_multiple_files=True
        )
        kind = st.selectbox("Document type", list(SourceKind), format_func=KIND_LABELS.get)
        asset_id = st.text_input("Asset ID / tag", placeholder="e.g. PUMP-P101").strip()
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

    with st.expander("Synthetic sample data (for testing the pipeline only)"):
        st.write(
            "Loads three fictional documents for asset `SAMPLE-PUMP-01`. They are not real OEM or "
            "vendor content and are tagged SAMPLE everywhere they appear."
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
                        "File": ("🧪 SAMPLE · " if d.is_sample else "") + d.filename,
                        "Type": KIND_LABELS[d.kind],
                        "Asset": d.asset_id,
                        "Vendor": d.vendor or "",
                    }
                    for d in docs
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

# ---------------------------------------------------------------- Gap report
elif page == "Gap report":
    st.header("Compliance gap report")
    st.caption(
        "Produced by the deterministic rules engine: same inputs, same findings. "
        "Critical = OEM task missing or interval extended beyond OEM."
    )
    asset_id = asset_picker("gap_asset")
    if st.button("Re-run analysis"):
        with st.spinner("Analyzing..."):
            bp.analyze(asset_id)

    findings = bp.db.findings(asset_id)
    if not findings:
        st.info("No findings yet. The asset needs both an OEM document and a vendor schedule.")
        st.stop()

    cols = st.columns(3)
    for col, sev in zip(cols, Severity):
        col.metric(f"{SEVERITY_ICON[sev]} {sev.value.title()}", sum(f.severity == sev for f in findings))

    show = st.multiselect("Severity", list(Severity), default=[Severity.CRITICAL, Severity.WARNING],
                          format_func=lambda s: s.value.title())
    rows = [
        {
            "Severity": f"{SEVERITY_ICON[f.severity]} {f.severity.value}",
            "Vendor": f.vendor or "",
            "Type": f.type.value.replace("_", " "),
            "Finding": f.message,
            "OEM source": (f.oem_task.source_quote if f.oem_task else ""),
            "Vendor source": (f.vendor_task.source_quote if f.vendor_task else ""),
        }
        for f in findings
        if f.severity in show
    ]
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, use_container_width=True)
    st.download_button("Download CSV", df.to_csv(index=False), file_name=f"gap-report-{asset_id}.csv")

# ---------------------------------------------------------------- Field wisdom
elif page == "Field wisdom":
    st.header("Field wisdom: why vendors do more than OEM")
    st.caption(
        "Captured by the rationale agent from field logs and vendor documents. "
        "UNDOCUMENTED means no evidence was found, so the reason should be collected from the vendor."
    )
    asset_id = asset_picker("wisdom_asset", allow_all=True)
    rationales = bp.db.rationales(asset_id)
    if not rationales:
        st.info("No vendor additions or tightened intervals recorded yet.")
    for r in rationales:
        undocumented = r.rationale.startswith("UNDOCUMENTED")
        with st.container(border=True):
            st.markdown(f"**{r.asset_id} · {r.vendor or 'n/a'}** · `{r.task_key}`")
            (st.warning if undocumented else st.write)(r.rationale)
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

    if question := st.chat_input("e.g. Why does the vendor grease the bearings more often than OEM?"):
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
