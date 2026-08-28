# 03_Bandpass_Correction.py — FR-04: mode selector + bandpass-corrected spectrum overlay.
#
# This page consumes the real spectra loaded by Page 02 through
# utils.bandpass_correction_logic, validates the corrected result, stores an
# explicit in-memory Page 3 -> Page 4 spectrum handoff, and only then marks
# FR-04 complete. The compact session JSON still stores summary metadata only.

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from utils import session_store, sidebar, styles
from utils.bandpass_correction_logic import (
    MODE_OPTIONS,
    THIS_STAGE_KEY,
    get_corrected_spectrum,
    stage_summary,
)

PAGE_STAGE_KEY = THIS_STAGE_KEY
CURRENT_STAGE = 3
PAGE_TITLE = "Bandpass Correction"
PAGE_SUBTITLE = "FR-04 — mode selector + spectrum overlay"
CHART_PANEL_TITLE = "Bandpass-corrected spectrum"

# Exact stage keys already used by Pages 01/02 in the supplied project.
UPSTREAM_STAGE_KEYS = ("01_source_browser", "file_loader")
DOWNSTREAM_BASELINE_STAGE_KEY = "04_baseline_editor"

_FREQ_SWITCH_PILL_WIDTH_PX = 180
_POS_SWITCH_PILL_WIDTH_PX = 180
_REQUIRED_ARRAY_KEYS = ("Vlsr", "LCP", "RCP")


st.set_page_config(
    page_title="HARTSPEC — Bandpass Correction",
    layout="wide",
    initial_sidebar_state="expanded",
)

session_store.init_session_state()
sidebar.render_sidebar(current_stage=CURRENT_STAGE)
styles.inject_base_css()


def _init_page_state() -> None:
    """Initialize Page 3 working state without overwriting an existing selection."""
    st.session_state.setdefault("bandpass_mode", MODE_OPTIONS[0])
    st.session_state.setdefault("bandpass_last_logged_mode", None)


_init_page_state()


def _on_mode_select(mode: str) -> None:
    """Store the selected FR-04 switching mode for the next Streamlit rerun."""
    st.session_state["bandpass_mode"] = mode


def _completed_upstream_count() -> int:
    """Count only stages strictly before Page 3 for the shared progress bar."""
    completed = st.session_state["completed_stages"]
    return sum(stage_key in completed for stage_key in UPSTREAM_STAGE_KEYS)


