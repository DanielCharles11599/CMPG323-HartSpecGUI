# test_export_page_polish_runtime.py — FR-22: native Page 08 table/panel interaction checks.
from __future__ import annotations

import pytest

pytest.importorskip("streamlit", reason="Requires the project's native Streamlit environment")
from streamlit.testing.v1 import AppTest  # noqa: E402

SCRIPT = '''
import pandas as pd
import streamlit as st
from utils import export_page_ui, styles
from utils.accessibility_help import help_link_html

st.set_page_config(layout="wide")
st.session_state.setdefault("pipeline_data", {"test": "unchanged"})
st.session_state.setdefault("audit_log", [{"ts": "10:00:00", "message": "Recorded"}])
styles.inject_base_css()
export_page_ui.inject_css(styles.get_theme())
with export_page_ui.section("Observation log"):
    frame = pd.DataFrame({"Entry": range(121), "Message": [f"EVENT-{i}-END" for i in range(121)]})
    export_page_ui.render_review_table(frame.style, hide_index=True)
st.markdown(help_link_html(styles.get_theme_name(), styles.get_font_scale()), unsafe_allow_html=True)
'''


def test_pagination_theme_and_font_changes_do_not_mutate_recorded_data():
    app = AppTest.from_string(SCRIPT, default_timeout=15).run()
    assert not app.exception
    app.selectbox(key="export_observation_log_events_review_page").set_value("3 of 3").run()
    assert not app.exception
    assert any("EVENT-120-END" in widget.value for widget in app.markdown)
    app.session_state["theme"] = "dark"
    app.session_state["font_scale"] = 200
    app.run()
    assert not app.exception
    assert app.session_state["pipeline_data"] == {"test": "unchanged"}
    assert app.session_state["audit_log"] == [{"ts": "10:00:00", "message": "Recorded"}]
    assert not app.dataframe


def test_optional_grid_still_contains_every_filtered_row():
    app = AppTest.from_string(SCRIPT, default_timeout=15).run()
    assert not app.exception
    app.checkbox(key="export_observation_log_events_review_grid").set_value(True).run()
    assert not app.exception
    assert len(app.dataframe) == 1
    assert len(app.dataframe[0].value) == 121
