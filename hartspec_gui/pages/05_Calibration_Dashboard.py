# 05_Calibration_Dashboard.py — FR-09 / FR-10 / FR-11
#
# Calibration Dashboard for atmospheric calibration and Point Source
# Sensitivity (PSS) visualisation.
#
# Atmospheric calculations use the existing CLC calibration module.
# Page 05 only handles the GUI and integration around those calculations.

from typing import Mapping

import plotly.graph_objects as go
import streamlit as st

from utils import calibration_logic, session_store, sidebar, styles
from utils.polarization_logic import SETTINGS_KEY as POLARIZATION_SETTINGS_KEY
from utils.polarization_panel import render_polarization_panel
from utils.spectrum_resolution import CALIBRATED_UNIT, UNCALIBRATED_UNIT


CURRENT_STAGE = 5
PAGE_STAGE_KEY = "05_calibration_dashboard"

PAGE_TITLE = "Calibration Dashboard"
PAGE_SUBTITLE = "FR-09 / FR-10 / FR-11 — polarisation overlay, atmospheric and PSS calibration"

st.set_page_config(
    page_title="HARTSPEC — Calibration Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

session_store.init_session_state()
sidebar.render_sidebar(current_stage=CURRENT_STAGE)
# Pull the latest Dash result before reading any baseline-dependent view or calibration.
session_store.sync_baseline_state()
styles.inject_base_css()

_theme = styles.get_theme()

# Page 05 uses native bordered Streamlit containers and metric widgets.
# Keep them aligned with the shared HartSpec light/dark theme without
# modifying the application-wide stylesheet.
st.markdown(
    f"""
    <style>
    [data-testid="stMain"] [data-testid="stVerticalBlockBorderWrapper"] {{
        background-color: {_theme["bg-panel"]} !important;
        border-color: {_theme["border-subtle"]} !important;
    }}

    [data-testid="stMetricLabel"] p,
    [data-testid="stMetricLabel"] div {{
        color: {_theme["text-muted"]} !important;
    }}

    [data-testid="stMetricValue"],
    [data-testid="stMetricValue"] * {{
        color: {_theme["text-heading"]} !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

observation_pair_error = None
try:
    _pair_resolver = getattr(calibration_logic, "metadata_for_selected_pair", None)
    if callable(_pair_resolver):
        loaded_spectrum = _pair_resolver(st.session_state)
    elif "loaded_spectra" not in st.session_state:
        # Legacy single-spectrum sessions and minimal FR-09 test doubles.
        loaded_spectrum = st.session_state.get("loaded_spectrum")
    else:
        raise ValueError("Selected-pair metadata resolver is unavailable.")
except ValueError as exc:
    loaded_spectrum = None
    observation_pair_error = str(exc)

if observation_pair_error:
    st.error(
        f"Selected observation metadata unavailable: {observation_pair_error}"
    )
atmospheric_result = None
atmospheric_error = None

pss_history = None
pss_window = None
pss_averages = None
pss_30day_stats = None
pss_error = None
calibration_error = None

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
        pss_30day_stats = calibration_logic.get_pss_trailing_statistics(
            pss_history,
            pss_window["observation_mjd"],
            days=30,
        )
    except Exception as exc:
        pss_error = str(exc)

was_page_complete = PAGE_STAGE_KEY in st.session_state["completed_stages"]
# Page 05 rebuilds its calibration payload on reruns. Retain the nested FR-09
# view preferences; upstream invalidation removes this whole payload as before.
_saved_calibration_stage = st.session_state["pipeline_data"].get(PAGE_STAGE_KEY, {})
if not isinstance(_saved_calibration_stage, Mapping):
    # The session loader validates the envelope, not each stage's nested schema.
    # Recompute calibration below; never trust a malformed saved completion record.
    st.warning("Saved calibration stage data is malformed; this page will rebuild it from the current inputs.")
    _saved_calibration_stage = {}
_saved_polarization_display = _saved_calibration_stage.get(POLARIZATION_SETTINGS_KEY)

baseline_ready = (
    all(key in st.session_state["completed_stages"] for key in (
        "01_source_browser", "file_loader", "03_bandpass_correction", "04_baseline_editor",
    ))
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

    calibrated_spectrum = None
    if page_complete:
        try:
            mean_pss = (
                float(pss_averages["lcp"]) +
                float(pss_averages["rcp"])
            ) / 2.0
            calibrated_spectrum = (
                calibration_logic.apply_calibration_to_spectrum(
                    st.session_state["baseline_corrected_spectrum"],
                    atmospheric_result["atcor"],
                    mean_pss,
                )
            )
        except (ValueError, TypeError, KeyError) as exc:
            calibration_error = str(exc)
            page_complete = False

    if calibrated_spectrum is not None:
        st.session_state["calibrated_spectrum"] = calibrated_spectrum
    else:
        st.session_state.pop("calibrated_spectrum", None)

    page_payload = {
        "complete": page_complete,
        "atmospheric": None,
        "pss": None,
    }

    if _saved_polarization_display is not None:
        page_payload[POLARIZATION_SETTINGS_KEY] = _saved_polarization_display

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
            "trailing_30_day": (
                None
                if pss_30day_stats is None
                else {
                    "start_mjd": float(pss_30day_stats["start_mjd"]),
                    "end_mjd": float(pss_30day_stats["end_mjd"]),
                    "lcp_mean": pss_30day_stats["lcp"]["mean"],
                    "lcp_std": pss_30day_stats["lcp"]["std"],
                    "lcp_count": pss_30day_stats["lcp"]["count"],
                    "rcp_mean": pss_30day_stats["rcp"]["mean"],
                    "rcp_std": pss_30day_stats["rcp"]["std"],
                    "rcp_count": pss_30day_stats["rcp"]["count"],
                }
            ),
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
    # FR-09 can display a verified baseline even without atmospheric metadata.
    # Keep its view settings on that fallback path without completing calibration.
    if baseline_ready and _saved_polarization_display is not None:
        st.session_state["pipeline_data"][PAGE_STAGE_KEY] = {
            "complete": False, "atmospheric": None, "pss": None,
            POLARIZATION_SETTINGS_KEY: _saved_polarization_display,
        }
    else:
        st.session_state["pipeline_data"].pop(PAGE_STAGE_KEY, None)
    st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)
    st.session_state.pop("calibrated_spectrum", None)

if calibration_error:
    st.error(f"Spectrum calibration failed: {calibration_error}")

session_store.checkpoint_session("Calibration parameters recorded")

styles.render_page_header(
    title=PAGE_TITLE,
    subtitle=PAGE_SUBTITLE,
    current_stage=CURRENT_STAGE,
    completed_stages=session_store.completed_before(CURRENT_STAGE),
)

st.markdown(
    f"""
    <div style="
        background:
            color-mix(
                in srgb,
                {_theme["accent"]} 10%,
                {_theme["bg-panel"]}
            );
        border-left: 4px solid {_theme["accent"]};
        color: {_theme["text-body"]};
        padding: 12px 16px;
        border-radius: 6px;
        margin-bottom: 14px;
        line-height: 1.5;
        font-size: 0.92rem;
    ">
        Review the atmospheric calibration metrics and PSS history for the
        loaded observation. The shaded region marks the ±15-day PSS window,
        while the dashed vertical line marks the observation date. This stage
        completes automatically when the atmospheric calibration and both LCP
        and RCP PSS values are available.
    </div>
    """,
    unsafe_allow_html=True,
)


# Atmospheric calibration

with st.container(border=True):
    st.markdown(
        '<div class="hs-panel-title" style="font-size:0.92rem; font-weight:600;">Atmospheric calibration</div>',
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
        st.markdown(
            f"""
            <div style="
                background:
                    color-mix(
                        in srgb,
                        {_theme["accent"]} 8%,
                        {_theme["bg-panel"]}
                    );
                border-left: 3px solid {_theme["accent"]};
                color: {_theme["text-body"]};
                padding: 10px 12px;
                border-radius: 6px;
                margin-top: 8px;
                line-height: 1.4;
                font-size: 0.90rem;
            ">
                Load a spectrum before running atmospheric calibration.
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif atmospheric_error is not None:
        st.error(f"Atmospheric calibration could not be completed: {atmospheric_error}")


# PSS calibration

with st.container(border=True):
    st.markdown(
        '<div class="hs-panel-title" style="font-size:0.92rem; font-weight:600;">PSS calibration</div>',
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
        st.markdown(
            f"""
            <div style="
                background:
                    color-mix(
                        in srgb,
                        {_theme["accent"]} 8%,
                        {_theme["bg-panel"]}
                    );
                border-left: 3px solid {_theme["accent"]};
                color: {_theme["text-body"]};
                padding: 10px 12px;
                border-radius: 6px;
                margin-top: 8px;
                line-height: 1.4;
                font-size: 0.90rem;
            ">
                Load a spectrum to view PSS calibration history.
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif pss_error is not None:
        st.error(f"PSS calibration history could not be loaded: {pss_error}")

    pss_fig = go.Figure()

    if pss_history is not None and pss_window is not None:
        pss_fig.add_trace(
            go.Scatter(
                x=pss_history["lcp"]["mjd"],
                y=pss_history["lcp"]["pss"],
                mode="markers",
                name="LCP",
                marker=dict(
                    color=styles.LCP_COLOR,
                    size=7,
                    opacity=0.85,
                ),
                hovertemplate="MJD %{x:.3f}<br>LCP PSS %{y:.4f}<extra></extra>",
            )
        )

        pss_fig.add_trace(
            go.Scatter(
                x=pss_history["rcp"]["mjd"],
                y=pss_history["rcp"]["pss"],
                mode="markers",
                name="RCP",
                marker=dict(
                    color=styles.RCP_COLOR,
                    size=7,
                    opacity=0.85,
                ),
                hovertemplate="MJD %{x:.3f}<br>RCP PSS %{y:.4f}<extra></extra>",
            )
        )

        pss_fig.add_vrect(
            x0=pss_window["start_mjd"],
            x1=pss_window["end_mjd"],
            fillcolor=_theme["accent"],
            opacity=0.10,
            line_width=0,
            layer="below",
            annotation_text="±15 day window",
            annotation_position="top left",
            annotation_font_color=_theme["text-muted"],
        )

        pss_fig.add_vline(
            x=pss_window["observation_mjd"],
            line_dash="dash",
            line_color=_theme["text-muted"],
            annotation_text="Observation",
            annotation_position="top",
            annotation_font_color=_theme["text-muted"],
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
                showgrid=True,
                gridcolor=_theme["border-subtle"],
                linecolor=_theme["border-subtle"],
                tickfont=dict(color=_theme["text-body"]),
                title_font=dict(color=_theme["text-body"]),
                zeroline=False,
            ),
            yaxis=dict(
                title="PSS",
                showgrid=True,
                gridcolor=_theme["border-subtle"],
                linecolor=_theme["border-subtle"],
                tickfont=dict(color=_theme["text-body"]),
                title_font=dict(color=_theme["text-body"]),
                zeroline=False,
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
                font=dict(color=_theme["text-body"]),
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

    styles.render_plotly_chart(
        pss_fig,
        use_container_width=True,
        config={"displayModeBar": False},
    )

    st.markdown(
        '<div class="hs-panel-title" style="font-size:0.92rem; font-weight:600;">Previous 30-day PSS variability</div>',
        unsafe_allow_html=True,
    )

    variability_fig = go.Figure()
    variability_available = False

    if pss_30day_stats is not None:
        for label, key, color in (
            ("LCP", "lcp", styles.LCP_COLOR),
            ("RCP", "rcp", styles.RCP_COLOR),
        ):
            stats = pss_30day_stats[key]

            if stats["mean"] is None:
                continue

            variability_available = True
            std_value = stats["std"]
            std_text = (
                f"σ = {std_value:.4f}"
                if std_value is not None
                else "σ unavailable"
            )

            error_kwargs = {
                "type": "data",
                "array": [std_value if std_value is not None else 0.0],
                "visible": std_value is not None,
                "color": color,
                "thickness": 1.6,
                "width": 6,
            }

            variability_fig.add_trace(
                go.Scatter(
                    x=[label],
                    y=[stats["mean"]],
                    mode="markers+text",
                    name=label,
                    marker=dict(
                        color=color,
                        size=10,
                    ),
                    error_y=error_kwargs,
                    text=[std_text],
                    textposition="top center",
                    textfont=dict(color=_theme["text-body"]),
                    hovertemplate=(
                        f"{label}<br>"
                        "30-day mean %{y:.4f}<br>"
                        + std_text
                        + f"<br>Measurements: {stats['count']}"
                        + "<extra></extra>"
                    ),
                )
            )

    if variability_available:
        variability_fig.update_layout(
            paper_bgcolor=_theme["bg-panel"],
            plot_bgcolor=_theme["bg-panel"],
            margin=dict(l=48, r=16, t=28, b=42),
            height=230,
            showlegend=False,
            xaxis=dict(
                showgrid=False,
                linecolor=_theme["border-subtle"],
                tickfont=dict(color=_theme["text-body"]),
                zeroline=False,
            ),
            yaxis=dict(
                title="PSS",
                showgrid=True,
                gridcolor=_theme["border-subtle"],
                linecolor=_theme["border-subtle"],
                tickfont=dict(color=_theme["text-body"]),
                title_font=dict(color=_theme["text-body"]),
                zeroline=False,
            ),
            font=dict(
                family="Inter, -apple-system, 'Segoe UI', sans-serif",
                size=11,
                color=_theme["text-body"],
            ),
        )

        styles.render_plotly_chart(
            variability_fig,
            use_container_width=True,
            config={"displayModeBar": False},
        )

        st.markdown(
            f"""
            <div style="
                color: {_theme["text-body"]};
                opacity: 0.78;
                font-size: 0.82rem;
                margin-top: 2px;
                margin-bottom: 4px;
            ">
                Error bars show ±1 sample standard deviation of the available
                PSS measurements from the 30 days preceding the observation.
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif loaded_spectrum is not None and pss_error is None:
        st.markdown(
            f"""
            <div style="
                color: {_theme["text-body"]};
                opacity: 0.78;
                font-size: 0.82rem;
                margin-top: 4px;
            ">
                Not enough historical PSS measurements are available in the
                previous 30 days to calculate variability.
            </div>
            """,
            unsafe_allow_html=True,
        )


def _record_polarization_change(message: str) -> None:
    """Send view-only FR-09 changes through the existing audit/checkpoint hooks."""
    session_store.log_event(message)
    session_store.checkpoint_session("Polarization display settings recorded")


# TODO: confirm against design — FR-09 was absent from the original mockups.
# Keep the eight-stage navigation: this reusable panel is part of Page 05.
_polarization_input = None
_polarization_source = "baseline"
_polarization_label = "Baseline-flattened spectrum (Stage 04; calibration not yet applied)"
_polarization_unit = UNCALIBRATED_UNIT
if baseline_ready:
    _polarization_input = st.session_state.get("baseline_corrected_spectrum")
    if (
        PAGE_STAGE_KEY in st.session_state["completed_stages"]
        and st.session_state.get("calibrated_spectrum") is not None
    ):
        _polarization_input = st.session_state["calibrated_spectrum"]
        _polarization_source = "calibrated"
        _polarization_label = "Calibrated spectrum (Stage 05 output)"
        _polarization_unit = CALIBRATED_UNIT

_polarization_rendered = render_polarization_panel(
    _polarization_input,
    source_key=_polarization_source,
    source_label=_polarization_label,
    intensity_unit=_polarization_unit,
    stage_key=PAGE_STAGE_KEY,
    on_change=_record_polarization_change,
)

# Headless FR-09 test doubles do not implement download widgets.
# Real Streamlit renders these exports; visualization tests remain unchanged.
if _polarization_rendered and callable(getattr(st, "download_button", None)):
    st.caption(
        "Export the unsmoothed LCP/RCP values shown in the graph above. "
        f"Source: {_polarization_label}. Displayed units: {_polarization_unit}. "
        "Export does not recalculate or change the spectrum."
    )
    _export_columns = st.columns(2)
    for _column, _polarization in zip(_export_columns, ("LCP", "RCP")):
        with _column:
            st.download_button(
                label=f"Export {_polarization} CSV",
                data=calibration_logic.polarization_trace_csv(
                    _polarization_input, _polarization, _polarization_unit,
                ),
                file_name=f"HartSpec_Page05_{_polarization}_display.csv",
                mime="text/csv",
                key=f"page05_export_{_polarization.lower()}",
                use_container_width=True,
            )

st.markdown(
    f"<div style='height:{styles.SECTION_GAP}px'></div>",
    unsafe_allow_html=True,
)

if st.button(
    "Continue to Pointing Correction →",
    type="primary",
    key="continue_to_pointing_correction",
):
    if PAGE_STAGE_KEY in st.session_state["completed_stages"]:
        st.switch_page("pages/06_Pointing_Correction.py")
    else:
        st.warning(
            "Complete the atmospheric and PSS calibration before continuing."
        )
