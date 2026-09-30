# 07_Spectral_Fitting.py — FR-14/15/16/17: Gaussian / polynomial / multi-
# component spectral line fitting, with a spectrum + fit overlay chart and a
# fit-parameters table.
#
# The fitting itself lives in utils/spectral_fitting_logic.py (pure, unit-tested) and the "which spectrum is
# current?" decision in utils/spectrum_resolution.py (shared with Page 08). This file is only the Streamlit layer.
#
# Wired against the utils/ modules actually in the repo:
#   utils/session_store.py     -- session_id, pipeline_data, audit log, stage completion
#                                  (init_session_state / log_event / mark_stage_complete / completed_before)
#   utils/styles.py             -- theme tokens, inject_base_css, page header, LCP_COLOR/RCP_COLOR,
#                                  get_fit_line_color()
#   utils/sidebar.py            -- render_sidebar (nav + theme toggle + Save/Load/Reset, 1-indexed current_stage)
#   utils/baseline_editor_bridge.py -- read_bridge / spectrum_fingerprint, passed into the resolver
#
# No clc/Gaussf.py call is made directly -- see the header of utils/spectral_fitting_logic.py for why, and for
# the open FR-15 / FR-16 / FR-17 questions (all marked TODO: confirm against design).
from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import baseline_editor_bridge, session_store, spectrum_resolution, styles
from utils.sidebar import render_sidebar
from utils.spectral_fitting_logic import FIT_TYPES, FitResult, run_fit

THIS_STAGE_KEY = "07_spectral_fitting"
CURRENT_STAGE = 7  # 1-indexed, per utils/sidebar.py + utils/styles.py convention
POLARIZATIONS = spectrum_resolution.POLARIZATIONS

st.set_page_config(page_title="HARTSPEC — Spectral Fitting", layout="wide")
session_store.init_session_state()
render_sidebar(CURRENT_STAGE)
styles.inject_base_css()
styles.render_page_header(
    "Spectral Fitting",
    "FR-14–17 — Gaussian / polynomial / multi-component fits",
    CURRENT_STAGE,
    # strictly-before-this-page count, per Build Spec section 6 (completed_count() also counted this page)
    session_store.completed_before(CURRENT_STAGE),
)

# ---------------------------------------------------------------------
# FIT TYPE + polarization selectors
# ---------------------------------------------------------------------
st.markdown('<div class="hs-eyebrow">Fit Type</div>', unsafe_allow_html=True)
# st.radio, not custom pill buttons -- utils/styles.py's inject_base_css()
# already carries a specific fix for "Page 07's Fit type" radio label
# contrast, confirming this is the established widget choice for this
# control, not styled button pills.
fit_type = st.radio(
    "Fit type", FIT_TYPES, horizontal=True, label_visibility="collapsed", key="fit_type",
)

pol_col, _ = st.columns([1, 4])
with pol_col:
    polarization = st.radio(
        "Polarization", POLARIZATIONS, horizontal=True, key="fit_polarization",
    )

st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Resolve spectrum + fit
# ---------------------------------------------------------------------
resolved = spectrum_resolution.resolve_spectrum(
    st.session_state,
    read_bridge=baseline_editor_bridge.read_bridge,
    fingerprint=baseline_editor_bridge.spectrum_fingerprint,
)
unit = resolved.intensity_unit
vlsr = resolved.vlsr
y = resolved.channels[polarization]
result: FitResult = run_fit(fit_type, vlsr, y, unit)

st.caption(f"Spectrum source: {resolved.source_label}")
for note in resolved.notes:
    st.warning(note)
if resolved.is_placeholder:
    st.error(
        "No real spectrum is available in this session, so the fit below is of synthetic placeholder data. "
        "Saving is disabled -- complete the earlier pipeline stages first."
    )
elif not resolved.is_calibrated:
    st.warning(
        f"This fit uses an uncalibrated spectrum ({unit}). Complete Page 5 (Calibration Dashboard) to fit the "
        "calibrated spectrum."
    )

saved_fit = st.session_state.get("latest_fit")
if saved_fit and saved_fit.get("spectrum_source") != resolved.source_key:
    st.warning(
        "The fit saved earlier was computed on a different spectrum than the one shown now "
        f"({saved_fit.get('spectrum_source', 'unknown source')}). Save again to update it."
    )

