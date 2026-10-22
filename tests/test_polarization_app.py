# test_polarization_app.py — FR-09: real Streamlit AppTest checks (pinned app environment).
"""Run with the project's dependencies; skip explicitly when they are unavailable.

This mounts the real shared panel, not a replacement GUI implementation.
Full Page 05/session-store verification still requires the repository helpers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="Real AppTest requires the project's Streamlit dependency")
pytest.importorskip("astropy", reason="The original clc/Pols.py imports Astropy")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hartspec_gui"))

STAGE = "05_calibration_dashboard"
PREFIX = "calibration_polarization"
SCRIPT = '''
import numpy as np
import streamlit as st
from utils import styles
from utils.polarization_panel import render_polarization_panel

st.set_page_config(layout="wide")
st.session_state.setdefault("session_id", "fr09-apptest")
st.session_state.setdefault("pipeline_data", {"05_calibration_dashboard": {}})
st.session_state.setdefault("completed_stages", set())
styles.inject_base_css()
n = st.session_state.get("test_channels", 31)
x = np.linspace(-10., 10., n)
spectrum = {"Vlsr": x, "LCP": np.sin(x) + 1, "RCP": np.cos(x) + 2}
if st.session_state.get("test_no_input", False):
    spectrum = None
if st.session_state.get("test_show_panel", True):
    render_polarization_panel(
        spectrum, source_key="baseline", source_label="Baseline input", intensity_unit="K",
    )
else:
    st.write("Another page; polarization controls are not rendered.")
'''


def app(**state):
    """Create a real ScriptRunner-backed app with explicitly seeded test inputs."""
    result = AppTest.from_string(SCRIPT, default_timeout=15)
    for key, value in state.items():
        result.session_state[key] = value
    result.run()
    assert not result.exception
    return result


def record(at):
    """Read the permanent view metadata rather than temporary widget state."""
    return at.session_state["pipeline_data"][STAGE]["polarization_display"]


def test_real_widgets_default_to_unsmoothed_overlay():
    at = app()
    assert at.toggle(key=f"{PREFIX}_smooth").value is False
    assert at.number_input(key=f"{PREFIX}_window").value == 7
    assert at.number_input(key=f"{PREFIX}_window").disabled
    assert len(at.get("plotly_chart")) == 1
    assert not at.session_state["completed_stages"]


def test_real_toggle_and_window_edits_survive_reruns():
    at = app()
    at.toggle(key=f"{PREFIX}_smooth").set_value(True).run()
    assert not at.exception
    assert record(at)["smoothing_enabled"] is True
    at.number_input(key=f"{PREFIX}_window").set_value(11).run()
    assert not at.exception
    assert record(at)["window_length"] == 11
    at.run()
    assert at.number_input(key=f"{PREFIX}_window").value == 11


def test_widget_cleanup_does_not_erase_permanent_preferences():
    at = app()
    at.toggle(key=f"{PREFIX}_smooth").set_value(True).run()
    at.number_input(key=f"{PREFIX}_window").set_value(9).run()
    at.session_state["test_show_panel"] = False
    at.run()
    at.session_state["test_show_panel"] = True
    at.run()
    assert not at.exception
    assert at.toggle(key=f"{PREFIX}_smooth").value is True
    assert at.number_input(key=f"{PREFIX}_window").value == 9


def test_json_restore_overrides_old_widget_values_even_with_same_session_id():
    at = app()
    loaded = json.loads(json.dumps(at.session_state["pipeline_data"]))
    loaded[STAGE]["polarization_display"].update(smoothing_enabled=True, window_length=13)
    at.session_state["pipeline_data"] = loaded
    at.run()
    assert not at.exception
    assert at.toggle(key=f"{PREFIX}_smooth").value is True
    assert at.number_input(key=f"{PREFIX}_window").value == 13


def test_invalid_manual_even_window_has_visible_error():
    at = app()
    at.toggle(key=f"{PREFIX}_smooth").set_value(True).run()
    at.number_input(key=f"{PREFIX}_window").set_value(6).run()
    assert not at.exception
    assert any("odd" in error.value for error in at.error)
    assert record(at)["window_length"] == 7


def test_missing_data_is_guidance_not_a_fake_chart():
    at = app(test_no_input=True)
    assert at.info
    assert not at.get("plotly_chart")


def test_short_input_disables_smoothing_without_crashing():
    at = app(test_channels=3)
    assert at.toggle(key=f"{PREFIX}_smooth").disabled
    assert at.number_input(key=f"{PREFIX}_window").disabled
    assert len(at.get("plotly_chart")) == 1


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_real_panel_renders_in_each_theme(theme):
    at = app(theme=theme)
    assert not at.exception
    assert not at.error
    assert len(at.get("plotly_chart")) == 1
