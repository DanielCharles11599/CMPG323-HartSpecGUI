# 05_Calibration_Dashboard.py — FR-10 / FR-11
#
# Calibration Dashboard for atmospheric calibration and Point Source
# Sensitivity (PSS) visualisation.
#
# Scientific calculations will be integrated through the existing
# clc/Calibrate_PSS_PWR.py module. This page must not duplicate the
# scientific calibration equations.

import streamlit as st

from utils import session_store, sidebar, styles


# Page identity
CURRENT_STAGE = 5

PAGE_TITLE = "Calibration Dashboard"
PAGE_SUBTITLE = "FR-10 / FR-11 — atmospheric calibration and PSS visualisation"


# Shared page setup
st.set_page_config(
    page_title="HARTSPEC — Calibration Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

session_store.init_session_state()
sidebar.render_sidebar(current_stage=CURRENT_STAGE)
styles.inject_base_css()


# Header
styles.render_page_header(
    title=PAGE_TITLE,
    subtitle=PAGE_SUBTITLE,
    current_stage=CURRENT_STAGE,
    completed_stages=session_store.completed_count(),
)


# Atmospheric calibration
st.subheader("Atmospheric calibration")

st.caption(
    "Precipitable water vapour, elevation, zenith optical depth "
    "and atmospheric correction factor."
)

st.info(
    "Atmospheric calibration integration will use the observation metadata "
    "loaded earlier in the pipeline."
)


# PSS visualisation
st.subheader("Point Source Sensitivity")

st.caption(
    "LCP and RCP Point Source Sensitivity values around the observation epoch."
)

st.info(
    "PSS data integration and the interactive time-series visualisation "
    "will be added in the next implementation stage."
)
