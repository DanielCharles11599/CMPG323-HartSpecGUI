# 05_Calibration_Dashboard.py — FR-10 / FR-11
#
# Calibration Dashboard for atmospheric calibration and Point Source
# Sensitivity (PSS) visualisation.
#
# Atmospheric calculations use the existing CLC calibration module.
# Page 05 only handles the GUI and integration around those calculations.

import plotly.graph_objects as go
import streamlit as st

from utils import calibration_logic, session_store, sidebar, styles


CURRENT_STAGE = 5
PAGE_STAGE_KEY = "05_calibration_dashboard"

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

loaded_spectrum = st.session_state.get("loaded_spectrum")
atmospheric_result = None
atmospheric_error = None

pss_history = None
pss_window = None
pss_averages = None
pss_error = None

if loaded_spectrum is not None:
    try:
        atmospheric_result = calibration_logic.get_atmospheric_calibration(
            loaded_spectrum
        )
    except Exception as exc:
        atmospheric_error = str(exc)

if loaded_spectrum is not None:
    try:
        pss_history = calibration_logic.get_pss_history(
            loaded_spectrum["restfreq"]
        )
        pss_window = calibration_logic.get_pss_window(
            loaded_spectrum["date"]
        )
        pss_averages = calibration_logic.get_pss_window_averages(
            pss_history,
            pss_window,
        )
    except Exception as exc:
        pss_error = str(exc)

was_page_complete = PAGE_STAGE_KEY in st.session_state["completed_stages"]

baseline_ready = (
    "04_baseline_editor" in st.session_state["completed_stages"]
    and st.session_state.get("baseline_corrected_spectrum") is not None
)

if loaded_spectrum is not None:
    page_complete = (
        baseline_ready
        and atmospheric_result is not None
        and atmospheric_result["optical_depth"] is not None
        and atmospheric_error is None
        and pss_history is not None
        and pss_window is not None
        and pss_averages is not None
        and pss_averages["lcp"] is not None
        and pss_averages["rcp"] is not None
        and pss_error is None
    )

    page_payload = {
        "complete": page_complete,
        "atmospheric": None,
        "pss": None,
    }

    if atmospheric_result is not None:
        page_payload["atmospheric"] = {
            "frequency": atmospheric_result["frequency"],
            "pwv": float(atmospheric_result["pwv"]),
            "elevation": float(atmospheric_result["elevation"]),
            "azimuth": float(atmospheric_result["azimuth"]),
            "atcor": float(atmospheric_result["atcor"]),
            "optical_depth": atmospheric_result["optical_depth"],
        }

    if pss_history is not None and pss_window is not None:
        page_payload["pss"] = {
            "frequency": pss_history["frequency"],
            "observation_mjd": float(pss_window["observation_mjd"]),
            "start_mjd": float(pss_window["start_mjd"]),
            "end_mjd": float(pss_window["end_mjd"]),
            "window_days": int(pss_window["days"]),
            "lcp_window_mean": (
                None
                if pss_averages is None or pss_averages["lcp"] is None
                else float(pss_averages["lcp"])
            ),
            "rcp_window_mean": (
                None
                if pss_averages is None or pss_averages["rcp"] is None
                else float(pss_averages["rcp"])
            ),
            "source_files": dict(pss_history["source_files"]),
        }

    if atmospheric_error is not None:
        page_payload["atmospheric_error"] = atmospheric_error

    if pss_error is not None:
        page_payload["pss_error"] = pss_error

    st.session_state["pipeline_data"][PAGE_STAGE_KEY] = page_payload

    if page_complete:
        session_store.mark_stage_complete(PAGE_STAGE_KEY)

        if not was_page_complete:
            session_store.log_event(
                "Calibration dashboard completed — "
                f"PWV {atmospheric_result['pwv']:.3f} mm, "
                f"elevation {atmospheric_result['elevation']:.3f}°, "
                f"zenith optical depth {atmospheric_result['optical_depth']:.4f}, "
                f"ATcor {atmospheric_result['atcor']:.4f}"
            )
    else:
        st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)
