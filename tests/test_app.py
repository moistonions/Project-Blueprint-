"""Smoke-test every Streamlit page with the fake LLM from test_pipeline."""

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from blueprint.pipeline import Blueprint
from blueprint.samples import SAMPLE_ASSET, load_samples
from tests.test_pipeline import bp  # noqa: F401  (fixture)

PAGES = ["About Us", "Ingest", "Baseline sign-off", "Checklist entry", "Gap report", "Field wisdom", "Ask", "Methodology"]


@pytest.fixture
def app(bp, monkeypatch):  # noqa: F811
    load_samples(bp)
    monkeypatch.setattr(Blueprint, "from_settings", classmethod(lambda cls, s: bp))
    st.cache_resource.clear()  # app.py caches the Blueprint across runs
    at = AppTest.from_file("../app.py", default_timeout=30)
    at.run()
    at.bp = bp
    return at


@pytest.mark.parametrize("page", PAGES)
def test_pages_render(app, page):
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception


def test_gap_report_counts(app):
    app.sidebar.radio[0].set_value("Gap report").run()
    # 2 missing tasks + 3 beyond tolerance + 2 execution gaps
    assert app.metric[0].value == "7"
    assert app.metric[1].value == "3"  # 1 longer interval + 2 spec mismatches


def test_checklist_submission_records_tickets(app):
    before = len(app.bp.db.tickets(SAMPLE_ASSET))
    app.sidebar.radio[0].set_value("Checklist entry").run()
    app.checkbox(key="chk_0").check()
    app.text_input(key="note_0").input("dusty again")
    next(b for b in app.button if b.label == "Submit checklist").click().run()
    assert not app.exception
    assert len(app.bp.db.tickets(SAMPLE_ASSET)) == before + 1
    assert app.bp.db.tickets(SAMPLE_ASSET)[-1].notes == "dusty again"


def test_chat_answers_with_sources(app):
    app.sidebar.radio[0].set_value("Ask").run()
    app.chat_input[0].set_value("why clean radiator fins?").run()
    assert not app.exception
    assert any("answer [1]" in m.value for m in app.markdown)


def test_gap_report_lists_critical_first_and_explains_types(app):
    app.sidebar.radio[0].set_value("Gap report").run()
    assert not app.exception
    severities = list(app.dataframe[0].value["Severity"])
    assert severities == sorted(severities, key=lambda s: ("Critical" not in s, "Warning" not in s))
    assert any(e.label == "What do the finding types mean?" for e in app.expander)


def test_llm_failure_shows_message_not_traceback(app, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(app.bp, "ask", boom)
    app.sidebar.radio[0].set_value("Ask").run()
    app.chat_input[0].set_value("anything?").run()
    assert not app.exception
    assert any("network down" in e.value for e in app.error)


def test_panda_demo_button_loads_scenario(app, monkeypatch):
    from tests.test_scenario_panda import ContractLLM

    monkeypatch.setattr(app.bp, "llm", ContractLLM())
    app.sidebar.radio[0].set_value("Ingest").run()
    next(b for b in app.button if b.label == "Load Panda 60i demo").click().run()
    assert not app.exception
    assert "PANDA-60I" in app.bp.db.assets()
    assert len(app.bp.db.findings("PANDA-60I")) == 12


def test_notice_on_main_page(app):
    assert "IMPORTANT NOTICE" in app.expander[0].label
    assert any("proof-of-concept prototype" in m.value for m in app.markdown)


def test_password_gate(bp, monkeypatch):  # noqa: F811
    monkeypatch.setenv("BLUEPRINT_APP_PASSWORD", "s3cret")
    monkeypatch.setattr(Blueprint, "from_settings", classmethod(lambda cls, s: bp))
    at = AppTest.from_file("../app.py", default_timeout=30).run()
    assert not at.sidebar.radio  # nothing but the password box
    at.text_input[0].input("wrong").run()
    assert at.error
    at.text_input[0].input("s3cret").run()
    assert at.sidebar.radio[0].value == "About Us"
