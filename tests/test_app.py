"""Run the real app headless through every tab and widget. Unit tests
cannot catch a tab that only throws when it renders."""

import os

import pytest
from streamlit.testing.v1 import AppTest

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("LAB_OFFLINE", "1")
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception
    return at


def _captions(at):
    return " ".join(c.value for c in at.caption)


def _text(at):
    return " ".join(m.value for m in at.markdown)


def test_every_tab_renders(app):
    labels = [m.label for m in app.metric]
    for want in ("Controls passed", "Open concerns", "On loan"):
        assert want in labels
    # notes are captions, no metric carries a delta arrow
    assert all(not m.delta for m in app.metric)
    text = _captions(app)
    assert "20/20 data controls passed" in text
    assert "data concerns" in _text(app)


def test_concern_picker(app):
    app.selectbox[0].set_value("DC-003").run()
    assert not app.exception
    body = _text(app)
    assert "price_feed_not_frozen" in body
    assert "Birch" in body
    app.selectbox[0].set_value("DC-002").run()
    assert not app.exception
    assert "limit breach hidden" in _text(app)
