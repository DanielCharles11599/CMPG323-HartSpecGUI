# polarization_panel.py — FR-09: reusable Streamlit polarization overlay panel.
"""Presentation only: persist view controls, never publish smoothed pipeline data."""
from __future__ import annotations

from typing import Any, Callable, Mapping

import plotly.graph_objects as go
import streamlit as st

from utils import styles
from utils.polarization_logic import (
    MIN_WINDOW,
    SETTINGS_KEY,
    PolarizationIntegrationError,
    PolarizationOverlay,
    build_polarization_overlay,
    display_record,
    restore_display_settings,
    spectrum_identity,
    validated_spectrum,
    validate_window,
)


def build_overlay_figure(
    overlay: PolarizationOverlay, *, intensity_unit: str, theme: dict[str, str], revision: str,
) -> go.Figure:
    """Build the four themed Plotly traces, retaining zoom for display-only edits.

    Args:
        overlay: Independent display arrays from the FR-09 adapter.
        intensity_unit: Existing pipeline unit label (K or Jy).
        theme: Shared light/dark tokens, never a page-local color palette.
        revision: Identity of the source arrays and units, not filter settings.
    Returns:
        An interactive four-trace figure with a clickable legend.
    """
    figure = go.Figure()
    for label, values, color, dash, width in (
        ("LCP", overlay.lcp, styles.LCP_COLOR, "solid", 1.3),
        ("RCP", overlay.rcp, styles.RCP_COLOR, "solid", 1.3),
        ("Mean", overlay.mean, styles.MEAN_COLOR, "dot", 1.8),
        ("Stokes I", overlay.stokes_i, styles.STOKES_I_COLOR, "solid", 1.8),
    ):
        figure.add_trace(go.Scatter(
            x=overlay.vlsr, y=values, name=label, uid=label, mode="lines",
            line=dict(color=color, dash=dash, width=width), connectgaps=False,
            hovertemplate=f"{label}<br>Vlsr %{{x:.4f}} km/s<br>%{{y:.6g}} {intensity_unit}<extra></extra>",
        ))
    figure.update_layout(**styles.plotly_layout_theme(theme))
    figure.update_layout(
        height=380, margin=dict(l=60, r=20, t=16, b=80), uirevision=revision,
        hovermode="x unified", dragmode="zoom",
        xaxis=dict(title="Vlsr (km/s)", showline=True),
        yaxis=dict(title=f"Intensity ({intensity_unit})", showline=True),
        legend=dict(orientation="h", x=0, y=-0.22, xanchor="left", yanchor="top"),
    )
    return figure


def _on_controls_changed(
    stage_key: str, prefix: str, session_id: str, fingerprint: str,
    n_channels: int, on_change: Callable[[str], None] | None,
) -> None:
    """Persist controls before a rerun so widget cleanup cannot erase preferences.

    A stale callback must not modify a different loaded session or spectrum.
    Invalid typed windows leave the previous valid record intact and report why.
    """
    state = st.session_state
    pipeline = state.get("pipeline_data", {})
    stage = pipeline.get(stage_key, {}) if isinstance(pipeline, dict) else {}
    record = stage.get(SETTINGS_KEY) if isinstance(stage, dict) else None
    if state.get("session_id", "") != session_id or not isinstance(record, dict):
        return
    if record.get("source_fingerprint") != fingerprint:
        return
    enabled = bool(state[f"{prefix}_smooth"])
    try:
        window = validate_window(state[f"{prefix}_window"], n_channels, smoothing_enabled=enabled)
    except ValueError as exc:
        state[f"{prefix}_error"] = str(exc)
        return
    updated = dict(record, smoothing_enabled=enabled, window_length=window)
    if updated != record:
        stage[SETTINGS_KEY] = updated
        if on_change is not None:
            on_change(
                f"Polarisation view changed — Stokes I smoothing {'on' if enabled else 'off'}, "
                f"window {window}, order 3; pipeline spectra unchanged"
            )


