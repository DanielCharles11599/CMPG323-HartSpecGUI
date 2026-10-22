# Keyboard_Help.py — FR-22/NFR-11: read-only accessibility manual, opened in a separate tab.
"""Not a ninth pipeline stage: no recovery, fitting, save or checkpoint actions."""
from __future__ import annotations

import streamlit as st

from utils import styles
from utils.accessibility_help import help_preferences, read_help_text

st.set_page_config(page_title="HARTSPEC — Keyboard and accessibility help", layout="wide",
                   initial_sidebar_state="collapsed")
theme, font_scale = help_preferences(st.query_params)
st.session_state["theme"] = theme
st.session_state["font_scale"] = font_scale
styles.inject_base_css()
st.markdown(
    '<style>.block-container { max-width: 58rem !important; } '
    '[data-testid="stMarkdownContainer"] :is(p, li, td, th) { line-height: 1.6; }</style>',
    unsafe_allow_html=True,
)
st.caption("USER MANUAL · Keyboard and accessibility")
st.info("This is a separate, read-only help tab. Close it to return to your reduction. "
        "Reading help does not load, save or change a reduction.")
try:
    st.markdown(read_help_text())
except OSError:
    st.error("The help chapter is missing from this installation. Include "
             "hartspec_gui/help/keyboard_accessibility.md when deploying the application.")
