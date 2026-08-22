"""HARTSPEC GUI entry point. Redirects straight into the pipeline."""

import streamlit as st

from utils import session_store, sidebar, styles

st.set_page_config(page_title="HARTSPEC", layout="wide", initial_sidebar_state="expanded")
session_store.init_session_state()
sidebar.render_sidebar(current_stage=0)
styles.inject_base_css()

styles.render_page_header(
    title="HARTSPEC",
    subtitle="HartRAO data reduction pipeline",
    current_stage=0,
    completed_stages=session_store.completed_count(),
)
st.write("Select a pipeline stage from the sidebar to begin.")
