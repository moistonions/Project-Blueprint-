"""Smoke-test every Streamlit page with the fake LLM from test_pipeline."""

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from blueprint.pipeline import Blueprint
from blueprint.samples import SAMPLE_ASSET, load_samples
from tests.test_pipeline import bp  # noqa: F401  (fixture)

PAGES = ["Ingest", "Baseline sign-off", "Checklist entry", "Gap report", "Field wisdom", "Ask"]


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