def _normalise_corrected_spectrum(corrected: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """Validate and copy the three arrays Page 4 requires.

    Raises:
        ValueError: If Vlsr/LCP/RCP is missing, empty, non-numeric, or the
            three arrays have inconsistent lengths.
    """
    arrays: dict[str, np.ndarray] = {}

    for key in _REQUIRED_ARRAY_KEYS:
        if key not in corrected:
            raise ValueError(f"Bandpass output is missing required field: {key}.")
        try:
            array = np.asarray(corrected[key], dtype=float).reshape(-1)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Bandpass output field {key} is not a numeric array.") from exc

        if array.size == 0:
            raise ValueError(
                "Bandpass correction produced zero output channels. "
                "Check that the two Page 2 spectra form the correct switching pair and share the velocity channels "
                "required by the selected mode."
            )
        arrays[key] = array.copy()

    lengths = {key: arrays[key].size for key in _REQUIRED_ARRAY_KEYS}
    if len(set(lengths.values())) != 1:
        raise ValueError(
            "Bandpass output arrays have inconsistent lengths: "
            + ", ".join(f"{key}={size}" for key, size in lengths.items())
        )

    return arrays


def _spectra_equal(left: Mapping[str, Any] | None, right: Mapping[str, Any]) -> bool:
    """Return True when two Page 3 handoff spectra contain identical arrays."""
    if not left:
        return False

    try:
        return all(
            np.array_equal(
                np.asarray(left[key], dtype=float),
                np.asarray(right[key], dtype=float),
                equal_nan=True,
            )
            for key in _REQUIRED_ARRAY_KEYS
        )
    except (KeyError, TypeError, ValueError):
        return False


def _invalidate_page4_if_upstream_changed(new_handoff: Mapping[str, Any]) -> None:
    """Invalidate a stale baseline fit when Page 3's scientific input changes."""
    previous = st.session_state.get("bandpass_corrected_spectrum")
    if previous is None or _spectra_equal(previous, new_handoff):
        return

    st.session_state["completed_stages"].discard(DOWNSTREAM_BASELINE_STAGE_KEY)
    st.session_state["pipeline_data"].pop(DOWNSTREAM_BASELINE_STAGE_KEY, None)
    st.session_state.pop("baseline_corrected_spectrum", None)
    session_store.log_event("Bandpass output changed — Baseline Block Editor state invalidated")


_theme = styles.get_theme()

st.markdown(
    f"""
    <style>
    .hs-legend-row {{
        display: flex;
        align-items: center;
        gap: 24px;
        margin-top: 10px;
    }}
    .hs-legend-item {{
        display: flex;
        align-items: center;
        gap: 8px;
    }}
    .hs-legend-swatch {{
        width: 10px;
        height: 10px;
        border-radius: 2px;
        display: inline-block;
    }}
    .hs-legend-label {{
        font-size: 9px;
        color: {_theme['text-muted']};
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# The current stage is in progress, so only Pages 1 and 2 may contribute to
# the Page 3 header progress value.
styles.render_page_header(
    title=PAGE_TITLE,
    subtitle=PAGE_SUBTITLE,
    current_stage=CURRENT_STAGE,
    completed_stages=_completed_upstream_count(),
)


st.markdown('<div class="hs-eyebrow">Mode</div>', unsafe_allow_html=True)

_remaining_width = (
    styles.CONTENT_WIDTH
    - _FREQ_SWITCH_PILL_WIDTH_PX
    - _POS_SWITCH_PILL_WIDTH_PX
)
mode_cols = st.columns(
    [
        _FREQ_SWITCH_PILL_WIDTH_PX,
        _POS_SWITCH_PILL_WIDTH_PX,
        _remaining_width,
    ]
)

active_mode = st.session_state["bandpass_mode"]

with mode_cols[0]:
    st.button(
        "Frequency Switch",
        key="mode_freq_switch",
        type="primary" if active_mode == "Frequency Switch" else "secondary",
        use_container_width=True,
        on_click=_on_mode_select,
        args=("Frequency Switch",),
    )

with mode_cols[1]:
    st.button(
        "Position Switch",
        key="mode_pos_switch",
        type="primary" if active_mode == "Position Switch" else "secondary",
        use_container_width=True,
        on_click=_on_mode_select,
        args=("Position Switch",),
    )

st.write("")


mode = st.session_state["bandpass_mode"]

try:
    corrected = get_corrected_spectrum(mode)
    handoff_spectrum = _normalise_corrected_spectrum(corrected)
except (ValueError, TypeError, KeyError) as exc:
    # Do not leave stale success state behind if the current correction fails.
    st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)
    st.session_state["pipeline_data"].pop(PAGE_STAGE_KEY, None)
    st.session_state.pop("bandpass_corrected_spectrum", None)
    st.error(str(exc))
    st.stop()

# Page 4 must consume exactly the spectrum the user sees here. Keep the arrays
# out of pipeline_data because session_store serializes that dict to JSON.
_invalidate_page4_if_upstream_changed(handoff_spectrum)
st.session_state["bandpass_corrected_spectrum"] = handoff_spectrum


with st.container(border=True):
    st.markdown(
        f'<div class="hs-panel-title">{CHART_PANEL_TITLE}</div>',
        unsafe_allow_html=True,
    )

    fig = go.Figure()
    fig.add_scatter(
        x=handoff_spectrum["Vlsr"],
        y=handoff_spectrum["LCP"],
        mode="lines",
        line=dict(color=styles.LCP_COLOR, width=1.6),
        name="LCP",
        hovertemplate="Vlsr=%{x:.2f} km/s<br>LCP=%{y:.3f} K<extra></extra>",
    )
    fig.add_scatter(
        x=handoff_spectrum["Vlsr"],
        y=handoff_spectrum["RCP"],
        mode="lines",
        line=dict(color=styles.RCP_COLOR, width=1.6),
        name="RCP",
        hovertemplate="Vlsr=%{x:.2f} km/s<br>RCP=%{y:.3f} K<extra></extra>",
    )
    fig.update_layout(
        showlegend=False,
        paper_bgcolor=_theme["bg-panel"],
        plot_bgcolor=_theme["bg-panel"],
        margin=dict(l=48, r=16, t=8, b=40),
        height=384,
        xaxis=dict(
            title="Vlsr (km/s)",
            showgrid=False,
            zeroline=False,
            showline=True,
            linecolor=_theme["border-subtle"],
            color=_theme["text-muted"],
        ),
        yaxis=dict(
            title="Tsys (K)",
            showgrid=False,
            zeroline=False,
            showline=True,
            linecolor=_theme["border-subtle"],
            color=_theme["text-muted"],
        ),
        font=dict(
            family="Inter, -apple-system, 'Segoe UI', sans-serif",
            size=11,
            color=_theme["text-body"],
        ),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown(
        f"""
        <div class="hs-legend-row">
          <div class="hs-legend-item">
            <span class="hs-legend-swatch" style="background-color:{styles.LCP_COLOR};"></span>
            <span class="hs-legend-label">LCP</span>
          </div>
          <div class="hs-legend-item">
            <span class="hs-legend-swatch" style="background-color:{styles.RCP_COLOR};"></span>
            <span class="hs-legend-label">RCP</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# FR-04 is complete only after a real, non-empty corrected spectrum has been
# produced and handed to the next stage.
st.session_state["pipeline_data"][PAGE_STAGE_KEY] = stage_summary(mode, corrected)
session_store.mark_stage_complete(PAGE_STAGE_KEY)

if st.session_state["bandpass_last_logged_mode"] != mode:
    session_store.log_event(
        f"Bandpass correction applied — {mode} "
        f"({handoff_spectrum['Vlsr'].size} channels)"
    )
    st.session_state["bandpass_last_logged_mode"] = mode