def render_polarization_panel(
    spectrum: Mapping[str, Any] | None, *, source_key: str, source_label: str,
    intensity_unit: str, stage_key: str = "05_calibration_dashboard",
    key_prefix: str = "calibration_polarization", on_change: Callable[[str], None] | None = None,
) -> bool:
    """Render FR-09 inside an existing page and save only nested view metadata.

    Args:
        spectrum: Explicit real pipeline input; None renders guidance, not demo data.
        source_key/source_label: Machine-readable and visible input provenance.
        intensity_unit: The selected pipeline input's existing unit convention.
        stage_key: Owner of pipeline_data[stage_key]['polarization_display'].
        key_prefix: Page-owned temporary widgets (cleared by existing invalidation).
        on_change: Optional audit/checkpoint hook taking a human-readable message.
    Returns:
        True if an overlay was rendered, False for empty or invalid inputs.
    """
    with st.container(border=True):
        st.markdown('<div class="hs-panel-title">Polarisation averaging</div>', unsafe_allow_html=True)
        if spectrum is None:
            st.info("Complete the Baseline Block Editor to view LCP, RCP, mean and Stokes I. No demo data is shown.")
            return False
        try:
            arrays = validated_spectrum(spectrum)
            fingerprint = spectrum_identity(arrays)
        except ValueError as exc:
            st.error(f"Polarization overlay unavailable: {exc}")
            return False

        state = st.session_state
        pipeline = state.setdefault("pipeline_data", {})
        if not isinstance(pipeline, dict):
            st.error("Polarization overlay unavailable: saved pipeline data is malformed. Load a valid session.")
            return False
        stage = pipeline.setdefault(stage_key, {})
        if not isinstance(stage, dict):
            st.error("Polarization overlay unavailable: the saved owning stage is malformed. Revisit its input stage.")
            return False
        saved = stage.get(SETTINGS_KEY)
        settings, notices = restore_display_settings(saved, arrays["Vlsr"].size)
        for notice in notices:
            st.warning(notice)
        error = state.pop(f"{key_prefix}_error", None)
        if error:
            st.error(error)
        st.caption(f"Input: {source_label} · {arrays['Vlsr'].size} channels · {intensity_unit}")
        st.caption("Mean = (LCP + RCP) / 2. Stokes I = LCP + RCP, following Pols.py.")

        # The JSON record is authoritative on every render, including same-ID
        # session loads. Callbacks save edits there before these keys are seeded.
        state[f"{key_prefix}_smooth"] = settings["smoothing_enabled"]
        state[f"{key_prefix}_window"] = settings["window_length"]
        can_smooth = arrays["Vlsr"].size >= MIN_WINDOW
        maximum = arrays["Vlsr"].size - (arrays["Vlsr"].size % 2 == 0)
        callback_args = (
            stage_key, key_prefix, state.get("session_id", ""), fingerprint,
            arrays["Vlsr"].size, on_change,
        )
        controls = st.columns([2, 1])
        with controls[0]:
            enabled = st.toggle(
                "Savitzky–Golay smoothing (Stokes I)", key=f"{key_prefix}_smooth", disabled=not can_smooth,
                help="Display only. LCP, RCP and mean remain unsmoothed. Fitting and exports are not changed.",
                on_change=_on_controls_changed, args=callback_args,
            )
        with controls[1]:
            window = st.number_input(
                "Window length (channels)", min_value=MIN_WINDOW, max_value=max(MIN_WINDOW, int(maximum)),
                step=2, key=f"{key_prefix}_window", disabled=not can_smooth or not enabled,
                help="Centered odd window, at least 5. Polynomial order is fixed at 3; CLC default window is 7.",
                on_change=_on_controls_changed, args=callback_args,
            )
        if not can_smooth:
            st.caption("Smoothing needs at least 5 channels. The unsmoothed overlay remains available.")
        try:
            overlay = build_polarization_overlay(arrays, smoothing_enabled=enabled, window_length=window)
        except (ValueError, PolarizationIntegrationError) as exc:
            st.error(f"Polarization overlay unavailable: {exc}")
            return False

        figure = build_overlay_figure(
            overlay, intensity_unit=intensity_unit, theme=styles.get_theme(),
            revision=f"{state.get('session_id', '')}:{source_key}:{fingerprint}:{intensity_unit}",
        )
        styles.render_plotly_chart(
            figure, use_container_width=True, theme=None,
            config={"displaylogo": False, "displayModeBar": True, "scrollZoom": True},
        )
        status = f"Stokes I: SG window {window}, polynomial order 3." if enabled else "Smoothing is off."
        st.caption(
            f"{status} LCP, RCP and mean are unsmoothed references. "
            "These controls do not alter calibration, fitting or exported data. "
            "Click legend entries to hide/show traces."
        )
        record = display_record(
            {"smoothing_enabled": enabled, "window_length": window}, source_key=source_key,
            fingerprint=fingerprint, intensity_unit=intensity_unit,
        )
        if saved != record:
            stage[SETTINGS_KEY] = record
            if on_change is not None:
                on_change(
                    f"Polarisation view recorded — {source_label}; Stokes I smoothing {'on' if enabled else 'off'}, "
                    f"window {window}, order 3; pipeline spectra unchanged"
                )
        return True
