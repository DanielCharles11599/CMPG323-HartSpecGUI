from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from utils import session_store, sidebar, styles
from utils.bandpass_correction_logic import (
    MODE_OPTIONS,
    THIS_STAGE_KEY,
    build_bandpass_result,
    get_full_integration_pairs,
    stage_summary,
    suggest_mode,
)

PAGE_STAGE_KEY = THIS_STAGE_KEY
CURRENT_STAGE = 3
PAGE_TITLE = "Bandpass Correction"
PAGE_SUBTITLE = "FR-04 — mode selector + before/after spectrum overlay"
UPSTREAM_STAGE_KEYS = ("01_source_browser", "file_loader")
DOWNSTREAM_STAGE_KEYS = ("04_baseline_editor",)
_REQUIRED_ARRAY_KEYS = ("Vlsr", "LCP", "RCP")

st.set_page_config(
    page_title="HARTSPEC — Bandpass Correction",
    layout="wide",
    initial_sidebar_state="expanded",
)

session_store.init_session_state()
sidebar.render_sidebar(current_stage=CURRENT_STAGE)
styles.inject_base_css()


def _completed_upstream_count() -> int:
    completed = st.session_state["completed_stages"]
    return sum(key in completed for key in UPSTREAM_STAGE_KEYS)


def _upstream_complete() -> bool:
    completed = st.session_state["completed_stages"]
    return all(key in completed for key in UPSTREAM_STAGE_KEYS)


def _normalise_spectrum(spectrum: Mapping[str, Any], label: str) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    for key in _REQUIRED_ARRAY_KEYS:
        if key not in spectrum:
            raise ValueError(f"{label} is missing required field: {key}.")
        try:
            array = np.asarray(spectrum[key], dtype=float).reshape(-1)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} field {key} is not numeric.") from exc
        if array.size == 0:
            raise ValueError(f"{label} contains no {key} channels.")
        if not np.all(np.isfinite(array)):
            raise ValueError(f"{label} field {key} contains NaN or infinite values.")
        arrays[key] = array.copy()

    lengths = {key: arrays[key].size for key in _REQUIRED_ARRAY_KEYS}
    if len(set(lengths.values())) != 1:
        raise ValueError(
            f"{label} arrays have inconsistent lengths: "
            + ", ".join(f"{key}={size}" for key, size in lengths.items())
        )
    return arrays


def _spectra_equal(left: Mapping[str, Any] | None, right: Mapping[str, Any]) -> bool:
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


def _clear_stage3_and_downstream() -> None:
    st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)
    st.session_state["pipeline_data"].pop(PAGE_STAGE_KEY, None)
    st.session_state.pop("bandpass_corrected_spectrum", None)
    st.session_state.pop("bandpass_display_result", None)
    st.session_state.pop("bandpass_applied_mode", None)

    for key in DOWNSTREAM_STAGE_KEYS:
        st.session_state["completed_stages"].discard(key)
        st.session_state["pipeline_data"].pop(key, None)
    st.session_state.pop("baseline_corrected_spectrum", None)


def _on_mode_change() -> None:
    applied = st.session_state.get("bandpass_applied_mode")
    selected = st.session_state.get("bandpass_mode")
    if applied and selected != applied:
        _clear_stage3_and_downstream()


def _commit_result(result: Mapping[str, Any]) -> None:
    mode = str(result["mode"])
    corrected = _normalise_spectrum(result["corrected"], "Bandpass-corrected spectrum")
    previous = st.session_state.get("bandpass_corrected_spectrum")

    if previous is not None and not _spectra_equal(previous, corrected):
        for key in DOWNSTREAM_STAGE_KEYS:
            st.session_state["completed_stages"].discard(key)
            st.session_state["pipeline_data"].pop(key, None)
        st.session_state.pop("baseline_corrected_spectrum", None)
        session_store.log_event("Bandpass output changed — Baseline Block Editor state invalidated")

    st.session_state["bandpass_corrected_spectrum"] = corrected
    st.session_state["bandpass_display_result"] = {
        "mode": mode,
        "raw_spec1": _normalise_spectrum(result["raw_spec1"], "Input spectrum 1"),
        "raw_spec2": _normalise_spectrum(result["raw_spec2"], "Input spectrum 2"),
        "corrected": corrected,
        "filename1": str(result["filename1"]),
        "filename2": str(result["filename2"]),
        "common_velocity_range_kms": list(result.get("common_velocity_range_kms") or []),
    }
    st.session_state["bandpass_applied_mode"] = mode

    summary = stage_summary(mode, corrected)
    summary["filename1"] = str(result["filename1"])
    summary["filename2"] = str(result["filename2"])
    summary["common_velocity_range_kms"] = list(result.get("common_velocity_range_kms") or [])
    st.session_state["pipeline_data"][PAGE_STAGE_KEY] = summary
    session_store.mark_stage_complete(PAGE_STAGE_KEY)
    session_store.log_event(
        f"Bandpass correction applied — {mode} "
        f"({corrected['Vlsr'].size} channels)"
    )


