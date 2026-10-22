# test_batch_ui.py — FR-21: test the real queue panel with a lightweight Streamlit facade.
"""This is a UI control-flow test, not a browser screenshot or numerical CLC regression."""

from __future__ import annotations

import importlib.util
import sys
import types
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from utils import batch_queue


class FakeStreamlit(types.ModuleType):
    def __init__(self, state):
        super().__init__("streamlit")
        self.session_state = state
        self.clicked = set()
        self.messages = []
        self.tables = []
        self.progress_fractions = []

    def container(self, **kwargs):
        return nullcontext()

    def expander(self, *args, **kwargs):
        return nullcontext()

    def spinner(self, *args, **kwargs):
        return nullcontext()

    def selectbox(self, label, options, **kwargs):
        return options[0]

    def multiselect(self, label, *, options, default, key):
        return self.session_state.get(key, default)

    def button(self, label, *, key, disabled=False):
        return key in self.clicked and not disabled

    def dataframe(self, data, **kwargs):
        self.tables.append(data)

    def progress(self, progress):
        self.progress_fractions.append(progress)

    def markdown(self, message, **kwargs):
        self.messages.append(str(message))

    caption = warning = success = info = error = markdown


def _app(monkeypatch, selection):
    """Load actual UI code while replacing only Streamlit and session persistence calls."""
    fake_st = FakeStreamlit({
        "fr21_batch_editor_open": True,
        "session_id": "s0102030",
        "pipeline_data": {"01_source_browser": selection},
    })
    session = types.ModuleType("utils.session_store")
    events = []
    session.log_event = events.append
    session.checkpoint_session = lambda reason: events.append(f"checkpoint: {reason}")
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setitem(sys.modules, "utils.session_store", session)
    monkeypatch.setattr(sys.modules["utils"], "session_store", session, raising=False)
    path = Path(batch_queue.__file__).with_name("batch_ui.py")
    spec = importlib.util.spec_from_file_location("utils._batch_ui_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return fake_st, module, events


def _selection(tmp_path):
    archive = tmp_path / "fits"
    archive.mkdir()
    for name in ("00000001_ON.fits", "00000001_OFF.fits"):
        (archive / name).write_bytes(b"synthetic bytes")
    return {
        "archive_root": str(archive),
        "selected_files": ["00000001_ON.fits", "00000001_OFF.fits"],
        "fits_file_paths": [str(archive / "00000001_ON.fits"), str(archive / "00000001_OFF.fits")],
        "observation_blocks": {"00000001_0.txt": ["00000001_ON.fits", "00000001_OFF.fits"]},
        "source_name": "Test source", "frequency_mhz": 1420.405,
        "discarded_files": [], "file_check_error": None,
    }


def test_create_queue_from_committed_source_and_show_status_on_next_run(tmp_path, monkeypatch):
    selection = _selection(tmp_path)
    st, ui, events = _app(monkeypatch, selection)
    st.clicked = {"fr21_create_queue"}
    ui.render_batch_panel(
        selection, source_session_id="s0102030", sessions_root=tmp_path / "sessions",
        verify_file=lambda path: SimpleNamespace(ok=True, issues=[]),
    )
    saved_id = selection["batch_queue_id"]
    saved = batch_queue.load_batch(tmp_path / "sessions", saved_id)
    assert saved["jobs"][0]["status"] == "pending"
    assert any("Batch " in event and " prepared" in event for event in events)
    assert "checkpoint: Batch queue prepared" in events
    assert st.tables and st.tables[0][0]["Status"] == "Pending"
    assert st.progress_fractions == [0]
    assert any("No manual session JSON" in message for message in st.messages)

    st.clicked.clear()
    st.session_state["fr21_batch_editor_open"] = False
    st.session_state.pop("fr21_current_batch_id", None)
    ui.render_batch_panel(
        selection, source_session_id="s0102030", sessions_root=tmp_path / "sessions",
        verify_file=lambda path: SimpleNamespace(ok=True, issues=[]),
    )
    assert st.tables[-1][0]["Block"] == "00000001_0.txt"
    assert len(list((tmp_path / "sessions" / "batches").glob("*.json"))) == 1


def test_invalid_block_shows_readable_issues_without_starting_processing(tmp_path, monkeypatch):
    selection = _selection(tmp_path)
    st, ui, events = _app(monkeypatch, selection)
    st.clicked = {"fr21_create_queue"}
    ui.render_batch_panel(
        selection, source_session_id="s0102030", sessions_root=tmp_path / "sessions",
        verify_file=lambda path: SimpleNamespace(ok=False, issues=["Checksum mismatch"]),
    )
    assert st.tables[0][0]["Status"] == "Invalid"
    assert any("Checksum mismatch" in message for message in st.messages)
    assert batch_queue.load_batch(tmp_path / "sessions", selection["batch_queue_id"])["processing_enabled"] is False
