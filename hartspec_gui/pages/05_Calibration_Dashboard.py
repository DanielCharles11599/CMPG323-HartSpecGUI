# 05_Calibration_Dashboard.py — FR-10 / FR-11
#
# Calibration Dashboard for atmospheric calibration and Point Source
# Sensitivity (PSS) visualisation.
#
# Scientific calculations are handled by the existing CLC calibration
# module and will be connected to this page separately.

import plotly.graph_objects as go
import streamlit as st

from utils import session_store, sidebar, styles


CURRENT_STAGE = 5

PAGE_TITLE = "Calibration Dashboard"
PAGE_SUBTITLE = "FR-10 / FR-11 — atmospheric and PSS calibration"

st.set_page_config(
    page_title="HARTSPEC — Calibration Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

session_store.init_session_state()
sidebar.render_sidebar(current_stage=CURRENT_STAGE)
styles.inject_base_css()

_theme = styles.get_theme()

styles.render_page_header(
    title=PAGE_TITLE,
    subtitle=PAGE_SUBTITLE,
    current_stage=CURRENT_STAGE,
    completed_stages=session_store.completed_count(),
)


# Atmospheric calibration

with st.container(border=True):
    st.markdown(
        '<div class="hs-panel-title">Atmospheric calibration</div>',
        unsafe_allow_html=True,
    )

    metric_cols = st.columns(4)

    with metric_cols[0]:
        st.metric("PWV", "Not calculated")

    with metric_cols[1]:
        st.metric("Elevation", "Not calculated")

    with metric_cols[2]:
        st.metric("Zenith optical depth", "Not calculated")

    with metric_cols[3]:
        st.metric("ATcor", "Not calculated")

    atmospheric_fig = go.Figure()

    atmospheric_fig.add_annotation(
        text="Atmospheric calibration data will appear here",
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(
            family="Inter, -apple-system, 'Segoe UI', sans-serif",
            size=13,
            color=_theme["text-muted"],
        ),
    )

    atmospheric_fig.update_layout(
        paper_bgcolor=_theme["bg-panel"],
        plot_bgcolor=_theme["bg-panel"],
        margin=dict(l=48, r=16, t=20, b=40),
        height=300,
        xaxis=dict(
            visible=False,
        ),
        yaxis=dict(
            visible=False,
        ),
        font=dict(
            family="Inter, -apple-system, 'Segoe UI', sans-serif",
            size=11,
            color=_theme["text-body"],
        ),
    )

    st.plotly_chart(
        atmospheric_fig,
        use_container_width=True,
        config={"displayModeBar": False},
    )


# PSS calibration

with st.container(border=True):
    st.markdown(
        '<div class="hs-panel-title">PSS calibration</div>',
        unsafe_allow_html=True,
    )

    pss_metric_cols = st.columns(2)

    with pss_metric_cols[0]:
        st.metric("LCP monthly mean", "Not calculated")

    with pss_metric_cols[1]:
        st.metric("RCP monthly mean", "Not calculated")

    pss_fig = go.Figure()

    pss_fig.add_annotation(
        text="PSS time-series data will appear here",
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(
            family="Inter, -apple-system, 'Segoe UI', sans-serif",
            size=13,
            color=_theme["text-muted"],
        ),
    )

    pss_fig.update_layout(
        paper_bgcolor=_theme["bg-panel"],
        plot_bgcolor=_theme["bg-panel"],
        margin=dict(l=48, r=16, t=20, b=40),
        height=300,
        xaxis=dict(
            visible=False,
        ),
        yaxis=dict(
            visible=False,
        ),
        font=dict(
            family="Inter, -apple-system, 'Segoe UI', sans-serif",
            size=11,
            color=_theme["text-body"],
        ),
    )

    st.plotly_chart(
        pss_fig,
        use_container_width=True,
        config={"displayModeBar": False},
    )