def _render_pair_info(pair: tuple[dict[str, Any], dict[str, Any]], pair_number: int, total_pairs: int) -> None:
    first, second = pair
    suggested, reason = suggest_mode(pair)
    suggestion = suggested if suggested else "Unable to determine automatically"

    st.markdown('<div class="hs-eyebrow">Detected full-integration pair</div>', unsafe_allow_html=True)
    with st.container(border=True):
        cols = st.columns([1, 1, 1.25])
        with cols[0]:
            st.markdown("**File 1**")
            st.caption(first["filename"])
        with cols[1]:
            st.markdown("**File 2**")
            st.caption(second["filename"])
        with cols[2]:
            st.markdown("**CLC mode suggestion**")
            st.caption(f"{suggestion} — {reason}")

        if total_pairs > 1:
            st.caption(
                f"Pair {pair_number} of {total_pairs}. Pairs are formed from SPPOINT = 0 files in observation order, "
                "matching the original HartSpec workflow."
            )
        else:
            st.caption(
                "This pair was formed from the SPPOINT = 0 full integrations, matching the original HartSpec workflow."
            )


def _add_before_after(fig: go.Figure, row: int, col: int, raw_x, raw_y, corrected_x, corrected_y, label: str, color: str) -> None:
    fig.add_trace(
        go.Scatter(
            x=raw_x,
            y=raw_y,
            mode="lines",
            name=f"Before {label}",
            legendgroup=label,
            line=dict(color=color, width=1.4, dash="dot"),
            opacity=0.55,
            hovertemplate=f"Before {label}<br>Vlsr=%{{x:.2f}} km/s<br>T=%{{y:.3f}} K<extra></extra>",
        ),
        row=row,
        col=col,
    )
    fig.add_trace(
        go.Scatter(
            x=corrected_x,
            y=corrected_y,
            mode="lines",
            name=f"After {label}",
            legendgroup=label,
            line=dict(color=color, width=1.7),
            hovertemplate=f"After {label}<br>Vlsr=%{{x:.2f}} km/s<br>T=%{{y:.3f}} K<extra></extra>",
        ),
        row=row,
        col=col,
    )


def _render_before_after(result: Mapping[str, Any]) -> None:
    theme = styles.get_theme()
    raw = result["raw_spec1"]
    corrected = result["corrected"]
    common_range = result.get("common_velocity_range_kms") or []

    with st.container(border=True):
        st.markdown(
            '<div class="hs-panel-title">Before / after bandpass correction</div>',
            unsafe_allow_html=True,
        )

        fig = make_subplots(
            rows=1,
            cols=2,
            subplot_titles=("LCP", "RCP"),
            horizontal_spacing=0.08,
        )

        _add_before_after(
            fig, 1, 1,
            raw["Vlsr"], raw["LCP"],
            corrected["Vlsr"], corrected["LCP"],
            "LCP", styles.LCP_COLOR,
        )
        _add_before_after(
            fig, 1, 2,
            raw["Vlsr"], raw["RCP"],
            corrected["Vlsr"], corrected["RCP"],
            "RCP", styles.RCP_COLOR,
        )

        if len(common_range) == 2:
            for column in (1, 2):
                fig.add_vrect(
                    x0=common_range[0],
                    x1=common_range[1],
                    fillcolor=theme["accent"],
                    opacity=0.08,
                    line_width=0,
                    row=1,
                    col=column,
                )

        fig.update_layout(
            paper_bgcolor=theme["bg-panel"],
            plot_bgcolor=theme["bg-panel"],
            height=430,
            margin=dict(l=50, r=18, t=48, b=48),
            hovermode="x unified",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
            ),
            font=dict(
                family="Inter, -apple-system, 'Segoe UI', sans-serif",
                size=11,
                color=theme["text-body"],
            ),
        )

        fig.update_xaxes(
            title_text="Vlsr (km/s)",
            showgrid=False,
            zeroline=False,
            showline=True,
            linecolor=theme["border-subtle"],
            color=theme["text-muted"],
            row=1,
            col=1,
        )
        fig.update_xaxes(
            title_text="Vlsr (km/s)",
            showgrid=False,
            zeroline=False,
            showline=True,
            linecolor=theme["border-subtle"],
            color=theme["text-muted"],
            row=1,
            col=2,
        )
        fig.update_yaxes(
            title_text="Temperature (K)",
            showgrid=False,
            zeroline=False,
            showline=True,
            linecolor=theme["border-subtle"],
            color=theme["text-muted"],
            row=1,
            col=1,
        )
        fig.update_yaxes(
            title_text="Temperature (K)",
            showgrid=False,
            zeroline=False,
            showline=True,
            linecolor=theme["border-subtle"],
            color=theme["text-muted"],
            row=1,
            col=2,
        )

        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": True})

        if len(common_range) == 2:
            st.caption(
                f"Highlighted common velocity range: {common_range[0]:.3f} to "
                f"{common_range[1]:.3f} km/s."
            )
        st.caption(
            f"Before = {result['filename1']} · reference = {result['filename2']} · "
            f"mode = {result['mode']}"
        )