for note in result.notes:
    (st.warning if result.ok else st.error)(note)

# ---------------------------------------------------------------------
# Spectrum + fit overlay chart
# ---------------------------------------------------------------------
styles.render_panel_open("Spectrum + fit overlay")
fig = go.Figure()
fig.add_scatter(
    x=vlsr, y=y, mode="lines",
    line=dict(color=styles.LCP_COLOR if polarization == "LCP" else styles.RCP_COLOR, width=1.6),
    name=f"Spectrum ({polarization})",
)
if result.ok:
    fig.add_scatter(
        x=vlsr, y=result.curve, mode="lines",
        line=dict(color=styles.get_fit_line_color(), width=1.6, dash="dash"),
        name="Fit" if not result.fell_back else f"Fit ({result.fit_type_used})",
    )
theme = styles.get_theme()
fig.update_layout(
    height=320, margin=dict(l=40, r=20, t=10, b=40),
    paper_bgcolor=theme["bg-panel"], plot_bgcolor=theme["bg-panel"],
    font=dict(color=theme["text-body"]),
    legend=dict(orientation="h", y=-0.2),
    xaxis=dict(title="Vlsr (km/s)", showgrid=False, zeroline=False, color=theme["text-muted"]),
    yaxis=dict(title=f"Intensity ({unit})", showgrid=False, zeroline=False, color=theme["text-muted"]),
)
st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
styles.render_panel_close()

# ---------------------------------------------------------------------
# Fit parameters table
# ---------------------------------------------------------------------
styles.render_panel_open("Fit parameters")
if result.rows:
    param_df = pd.DataFrame(list(result.rows), columns=["Parameter", "Value", "± Error"])
    st.dataframe(param_df, hide_index=True, use_container_width=True)
else:
    st.caption("No fit parameters -- the fit did not produce a result.")
styles.render_panel_close()


# ---------------------------------------------------------------------
# Commit fit to session — drives the progress bar and feeds Page 08's
# export/observation log. Not an explicit element in the mockup; added so
# the pipeline has a real "stage complete" trigger rather than auto-marking
# on every recompute (which would spam the audit log on every pill click).
# TODO: confirm against design
# ---------------------------------------------------------------------
def _stage_summary() -> dict[str, Any]:
    """Lightweight, JSON-serializable summary for pipeline_data.

    Mirrors bandpass_correction_logic.stage_summary()'s pattern of NOT duplicating full spectrum/fit arrays
    into session persistence. ``fit_type`` is the model actually fitted (which differs from
    ``fit_type_requested`` after a fallback), and the spectrum source + unit are recorded so a saved session
    can never present a fit of uncalibrated or synthetic data as a calibrated result.
    """
    return {
        "fit_type": result.fit_type_used,
        "fit_type_requested": result.fit_type_requested,
        "polarization": polarization,
        "parameters": [{"parameter": p, "value": v, "error": e} for p, v, e in result.rows],
        "converged": result.converged,
        "notes": list(result.notes),
        "spectrum_source": resolved.source_key,
        "intensity_unit": unit,
        "n_channels": int(vlsr.size),
        "vlsr_range_kms": [float(vlsr.min()), float(vlsr.max())] if vlsr.size else [],
    }


can_save = result.ok and not resolved.is_placeholder
if st.button("Save fit to session", type="primary", disabled=not can_save):
    st.session_state.setdefault("pipeline_data", {})[THIS_STAGE_KEY] = _stage_summary()
    # Full fit curve kept in session_state directly (not pipeline_data) for
    # Page 08 to reuse if it wants to overlay the fit on the export chart --
    # same "summaries in pipeline_data, arrays in session_state" split used
    # by Page 02/03/04. spectrum_source lets Page 08 refuse an overlay computed on a different spectrum.
    st.session_state["latest_fit"] = {
        "fit_type": result.fit_type_used,
        "polarization": polarization,
        "spectrum_source": resolved.source_key,
        "intensity_unit": unit,
        "vlsr": vlsr.tolist(),
        "fit_curve": result.curve.tolist(),
    }
    session_store.mark_stage_complete(THIS_STAGE_KEY)
    session_store.log_event(
        f"Spectral fit committed — {result.fit_type_used} ({polarization}, {resolved.source_key} spectrum)"
    )
    st.success("Fit saved to session.")