else:
    st.session_state["pipeline_data"].pop(PAGE_STAGE_KEY, None)
    st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)

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

    if atmospheric_result is not None:
        pwv_value = f"{atmospheric_result['pwv']:.3f} mm"
        elevation_value = f"{atmospheric_result['elevation']:.3f}°"
        optical_depth_value = f"{atmospheric_result['optical_depth']:.4f}"
        atcor_value = f"{atmospheric_result['atcor']:.4f}"
    else:
        pwv_value = "Not calculated"
        elevation_value = "Not calculated"
        optical_depth_value = "Not calculated"
        atcor_value = "Not calculated"

    with metric_cols[0]:
        st.metric("PWV", pwv_value)

    with metric_cols[1]:
        st.metric("Elevation", elevation_value)

    with metric_cols[2]:
        st.metric("Zenith optical depth", optical_depth_value)

    with metric_cols[3]:
        st.metric("ATcor", atcor_value)

    if loaded_spectrum is None:
        st.info("Load a spectrum before running atmospheric calibration.")
    elif atmospheric_error is not None:
        st.error(f"Atmospheric calibration could not be completed: {atmospheric_error}")

    atmospheric_fig = go.Figure()

    if atmospheric_result is not None:
        atmospheric_fig.add_trace(
            go.Bar(
                x=["PWV"],
                y=[atmospheric_result["pwv"]],
                name="PWV",
                hovertemplate="PWV %{y:.3f} mm<extra></extra>",
            )
        )

        atmospheric_fig.add_trace(
            go.Bar(
                x=["ATcor"],
                y=[atmospheric_result["atcor"]],
                name="ATcor",
                yaxis="y2",
                hovertemplate="ATcor %{y:.4f}<extra></extra>",
            )
        )

        atmospheric_fig.update_layout(
            paper_bgcolor=_theme["bg-panel"],
            plot_bgcolor=_theme["bg-panel"],
            margin=dict(l=48, r=48, t=28, b=40),
            height=300,
            bargap=0.5,
            showlegend=False,
            xaxis=dict(
                title="Current observation",
            ),
            yaxis=dict(
                title="PWV (mm)",
                rangemode="tozero",
            ),
            yaxis2=dict(
                title="ATcor",
                overlaying="y",
                side="right",
                rangemode="tozero",
            ),
            font=dict(
                family="Inter, -apple-system, 'Segoe UI', sans-serif",
                size=11,
                color=_theme["text-body"],
            ),
        )
    else:
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
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
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
        theme=None
    )


# PSS calibration

with st.container(border=True):
    st.markdown(
        '<div class="hs-panel-title">PSS calibration</div>',
        unsafe_allow_html=True,
    )

    pss_metric_cols = st.columns(2)

    if pss_averages is not None:
        lcp_mean_value = (
            f"{pss_averages['lcp']:.4f}"
            if pss_averages["lcp"] is not None
            else "Not available"
        )
        rcp_mean_value = (
            f"{pss_averages['rcp']:.4f}"
            if pss_averages["rcp"] is not None
            else "Not available"
        )
    else:
        lcp_mean_value = "Not calculated"
        rcp_mean_value = "Not calculated"

    with pss_metric_cols[0]:
        st.metric("LCP ±15-day mean", lcp_mean_value)

    with pss_metric_cols[1]:
        st.metric("RCP ±15-day mean", rcp_mean_value)

    if loaded_spectrum is None:
        st.info("Load a spectrum to view PSS calibration history.")
    elif pss_error is not None:
        st.error(f"PSS calibration history could not be loaded: {pss_error}")

    pss_fig = go.Figure()

    if pss_history is not None and pss_window is not None:
        pss_fig.add_trace(
            go.Scatter(
                x=pss_history["lcp"]["mjd"],
                y=pss_history["lcp"]["pss"],
                mode="lines",
                name="LCP",
                line=dict(color="#1F77B4"),
                hovertemplate="MJD %{x:.3f}<br>LCP %{y:.4f}<extra></extra>",
            )
        )

        pss_fig.add_trace(
            go.Scatter(
                x=pss_history["rcp"]["mjd"],
                y=pss_history["rcp"]["pss"],
                mode="lines",
                name="RCP",
                line=dict(color="#FF7F0E"),
                hovertemplate="MJD %{x:.3f}<br>RCP %{y:.4f}<extra></extra>",
            )
        )

        pss_fig.add_vrect(
            x0=pss_window["start_mjd"],
            x1=pss_window["end_mjd"],
            opacity=0.12,
            line_width=0,
            layer="below",
            annotation_text="±15 day window",
            annotation_position="top left",
        )

        pss_fig.add_vline(
            x=pss_window["observation_mjd"],
            line_dash="dash",
            annotation_text="Observation",
            annotation_position="top",
        )

        pss_fig.update_layout(
            paper_bgcolor=_theme["bg-panel"],
            plot_bgcolor=_theme["bg-panel"],
            margin=dict(l=48, r=16, t=28, b=48),
            height=340,
            xaxis=dict(
                title="Modified Julian Date",
                range=[
                    pss_window["start_mjd"],
                    pss_window["end_mjd"],
                ],
            ),
            yaxis=dict(
                title="PSS",
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
            font=dict(
                family="Inter, -apple-system, 'Segoe UI', sans-serif",
                size=11,
                color=_theme["text-body"],
            ),
        )
    else:
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
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
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
        theme=None
    )
