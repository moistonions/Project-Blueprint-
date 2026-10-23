"""Smoke-test every Streamlit page with the fake LLM from test_pipeline."""

import pytest
from streamlit.testing.v1 import AppTest

from blueprint.pipeline import Blueprint
from blueprint.samples import load_samples
from tests.test_pipeline import bp  # noqa: F401  (fixture)


@pytest.fixture
def app(bp, monkeypatch):  # noqa: F811
    load_samples(bp)
    monkeypatch.setattr(Blueprint, "from_settings", classmethod(lambda cls, s: bp))
    at = AppTest.from_file("../app.py", default_timeout=30)
    at.run()
    return at


@pytest.mark.parametrize("page", ["Ingest", "Gap report", "Field wisdom", "Ask"])
def test_pages_render(app, page):
    app.sidebar.radio[0].set_value(page).run()
    assert not app.exception


def test_gap_report_shows_critical_findings(app):
    app.sidebar.radio[0].set_value("Gap report").run()
    assert app.metric[0].value == "2"  # missing coupling check + extended seal interval


def test_chat_answers_with_sources(app):
    app.sidebar.radio[0].set_value("Ask").run()
    app.chat_input[0].set_value("why grease bearings more often?").run()
    assert not app.exception
    assert any("answer [1]" in m.value for m in app.markdown)