# ---------------------------------------------------------------------------
# Page render
# ---------------------------------------------------------------------------

styles.render_page_header(
    title=PAGE_TITLE,
    subtitle=PAGE_SUBTITLE,
    current_stage=CURRENT_STAGE,
    completed_stages=_completed_upstream_count(),
)

if not _upstream_complete():
    missing = [key for key in UPSTREAM_STAGE_KEYS if key not in st.session_state["completed_stages"]]
    _clear_stage3_and_downstream()
    st.error(
        "Bandpass correction requires Source Browser and File Loader to be completed first. "
        f"Missing stage keys: {', '.join(missing)}."
    )
    if st.button("Return to File Loader", key="bandpass_return_loader"):
        st.switch_page("pages/02_File_Loader.py")
    st.stop()

pairs = get_full_integration_pairs()
if not pairs:
    _clear_stage3_and_downstream()
    st.error(
        "No complete bandpass pair could be detected. Page 03 needs at least two "
        "successfully loaded FITS files with SPPOINT = 0."
    )
    if st.button("Return to File Loader", key="bandpass_return_loader_no_pair"):
        st.switch_page("pages/02_File_Loader.py")
    st.stop()

if len([entry for pair in pairs for entry in pair]) < 2:
    _clear_stage3_and_downstream()
    st.error("The selected observation does not contain a complete full-integration pair.")
    st.stop()

if st.session_state.get("bandpass_pair_index", 0) >= len(pairs):
    st.session_state["bandpass_pair_index"] = 0

pair_labels = [
    f"Pair {index + 1}: {pair[0]['filename']} ↔ {pair[1]['filename']}"
    for index, pair in enumerate(pairs)
]

st.markdown('<div class="hs-eyebrow">Full-integration pair</div>', unsafe_allow_html=True)
pair_index = st.selectbox(
    "Full-integration pair",
    options=range(len(pairs)),
    format_func=lambda index: pair_labels[index],
    key="bandpass_pair_index",
    label_visibility="collapsed",
)
selected_pair = pairs[pair_index]
pair_signature = f"{selected_pair[0]['filename']}::{selected_pair[1]['filename']}"

# Auto-select the CLC-derived mode when the detected pair changes, but leave the explicit toggle available for the user.
if st.session_state.get("bandpass_pair_signature") != pair_signature:
    st.session_state["bandpass_pair_signature"] = pair_signature
    suggested_mode, _reason = suggest_mode(selected_pair)
    if suggested_mode is not None:
        st.session_state["bandpass_mode"] = suggested_mode
    _clear_stage3_and_downstream()

_render_pair_info(selected_pair, pair_index + 1, len(pairs))

st.markdown('<div class="hs-eyebrow">Bandpass mode</div>', unsafe_allow_html=True)
st.radio(
    "Bandpass mode",
    options=MODE_OPTIONS,
    horizontal=True,
    key="bandpass_mode",
    label_visibility="collapsed",
    on_change=_on_mode_change,
)

# Automatically apply the detected/selected mode.
try:
    current_mode = st.session_state["bandpass_mode"]
    applied_mode = st.session_state.get("bandpass_applied_mode")

    if applied_mode != current_mode:
        result = build_bandpass_result(current_mode, selected_pair)
        _commit_result(result)

except (ValueError, TypeError, KeyError) as exc:
    _clear_stage3_and_downstream()
    st.error(f"Bandpass correction failed: {exc}")

stored_result = st.session_state.get("bandpass_display_result")
applied_mode = st.session_state.get("bandpass_applied_mode")

if stored_result and applied_mode == st.session_state["bandpass_mode"]:
    _render_before_after(stored_result)

    if st.button("Continue to Baseline Block Editor →", key="continue_to_baseline"):
        st.switch_page("pages/04_Baseline_Editor.py")
else:
    st.info("")
