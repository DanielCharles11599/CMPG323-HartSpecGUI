# test_batch_source_handoff.py — FR-21: Page 01 optional batch route does not regress FR-01.
"""Run the existing real Page 01 control flow with the project's headless Streamlit facade."""

from __future__ import annotations

import sys
import types

from test_source_selection_safety import app, browser, seed_old, set_source


# Imported pytest fixtures are referenced directly to preserve their identities.
_APP_FIXTURE = app
_BROWSER_FIXTURE = browser


def _fake_panel(app, monkeypatch):
    """Only replace the Streamlit widget surface, not the actual source-selection logic."""
    panel = types.ModuleType("utils.batch_ui")
    calls = []
    panel.render_batch_panel = lambda selection, **kwargs: calls.append((selection, kwargs))
    monkeypatch.setitem(sys.modules, "utils.batch_ui", panel)
    monkeypatch.setattr(sys.modules["utils"], "batch_ui", panel, raising=False)
    ingest = sys.modules["utils.fits_ingest"]
    monkeypatch.setattr(ingest, "verify_fits_file", lambda path: types.SimpleNamespace(ok=True, issues=[]),
                        raising=False)
    return calls


def test_batch_button_sorts_and_commits_new_source_without_navigating(app, browser, monkeypatch):
    calls = _fake_panel(app, monkeypatch)
    seed_old(app)
    set_source(app, "B")
    browser.run({"fr21_prepare_batch_btn"})
    assert app.st.navigation is None
    assert app.state["session_id"] != "old-a"
    assert len(browser.calls) == 1
    source = app.state["pipeline_data"]["01_source_browser"]
    assert source["selected_files"] == ["b1.fits", "b2.fits"]
    assert source["observation_blocks"] == {"block.txt": ["b1.fits", "b2.fits"]}
    assert app.state["fr21_batch_editor_open"] is True
    assert calls and calls[0][0] is source


def test_same_selection_reopens_queue_without_rerunning_file_check(app, browser, monkeypatch):
    _fake_panel(app, monkeypatch)
    set_source(app, "B")
    browser.run({"fr21_prepare_batch_btn"})
    assert len(browser.calls) == 1
    before_id = app.state["session_id"]
    browser.run({"fr21_prepare_batch_btn"})
    assert len(browser.calls) == 1
    assert app.state["session_id"] == before_id
    assert app.st.navigation is None


def test_batch_sort_failure_does_not_clear_current_reduction(app, browser, monkeypatch):
    _fake_panel(app, monkeypatch)
    seed_old(app)
    set_source(app, "B")
    original_session = app.state["session_id"]
    original_data = app.state["pipeline_data"]
    browser.controls["raise"] = True
    browser.run({"fr21_prepare_batch_btn"})
    assert app.state["session_id"] == original_session
    assert app.state["pipeline_data"] is original_data
    assert app.st.navigation is None
    assert not app.state.get("fr21_batch_editor_open", False)
    assert any("Cannot prepare the batch" in message for message in app.st.messages)


def test_normal_load_button_keeps_original_navigation_and_does_not_open_batch(app, browser, monkeypatch):
    _fake_panel(app, monkeypatch)
    set_source(app, "B")
    browser.run({"load_into_pipeline_btn"})
    assert app.st.navigation == "pages/02_File_Loader.py"
    assert not app.state.get("fr21_batch_editor_open", False)
