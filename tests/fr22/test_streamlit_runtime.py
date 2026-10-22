# test_streamlit_runtime.py — FR-22 real AppTest smoke checks in the pinned app environment.
from pathlib import Path

import pytest

pytest.importorskip("streamlit", reason="Requires installed Streamlit 1.32.0")
from streamlit.testing.v1 import AppTest  # noqa: E402

SCRIPT = '''
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from utils import styles, sidebar, session_store

st.set_page_config(layout="wide")
session_store.SESSIONS_DIR = Path(st.session_state["test_session_dir"])
session_store.init_session_state()
sidebar.render_sidebar(1)
styles.inject_base_css()
styles.render_page_header("FR-22 test", "Synthetic display-only data", 1, 0)
with st.expander("Existing page section", expanded=True):
    styles.render_dataframe(pd.DataFrame({"A": [1, 2]}), hide_index=True)
    fig = go.Figure(go.Scatter(x=[0, 1, 2], y=[1, 3, 2], name="Synthetic data"))
    fig.update_layout(height=300, font={"size": 11})
    styles.render_plotly_chart(fig, use_container_width=True, theme=None)
'''


def test_font_scale_native_widget_and_nested_section(tmp_path):
    app = AppTest.from_string(SCRIPT, default_timeout=15)
    app.session_state["test_session_dir"] = str(tmp_path / "sessions")
    app.run()
    assert not app.exception
    app.selectbox(key="_a11y_font_scale").set_value(200).run()
    assert not app.exception
    assert app.session_state["font_scale"] == 200
    app.button(key="theme_dark").click().run()
    assert not app.exception
    assert app.session_state["theme"] == "dark" and app.session_state["font_scale"] == 200
    assert app.session_state["pipeline_data"] == {}
    assert app.session_state["completed_stages"] == set()
    assert Path(app.session_state["checkpoint_path"]).is_file()


def test_native_chart_controls_render_inside_existing_expander(tmp_path):
    app = AppTest.from_string(SCRIPT, default_timeout=15)
    app.session_state["test_session_dir"] = str(tmp_path / "sessions")
    app.run()
    assert not app.exception
    control = next(widget for widget in app.checkbox if widget.label == "Keyboard chart controls and values")
    control.set_value(True).run()
    assert not app.exception
    assert any(widget.label == "Visible chart series" for widget in app.multiselect)
