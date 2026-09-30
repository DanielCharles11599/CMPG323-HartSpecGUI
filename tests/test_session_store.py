# test_session_store.py — tests for the utils/session_store.py functions added/changed for FR-19 and the header
# progress bar: list_sessions() must ignore sidecar files, and completed_before() must count only earlier stages.
#
# session_store reads st.session_state and SESSIONS_DIR at call time, so both are swapped for plain stand-ins.

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hartspec_gui"))

from utils import session_store  # noqa: E402


def _fake_streamlit(monkeypatch, **state):
    monkeypatch.setattr(session_store, "st", SimpleNamespace(session_state=dict(state)))
    return session_store.st.session_state


def _write(path: Path, payload: dict, mtime: float) -> None:
    path.write_text(json.dumps(payload))
    os.utime(path, (mtime, mtime))


# ---- list_sessions ---------------------------------------------------------------------------------------------
def test_list_sessions_excludes_dash_bridge_sidecar_even_when_it_is_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path)
    now = time.time()
    _write(tmp_path / "abcd1234.json", {"pipeline_data": {}}, now - 100)
    _write(tmp_path / "abcd1234.baseline_editor.json", {"blocks": []}, now)  # Dash rewrites this constantly
    listed = [p.name for p in session_store.list_sessions()]
    assert listed == ["abcd1234.json"]


def test_list_sessions_still_orders_real_sessions_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path)
    now = time.time()
    _write(tmp_path / "old00000.json", {}, now - 300)
    _write(tmp_path / "new00000.json", {}, now - 10)
    _write(tmp_path / "mid00000.json", {}, now - 100)
    assert [p.stem for p in session_store.list_sessions()] == ["new00000", "mid00000", "old00000"]


def test_loading_the_top_listed_session_never_wipes_state_via_a_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path)
    state = _fake_streamlit(monkeypatch, session_id="cur00000")
    now = time.time()
    _write(tmp_path / "abcd1234.json",
           {"session_id": "abcd1234", "pipeline_data": {"03_bandpass_correction": {"mode": "Frequency Switch"}},
            "completed_stages": ["03_bandpass_correction"], "audit_log": []}, now - 100)
    _write(tmp_path / "abcd1234.baseline_editor.json", {"session_id": "abcd1234", "blocks": []}, now)
    session_store.load_session(session_store.list_sessions()[0])
    assert state["completed_stages"] == {"03_bandpass_correction"}
    assert state["pipeline_data"]["03_bandpass_correction"]["mode"] == "Frequency Switch"


def test_list_sessions_creates_missing_directory(tmp_path, monkeypatch):
    target = tmp_path / "does" / "not" / "exist"
    monkeypatch.setattr(session_store, "SESSIONS_DIR", target)
    assert session_store.list_sessions() == [] and target.is_dir()


# ---- completed_before ------------------------------------------------------------------------------------------
def test_stage_keys_are_eight_unique_keys_in_pipeline_order():
    keys = session_store.STAGE_KEYS
    assert len(keys) == 8 and len(set(keys)) == 8
    assert keys[0] == "01_source_browser" and keys[1] == "file_loader" and keys[-1] == "08_export_and_session"


def test_completed_before_counts_only_strictly_earlier_stages(monkeypatch):
    _fake_streamlit(monkeypatch, completed_stages=set(session_store.STAGE_KEYS))  # everything complete
    assert session_store.completed_before(1) == 0
    assert session_store.completed_before(7) == 6
    assert session_store.completed_before(8) == 7  # Page 8 must never read 8/8
    assert session_store.completed_count() == 8  # the old value the header used


def test_completed_before_ignores_later_stages_and_the_current_page(monkeypatch):
    _fake_streamlit(monkeypatch, completed_stages={"01_source_browser", "07_spectral_fitting", "08_export_and_session"})
    assert session_store.completed_before(7) == 1  # 07 itself and 08 are not "before" page 7
    assert session_store.completed_before(8) == 2


def test_completed_before_handles_empty_session_and_out_of_range_input(monkeypatch):
    _fake_streamlit(monkeypatch, completed_stages=set())
    assert session_store.completed_before(8) == 0
    assert session_store.completed_before(0) == 0
    assert session_store.completed_before(-3) == 0
