# feature_detection_ui.py — FR-08: Plotly overlay and feature-detection log for Page 04.
"""Presentation helpers for the read-only FR-08 detector."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import styles
from utils.feature_detection_logic import FeatureDetectionError, FeatureDetectionResult, detect_features, event_rows


def build_feature_figure(result: FeatureDetectionResult, theme: Mapping[str, str]) -> go.Figure:
    """Build the LCP/RCP spectrum overlay with changed channels accentuated."""
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=result.vlsr,
            y=result.channels["LCP"],
            mode="lines",
            name="LCP",
            line=dict(color=styles.LCP_COLOR, width=1.4),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=result.vlsr,
            y=result.channels["RCP"],
            mode="lines",
            name="RCP",
            line=dict(color=styles.RCP_COLOR, width=1.4),
        )
    )

    appeared_color = styles.FIT_LINE_COLOR[styles.get_theme_name()]
    disappeared_color = theme["accent"]
    for polarization in ("LCP", "RCP"):
        detection = result.detections[polarization]
        for label, indices, color, symbol in (
            ("Appeared", detection.appeared_indices, appeared_color, "diamond-open"),
            ("Disappeared", detection.disappeared_indices, disappeared_color, "x"),
        ):
            if not indices.size:
                continue
            figure.add_trace(
                go.Scatter(
                    x=result.vlsr[indices],
                    y=result.channels[polarization][indices],
                    mode="markers",
                    name=f"{polarization} {label.lower()}",
                    marker=dict(color=color, symbol=symbol, size=9, line=dict(width=1.5, color=color)),
                    hovertemplate=(
                        f"{polarization} {label}<br>Vlsr=%{{x:.3f}} km/s"
                        "<br>Amplitude=%{y:.6g}<extra></extra>"
                    ),
                )
            )

    figure.update_layout(**styles.plotly_layout_theme(dict(theme)))
    figure.update_layout(
        height=330,
        margin=dict(l=50, r=20, t=15, b=45),
        hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(title="Vlsr (km/s)"),
        yaxis=dict(title="Baseline-flattened intensity"),
    )
    return figure


def render_feature_detection(
    spectrum: Mapping[str, Any],
    blocks: Sequence[Mapping[str, float]],
) -> bool:
    """Render the FR-08 overlay and log; return True when detection ran successfully."""
    theme = styles.get_theme()
    st.markdown('<div class="hs-eyebrow">Sigma-clipping feature detection</div>', unsafe_allow_html=True)
    st.caption(
        "Detection follows the supplied CLC Add_Remove_feature thresholds on the committed baseline-flattened "
        "LCP/RCP spectra. The review uses private mask copies; it does not edit your baseline regions "
        "or downstream data."
    )

    try:
        result = detect_features(spectrum, blocks)
    except FeatureDetectionError as exc:
        st.error(f"Feature detection could not run: {exc}")
        return False

    styles.render_plotly_chart(
        build_feature_figure(result, theme),
        use_container_width=True,
        config={"displayModeBar": True},
        theme=None,
    )

    lcp = result.detections["LCP"]
    rcp = result.detections["RCP"]
    st.caption(
        f"Baseline envelope: {result.vll:.3f} to {result.vrl:.3f} km/s · "
        f"LCP RMS {lcp.initial_rms:.6g} → {lcp.final_rms:.6g} · "
        f"RCP RMS {rcp.initial_rms:.6g} → {rcp.final_rms:.6g}."
    )

    rows = event_rows(result)
    if rows:
        frame = pd.DataFrame(rows)
        styles.render_dataframe(frame, use_container_width=True, height=min(260, 32 + 28 * len(frame)))
    else:
        st.info("No appeared or disappeared feature channels were detected by the supplied CLC thresholds.")

    st.caption(
        "Appeared = a selected baseline channel changed from included to excluded at the CLC ≥2.5× initial-RMS "
        "threshold. Disappeared follows the supplied ≤1.2× initial-RMS mask rule. Contiguous changed channels are "
        "grouped into one log row for readability."
    )
    return True
