# test_state_roundtrip.py — FR-22 real JSON persistence, with only the UI facade substituted.
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

APP = Path(__file__).resolve().parents[2] / "hartspec_gui"


def test_save_load_reset_and_recovery_display_policy(monkeypatch, tmp_path):
    ui = ModuleType("streamlit")
    ui.session_state = {}
    monkeypatch.setitem(sys.modules, "streamlit", ui)
    monkeypatch.setenv("SESSIONS_PATH", str(tmp_path / "sessions"))
    spec = importlib.util.spec_from_file_location("_fr22_store", APP / "utils/session_store.py")
    store = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(store)
    store.init_session_state()
    ui.session_state.update(theme="dark", font_scale=150)
    path = store.save_session()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["preferences"] == {"theme": "dark", "font_scale": 150}
    store.reset_session(navigate=False)
    assert ui.session_state["font_scale"] == 150
    ui.session_state.update(theme="light", font_scale=200)
    store.load_session(path, navigate=False)
    # Loading another reduction deliberately preserves the user's current access needs.
    assert ui.session_state["font_scale"] == 200 and ui.session_state["theme"] == "light"
    store.recover_checkpoint(path, navigate=False)
    assert ui.session_state["font_scale"] == 150 and ui.session_state["theme"] == "dark"
    assert json.loads(path.read_text(encoding="utf-8")) == saved


def test_bridge_font_change_preserves_scientific_state(monkeypatch, tmp_path):
    ui = ModuleType("streamlit")
    ui.session_state = {}
    monkeypatch.setitem(sys.modules, "streamlit", ui)
    monkeypatch.setenv("SESSIONS_PATH", str(tmp_path / "sessions"))
    spec = importlib.util.spec_from_file_location("_fr22_bridge", APP / "utils/baseline_editor_bridge.py")
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    monkeypatch.setattr(bridge, "SESSIONS_DIR", tmp_path / "sessions")
    spectrum = {"Vlsr": [-1., 0., 1.], "LCP": [1., 2., 1.], "RCP": [2., 3., 2.]}
    initial = bridge.initialize_bridge("fr22_test", spectrum, "light", "Frequency Switch")
    initial.update(blocks=[{"block": 1, "start": -1., "end": 0.}], fit_result={"existing": True}, complete=True)
    bridge.write_bridge("fr22_test", initial)
    updated = bridge.initialize_bridge("fr22_test", spectrum, "dark", "Frequency Switch", font_scale=200)
    assert updated["theme"] == "dark" and updated["font_scale"] == 200
    for key in ("spectrum", "spectrum_fingerprint", "blocks", "fit_result", "complete"):
        assert updated[key] == initial[key]
