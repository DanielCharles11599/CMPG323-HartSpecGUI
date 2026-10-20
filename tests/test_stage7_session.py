# test_stage7_session.py — FR-19: real session JSON I/O for all four Stage 7 modes.
"""Only the Streamlit facade is replaced; session_store/checkpoint_store are real."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from utils import fitting_helpers as fh, fitting_state as fs

APP = Path(__file__).resolve().parents[1] / "hartspec_gui"


@pytest.fixture
def store(monkeypatch, tmp_path):
    """Load a private real store against an isolated JSON directory and UI facade."""
    ui = ModuleType("streamlit")
    ui.session_state = {}
    monkeypatch.setitem(sys.modules, "streamlit", ui)
    monkeypatch.setenv("SESSIONS_PATH", str(tmp_path / "sessions"))
    spec = importlib.util.spec_from_file_location("_stage7_store", APP / "utils/session_store.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.init_session_state()
    return module, ui.session_state


@pytest.mark.parametrize("mode", fh.FIT_TYPES)
def test_real_save_load_fitting_state_and_exact_covariance(store, mode):
    module, state = store
    stage = fs.ensure_stage(state["pipeline_data"])
    stage.update(fit_type=mode, fit_type_requested=mode)
    options = {"p0": [3., 1., 2., 4., 3., 17., .1]} if mode == "2D Gaussian" else {"test_precision": 1.2345678901234567}
    entry = fs.mode_state(stage, mode, "source-id")
    entry["options"] = options
    request = fs.request_key("source-id", options)
    result = {"ok": True, "covariance": [[1.2345678901234567, None], [None, 0.]], "curve": [1., 2., 3.]}
    fs.save_result(entry, request, result)
    stage["committed_request"] = request
    if mode == "2D Gaussian":
        stage["map_snapshot"] = fs.json_safe(fh.synthetic_map_2d())
        entry["synthetic"] = False  # Explicit test fixture exercising observed-map persistence.
    module.mark_stage_complete(fs.STAGE_KEY)
    module.log_event("Stage 7 round-trip fixture")
    path = module.save_session()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["stages"]["fitting"]["params"] == options
    assert payload["stages"]["fitting"]["state"] == stage
    original_bytes = path.read_bytes()
    state["fit_stale_widget"] = "must be removed on load"
    state["map_2d_data"] = {"stale": True}
    module.load_session(path, navigate=False)
    restored = state["pipeline_data"][fs.STAGE_KEY]
    assert restored == stage
    assert state["fit_type"] == mode
    assert "fit_stale_widget" not in state
    assert fs.result_is_current(restored["modes"][mode], request)
    if mode == "2D Gaussian":
        assert state["map_2d_data"] == stage["map_snapshot"]
        assert fh.coerce_map_2d(state["map_2d_data"]) is not None
    else:
        assert "map_2d_data" not in state
    assert path.read_bytes() == original_bytes


def test_reset_removes_spatial_map_and_fit_controls(store):
    module, state = store
    state.update(map_2d_data={"data": np.ones((3, 3))}, fit_2d_old="stale", latest_fit={"old": True})
    fs.ensure_stage(state["pipeline_data"])
    module.reset_session(navigate=False)
    assert "map_2d_data" not in state
    assert "fit_2d_old" not in state
    assert "latest_fit" not in state
    assert fs.STAGE_KEY not in state["pipeline_data"]
