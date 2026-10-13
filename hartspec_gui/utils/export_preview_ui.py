# export_preview_ui.py — FR-18: render the calibrated LCP/RCP RMS + peak preview on Page 08.
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from utils import styles
from utils.export_preview_logic import ExportPreviewResult


def render_export_preview(result: ExportPreviewResult, theme: dict[str, str], height: int = 300) -> None:
    """Render source-faithful CLC RMS/peak information without changing any export/session state."""
    if not result.available:
        st.caption("FR-18 RMS / peak preview unavailable: " + (result.reason or "required inputs are missing."))
        return

    stats = result.stats
    assert stats is not None
    styles.render_panel_open("Final calibrated LCP/RCP preview — CLC RMS and peak")
    fig = go.Figure()
    fig.add_scatter(
        x=stats.vlsr, y=stats.lcp_jy, mode="lines", name="LCP (CLC calibration path)",
        line=dict(color=styles.LCP_COLOR, width=1.6),
    )
    fig.add_scatter(
        x=stats.vlsr, y=stats.rcp_jy, mode="lines", name="RCP (CLC calibration path)",
        line=dict(color=styles.RCP_COLOR, width=1.6),
    )
    x_limits = [float(stats.vlsr[0]), float(stats.vlsr[-1])]
    for value, label in ((stats.rms_jy, "+RMS"), (-stats.rms_jy, "−RMS")):
        fig.add_scatter(
            x=x_limits, y=[value, value], mode="lines", name=f"{label} ({abs(value):.3f} Jy)",
            line=dict(color=theme["text-muted"], width=1.0, dash="dot"), hoverinfo="skip",
        )
    fig.add_scatter(
        x=[stats.peak_velocity_kms], y=[stats.peak_jy], mode="markers+text", name="Stokes I peak",
        marker=dict(size=9, color=theme["accent"], symbol="diamond"),
        text=[f"Stokes I max {stats.peak_jy:.3f} Jy"], textposition="top center",
        hovertemplate=(
            "Stokes I peak<br>Vlsr=%{x:.3f} km/s<br>Flux=%{y:.3f} Jy<extra></extra>"
        ),
    )
    fig.update_layout(**styles.plotly_layout_theme(theme))
    fig.update_layout(
        height=height,
        margin=dict(l=40, r=20, t=16, b=48),
        paper_bgcolor=theme["bg-panel"],
        plot_bgcolor=theme["bg-panel"],
        legend=dict(orientation="h", y=-0.27),
        xaxis=dict(title="Vlsr (km/s)", showgrid=False, zeroline=False, color=theme["text-muted"]),
        yaxis=dict(title="Flux density (Jy)", showgrid=False, zeroline=False, color=theme["text-muted"]),
    )
    fig.update_annotations(font=dict(color=theme["text-body"]))
    styles.render_plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, theme=None)
    st.caption(
        "RMS and maximum follow the legacy CLC final-spectrum path and are Stokes I statistics. "
        "LCP/RCP are shown after the same pointing × per-polarisation PSS calibration. "
        f"Envelope: {stats.vll:.3f} to {stats.vrl:.3f} km/s · "
        f"RMS {stats.rms_jy:.3f} Jy · Stokes I max {stats.peak_jy:.3f} Jy at "
        f"{stats.peak_velocity_kms:.3f} km/s."
    )
    styles.render_panel_close()
