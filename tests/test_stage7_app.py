# test_stage7_app.py — native Streamlit AppTest checks; run in the pinned project environment.
"""These tests need Streamlit (and the project's usual scientific dependencies).

They are separate from the dependency-light widget-contract tests. AppTest checks
server-side Streamlit execution; it is not a browser rendering/screenshot test.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402
from utils import fitting_helpers as fh, fitting_state as fs, session_store, sidebar  # noqa: E402

PAGE = Path(__file__).resolve().parents[1] / "hartspec_gui/pages/07_Spectral_Fitting.py"


@pytest.fixture
def native_app(monkeypatch, tmp_path):
    """Keep native widgets; isolate unrelated navigation and persistent session history."""
    monkeypatch.setattr(session_store, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(sidebar, "render_sidebar", lambda stage: None)
    return AppTest.from_file(str(PAGE), default_timeout=30)


def test_native_2d_explicit_run_and_no_repeat_on_theme_or_guess(native_app, monkeypatch):
    calls = []
    original = fh.run_2d_gauss

    def measured(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(fh, "run_2d_gauss", measured)
    at = native_app
    at.session_state["fit_type"] = "2D Gaussian"
    at.session_state["map_2d_data"] = None
    at.run()
    assert not at.exception
    assert any(message.value == "Synthetic Test Map Active" for message in at.info)
    assert not calls
    assert len(at.number_input) == 7
    at.button(key="fit_2d_run").click().run()
    assert not at.exception and len(calls) == 1
    entry = at.session_state["pipeline_data"][fs.STAGE_KEY]["modes"]["2D Gaussian"]
    assert np.asarray(entry["result"]["pcov"]).shape == (7, 7)
    at.session_state["theme"] = "dark"
    at.run()
    at.number_input[0].set_value(float(at.number_input[0].value) + .1).run()
    assert not at.exception and len(calls) == 1
    assert at.button(key="fit_save").disabled


def test_native_1d_poly_selector_and_cached_1d(native_app, monkeypatch):
    calls = []
    original = fh.run_gaussf

    def measured(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(fh, "run_gaussf", measured)
    v = np.linspace(-20., 20., 1024)
    y = fh.gaussian(v, 10., -4., 2.5)
    at = native_app
    at.session_state["calibrated_spectrum"] = {"Vlsr": v, "LCP": y / 2, "RCP": y / 2}
    at.session_state["pipeline_data"] = {
        "05_calibration_dashboard": {"pss": {"lcp_window_mean": 1., "rcp_window_mean": 1.}},
        "06_pointing_correction": {"correction_factor": 0., "input_source": "AppTest fixture"},
    }
    at.run()
    assert not at.exception and len(calls) == 1
    assert tuple(at.radio(key="fit_type").options) == fh.FIT_TYPES
    assert not at.button(key="fit_save").disabled
    at.run()
    assert len(calls) == 1
    at.radio(key="fit_type").set_value("Polynomial Peak").run()
    assert not at.exception and not at.button(key="fit_save").disabled
    assert at.number_input[1].value == 10
    at.radio(key="fit_type").set_value("Multi-Component").run()
    assert not at.exception
    entry = at.session_state["pipeline_data"][fs.STAGE_KEY]["modes"]["Multi-Component"]
    assert "result" not in entry
    assert entry["options"]["max_components"] == 10
    assert entry["options"]["rms_cutoff"] == 5.0
    assert entry["options"]["chi2_threshold"] == .01
