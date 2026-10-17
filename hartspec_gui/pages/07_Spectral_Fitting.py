# 07_Spectral_Fitting.py — FR-14/15/16/17: Gaussian / polynomial / multi-component fitting of the calibrated spectrum.
# FR-17 (Multi-component mode): editable component table, live composite + residual, auto-decomposition via
# clc/Spec_comp.py (unmodified, through utils/fitting_helpers.py), termination criteria, lock + refit, session restore.
#
# UAT / system-owner layout:
#   Graph 1  LCP
#   Graph 2  RCP
#   (extra)  pair average -- for every LCP/RCP pair of points (LCP + RCP) / 2, plus the overall mean of those averages
#   Graph 3  [(LCP + RCP) * PSS] + Pointing Correction     (formula exactly as specified by the system owner)
#   Graph 4  the fit of Graph 3 (the Fit Type selector below applies to Graph 3)
#
# Inputs: LCP/RCP from the shared spectrum chain (utils/spectrum_resolution.py, the same one Page 08 uses); PSS from
# Page 05 and the Pointing Correction from Page 06 (both via utils/fitting_inputs.py, which also holds the arithmetic).
# Graph 3 is only drawn from the PRE-calibration (K) spectrum: a spectrum already scaled by Page 05 would have PSS
# applied twice.
#
# The fitting itself lives in utils/spectral_fitting_logic.py (pure, unit-tested); no clc/Gaussf.py call is made
# directly -- see that module's header for the open FR-15 / FR-16 / FR-17 questions (all marked TODO).
#   # TODO: confirm against design -- Graph 3 ADDS the pointing correction factor as written in the owner's formula;
#   # pointcor() returns a multiplicative factor. See utils/fitting_inputs.py.
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from plotly.subplots import make_subplots

from utils import baseline_editor_bridge, fitting_helpers, fitting_inputs, session_store, spectrum_resolution, styles
from utils.sidebar import render_sidebar
from utils.spectral_fitting_logic import FIT_TYPES, FitResult, run_fit

THIS_STAGE_KEY = "07_spectral_fitting"
CURRENT_STAGE = 7  # 1-indexed, per utils/sidebar.py + utils/styles.py convention
NEXT_PAGE = "pages/08_Export_and_Session.py"
MULTI_FIT_TYPE = "Multi-component"  # must match the label in utils.spectral_fitting_logic.FIT_TYPES

st.set_page_config(page_title="HARTSPEC — Spectral Fitting", layout="wide")
session_store.init_session_state()
render_sidebar(CURRENT_STAGE)
styles.inject_base_css()
styles.render_page_header(
    "Spectral Fitting",
    "Gaussian / polynomial / multi-component fits",
    CURRENT_STAGE,
    # strictly-before-this-page count, per Build Spec section 6 (completed_count() also counted this page)
    session_store.completed_before(CURRENT_STAGE),
)
theme = styles.get_theme()


def _figure(traces: list[tuple[str, Any, Any, str, str]], y_title: str, height: int = 280,
            hline: Optional[float] = None) -> go.Figure:
    """Themed line chart. traces = (name, x, y, colour, dash); backgrounds follow bg-panel (Plotly doesn't inherit)."""
    fig = go.Figure()
    for name, x, y, color, dash in traces:
        fig.add_scatter(x=x, y=y, mode="lines", line=dict(color=color, width=1.6, dash=dash), name=name)
    if hline is not None and np.isfinite(hline):
        fig.add_hline(y=hline, line=dict(color=theme["text-muted"], width=1, dash="dot"))
    fig.update_layout(**styles.plotly_layout_theme(theme))
    fig.update_layout(
        height=height, margin=dict(l=40, r=20, t=10, b=40),
        paper_bgcolor=theme["bg-panel"], plot_bgcolor=theme["bg-panel"],
        font=dict(color=theme["text-body"]),
        legend=dict(orientation="h", y=-0.25),
        xaxis=dict(title="Vlsr (km/s)", showgrid=False, zeroline=False, color=theme["text-muted"]),
        yaxis=dict(title=y_title, showgrid=False, zeroline=False, color=theme["text-muted"]),
    )
    return fig


def _panel(title: str, fig: Optional[go.Figure], placeholder: str = "") -> None:
    """Bordered panel with title; a short message instead of the chart when the graph can't be drawn yet."""
    with st.container(border=True):
        st.markdown(f'<div class="hs-panel-title">{title}</div>', unsafe_allow_html=True)
        if fig is None:
            st.info(placeholder)
        else:
            styles.render_plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, theme=None)


# ---------------------------------------------------------------------
# FIT TYPE selector (applies to Graph 3)
# ---------------------------------------------------------------------
st.markdown('<div class="hs-eyebrow">Fit Type</div>', unsafe_allow_html=True)
# st.radio, not custom pill buttons -- utils/styles.py's inject_base_css() already carries a specific fix for
# "Page 07's Fit type" radio label contrast, confirming this is the established widget choice for this control.
fit_type = st.radio("Fit type", FIT_TYPES, horizontal=True, label_visibility="collapsed", key="fit_type")
is_multi = fit_type == MULTI_FIT_TYPE
st.caption("The fit is applied to Graph 3 and shown in Graph 4. Graphs 1 and 2 show the input channels.")
# Describe the existing implementation honestly; do not change fitting algorithms here.
if fit_type == "2D Gaussian":
    st.info(
        "Current implementation: two Gaussian components on a 1D velocity spectrum, "
        "not a spatial 2D Gaussian fit. The full image/heatmap fit is not implemented here."
    )
elif fit_type == "Multi-component":
    st.info(
        "Add, edit, lock or delete Gaussian components in the table below; the composite model and residual update "
        "immediately. 'Run Auto-Decomposition' uses clc/Spec_comp.py, a fixed three-component Gaussian fit that the "
        "termination criteria can stop early."
    )

# ---------------------------------------------------------------------
# Resolve inputs
# ---------------------------------------------------------------------
resolved = spectrum_resolution.resolve_spectrum(
    st.session_state,
    read_bridge=baseline_editor_bridge.read_bridge,
    fingerprint=baseline_editor_bridge.spectrum_fingerprint,
)
unit = resolved.intensity_unit
vlsr = resolved.vlsr
lcp, rcp = resolved.channels["LCP"], resolved.channels["RCP"]
pipeline_data = st.session_state.get("pipeline_data", {})
pss = fitting_inputs.pss_from_pipeline(pipeline_data)
pointing_factor = fitting_inputs.pointing_factor_from_pipeline(pipeline_data)

st.caption(f"Spectrum source: {resolved.source_label}")
for note in resolved.notes:
    st.warning(note)
if resolved.is_placeholder:
    st.error(
        "No real spectrum is available in this session, so the graphs below are of synthetic placeholder data. "
        "Saving is disabled -- complete the earlier pipeline stages first."
    )

# Graph 3 needs a real, not-yet-PSS-scaled spectrum plus PSS (Page 05) and the pointing correction (Page 06).
blockers: list[str] = []
if resolved.is_placeholder:
    blockers.append("a real spectrum")
if (
    not resolved.is_placeholder
    and not resolved.is_calibrated
    and resolved.source_key != spectrum_resolution.SOURCE_BASELINE
):
    blockers.append("a valid baseline-flattened spectrum -- complete Page 04 (Baseline Editor)")
if pss is None:
    blockers.append("a PSS value -- complete Page 05 (Calibration Dashboard)")
if pointing_factor is None:
    blockers.append("a pointing correction -- complete Page 06 (Pointing Correction)")
graph3_ready = not blockers
if blockers:
    st.warning("Graph 3 and its fit need " + "; ".join(blockers) + ".")

graph3: Optional[np.ndarray] = None
result: Optional[FitResult] = None
source_key = ""
if graph3_ready:
    if resolved.is_calibrated:
        # Page 05 already applied ATcor and PSS.
        graph3 = lcp + rcp + pointing_factor
    else:
        graph3 = fitting_inputs.graph3(
            lcp, rcp, pss.value, pointing_factor
        )
    source_key = fitting_inputs.graph3_source_key(resolved.source_key, pss.value, pointing_factor)
    if not is_multi:
        result = run_fit(fit_type, vlsr, graph3, fitting_inputs.GRAPH3_UNIT)

saved_fit = st.session_state.get("latest_fit")
if saved_fit and graph3_ready and saved_fit.get("spectrum_source") != source_key:
    st.warning("The fit saved earlier was computed on different data (another spectrum, PSS or pointing correction). "
               "Save again to update it.")
if result is not None:
    for note in result.notes:
        (st.warning if result.ok else st.error)(note)

# ---------------------------------------------------------------------
# Graphs 1 & 2 — LCP, RCP
# ---------------------------------------------------------------------
left, right = st.columns(2)
with left:
    _panel("Graph 1 — LCP", _figure([("LCP", vlsr, lcp, styles.LCP_COLOR, "solid")], f"Intensity ({unit})"))
with right:
    _panel("Graph 2 — RCP", _figure([("RCP", vlsr, rcp, styles.RCP_COLOR, "solid")], f"Intensity ({unit})"))

# ---------------------------------------------------------------------
# Pair average — (LCP + RCP) / 2 per pair of points, then the overall mean
# ---------------------------------------------------------------------
average, overall_mean = fitting_inputs.pair_average(lcp, rcp)
_panel(
    "Average of each LCP/RCP pair — (LCP + RCP) / 2",
    _figure([("(LCP + RCP) / 2", vlsr, average, theme["accent"], "solid")], f"Intensity ({unit})", 260,
            hline=overall_mean),
)
st.caption(f"Overall average of the pair averages (dotted line): {overall_mean:.4f} {unit}")

# ---------------------------------------------------------------------
# Graphs 3 & 4 — [(LCP + RCP) * PSS] + Pointing Correction, and its fit
# ---------------------------------------------------------------------
g3_unit = fitting_inputs.GRAPH3_UNIT
left, right = st.columns(2)
with left:
    _panel(
        ("Graph 3 — Calibrated (LCP + RCP) + Pointing Correction"
         if resolved.is_calibrated
         else "Graph 3 — [(LCP + RCP) × PSS] + Pointing Correction"),
        None if graph3 is None else _figure([("Graph 3", vlsr, graph3, theme["accent"], "solid")],
                                            f"Intensity ({g3_unit})"),
        "Waiting for the inputs listed above.",
    )
with right:
    g4_slot = st.container()  # filled after the fit-parameters section so it sees this run's edits
if pss is not None and pointing_factor is not None:
    st.caption(
        f"PSS = {pss.value:.4f} Jy/K (mean of the LCP {pss.lcp_mean:.4f} and RCP {pss.rcp_mean:.4f} "
        f"±{pss.window_days}-day means, Page 05) · Pointing Correction = {pointing_factor:.4f} (Page 06, added as "
        "specified)"
    )

# ---------------------------------------------------------------------
# Fit parameters table
# ---------------------------------------------------------------------
def _multi_figure(v: np.ndarray, y: np.ndarray, params: fitting_helpers.Params, unit_label: str) -> go.Figure:
    """Main plot (data, components, composite) over a residual subplot; backgrounds follow bg-panel."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.06)
    fig.add_scatter(x=v, y=y, mode="lines", name="Graph 3", line=dict(color=theme["accent"], width=1.6), row=1, col=1)
    for p, curve in zip(params, fitting_helpers.component_curves(v, params)):
        fig.add_scatter(x=v, y=curve, mode="lines", name=p["id"],
                        line=dict(color=theme["text-muted"], width=1, dash="dot"), row=1, col=1)
    model = fitting_helpers.composite(v, params)
    if params:
        fig.add_scatter(x=v, y=model, mode="lines", name="Composite model",
                        line=dict(color=styles.get_fit_line_color(), width=1.6, dash="dash"), row=1, col=1)
    fig.add_scatter(x=v, y=y - model, mode="lines", name="Residual (data − model)",
                    line=dict(color=theme["text-muted"], width=1.2), row=2, col=1)
    fig.add_hline(y=0, line=dict(color=theme["border-subtle"], width=1), row=2, col=1)
    fig.update_layout(**styles.plotly_layout_theme(theme))
    fig.update_layout(height=460, margin=dict(l=40, r=20, t=10, b=40), paper_bgcolor=theme["bg-panel"],
                      plot_bgcolor=theme["bg-panel"], font=dict(color=theme["text-body"]),
                      legend=dict(orientation="h", y=-0.15))
    fig.update_xaxes(showgrid=False, zeroline=False, color=theme["text-muted"])
    fig.update_yaxes(showgrid=False, zeroline=False, color=theme["text-muted"])
    fig.update_xaxes(title_text="Vlsr (km/s)", row=2, col=1)
    fig.update_yaxes(title_text=f"Intensity ({unit_label})", row=1, col=1)
    fig.update_yaxes(title_text="Residual", row=2, col=1)
    return fig


@st.cache_data(show_spinner=False)
def _cached_spec_comp(v: np.ndarray, y: np.ndarray) -> fitting_helpers.Params:
    """Spec_comp.py result for one spectrum, cached so repeat clicks / reruns stay inside the 2 s budget (NFR-01)."""
    return fitting_helpers.run_spec_comp(v, y)


def _set_multi_params(params: fitting_helpers.Params, uncertainties: Optional[list] = None,
                      covariance: Optional[list] = None) -> None:
    """Programmatically replace the component table (new editor key so st.data_editor drops its old edit state)."""
    ss = st.session_state
    ss["spectral_fitting_multi_comp_params"] = params
    ss["spectral_fitting_multi_comp_uncertainties"] = uncertainties
    ss["spectral_fitting_multi_comp_covariance"] = covariance
    # uncertainties are only valid for exactly these values
    ss["spectral_fitting_multi_comp_unc_for"] = [dict(p) for p in params]
    ss["spectral_fitting_multi_comp_base_df"] = fitting_helpers.df_from_params(params)
    ss["spectral_fitting_multi_comp_version"] = ss.get("spectral_fitting_multi_comp_version", 0) + 1


def _restore_multi_from_session() -> None:
    """Rebuild the component table from the saved session block (Load Session / page revisit). Arrays are recomputed."""
    ss = st.session_state
    block = (st.session_state.get("pipeline_data", {}).get(THIS_STAGE_KEY) or {}).get("multi_component")
    if "spectral_fitting_multi_comp_params" not in ss:
        _set_multi_params([])
    if block != ss.get("spectral_fitting_multi_comp_saved_block"):  # session JSON changed underneath us (load / reset)
        try:
            _set_multi_params(fitting_helpers.restore_from_block(block) if block else [])
        except ValueError as exc:
            st.warning(f"The saved multi-component fit could not be restored: {exc}")
            _set_multi_params([])
        ss["spectral_fitting_multi_comp_saved_block"] = block


def _render_multi_component(v: np.ndarray, y: np.ndarray, unit_label: str) -> dict[str, Any]:
    """Controls + editable table inside the open 'Fit parameters' panel. Returns the state needed to plot and save."""
    ss = st.session_state
    _restore_multi_from_session()
    with st.expander("Termination criteria for auto-decomposition", expanded=False):
        c1, c2, c3 = st.columns(3)
        max_components = int(c1.number_input("max_components", min_value=1, max_value=20, value=10, step=1,
                                             key="spectral_fitting_mc_max_components",
                                             help="Spec_comp.py itself stops at 3."))
        rms_cutoff = float(c2.number_input("rms_cutoff (× σ_RMS)", min_value=0.0, value=5.0, step=0.5,
                                           key="spectral_fitting_mc_rms_cutoff",
                                           help="Default 5: pure noise over ~1000 channels peaks near 3.2 σ."))
        chi2_threshold = float(c3.number_input("chi2_threshold (Δ reduced χ²)", min_value=0.0, value=0.01, step=0.01,
                                               format="%.4f", key="spectral_fitting_mc_chi2_threshold"))
    b1, b2, b3, _ = st.columns([1.6, 1.3, 1.1, 2])
    run_clicked = b1.button("Run Auto-Decomposition / Fit", type="primary", use_container_width=True,
                            key="spectral_fitting_mc_run")
    refit_clicked = b2.button("Refit free parameters", type="secondary", use_container_width=True,
                              key="spectral_fitting_mc_refit")
    clear_clicked = b3.button("Clear all", type="secondary", use_container_width=True, key="spectral_fitting_mc_clear")

    if clear_clicked:
        _set_multi_params([])
    if run_clicked:
        try:
            # spinner always shown: the call is cached after the first run, so it only flashes when it is fast
            with st.spinner("Executing multi-component Gaussian decomposition..."):
                sequence = _cached_spec_comp(v, y)
            kept, why = fitting_helpers.apply_termination(v, y, sequence, max_components, rms_cutoff, chi2_threshold)
            if kept:
                _set_multi_params(kept)  # Spec_comp.py provides no uncertainties
                st.caption(f"Auto-decomposition: {len(kept)} component(s) — {why}.")
            else:
                st.warning(f"No components met the termination criteria ({why}). The table was left unchanged.")
        except fitting_helpers.DecompositionError as exc:
            st.error(f"Auto-decomposition failed: {exc} Your current components were kept.")
    if refit_clicked:
        try:
            with st.spinner("Refitting unlocked components..."):
                new_params, uncs, cov = fitting_helpers.refit_free(v, y, ss["spectral_fitting_multi_comp_params"])
            _set_multi_params(new_params, uncs, cov)
        except fitting_helpers.FitError as exc:
            st.error(f"Refit failed: {exc} Your current components were kept.")

    edited = st.data_editor(
        ss["spectral_fitting_multi_comp_base_df"],
        key=f"spectral_fitting_mc_editor_{ss['spectral_fitting_multi_comp_version']}", num_rows="dynamic",
        hide_index=True, use_container_width=True, disabled=[fitting_helpers.COL_ID],
        column_config={
            fitting_helpers.COL_ID: st.column_config.TextColumn("Component"),
            fitting_helpers.COL_AMP: st.column_config.NumberColumn(f"Amplitude ({unit_label})", format="%.4f"),
            fitting_helpers.COL_CENTER: st.column_config.NumberColumn("Center Vlsr (km/s)", format="%.4f"),
            fitting_helpers.COL_FWHM: st.column_config.NumberColumn("FWHM (km/s)", format="%.4f", min_value=0.0),
            fitting_helpers.COL_LOCK: st.column_config.CheckboxColumn(
                "Lock", help="Locked components are held fixed by 'Refit free parameters'."),
        },
    )
    params, problems = fitting_helpers.params_from_df(edited)
    for msg in problems:
        st.warning(msg)
    ss["spectral_fitting_multi_comp_params"] = params
    # hand-edited since the fit that produced the uncertainties?
    stale = ss.get("spectral_fitting_multi_comp_unc_for") != params
    uncs = None if stale else ss.get("spectral_fitting_multi_comp_uncertainties")
    cov = None if stale else ss.get("spectral_fitting_multi_comp_covariance")
    ss["spectral_fitting_multi_comp_residual"] = y - fitting_helpers.composite(v, params)
    ss["spectral_fitting_multi_comp_stats"] = fitting_helpers.compute_stats(v, y, params)
    stats = ss["spectral_fitting_multi_comp_stats"]
    if params:
        no_unc = "" if uncs else " · no uncertainties (run 'Refit free parameters')"
        st.caption(f"Reduced χ² = {stats['chi2']:.4g} · RMS residual = {stats['rms_residual']:.4g} {unit_label} · "
                   f"{len(params)} component(s){no_unc}")
    return {"params": params, "uncertainties": uncs, "covariance": cov, "stats": stats,
            "curve": fitting_helpers.composite(v, params)}


styles.render_panel_open("Fit parameters")
multi: Optional[dict[str, Any]] = None
if is_multi:
    if graph3 is not None:
        multi = _render_multi_component(vlsr, graph3, g3_unit)
    else:
        st.caption("Waiting for Graph 3 before components can be fitted.")
elif result is not None and result.rows:
    param_df = pd.DataFrame(list(result.rows), columns=["Parameter", "Value", "± Error"])
    styles.render_dataframe(param_df, hide_index=True, use_container_width=True)
else:
    st.caption("No fit parameters -- the fit did not produce a result.")
styles.render_panel_close()

if multi is not None:
    # Same shape as run_fit()'s FitResult for everything the commit code reads, plus the session-JSON block.
    result = SimpleNamespace(
        ok=bool(multi["params"]), fell_back=False, fit_type_used=MULTI_FIT_TYPE, fit_type_requested=MULTI_FIT_TYPE,
        rows=[(r["parameter"], r["value"], r["error"])
              for r in fitting_helpers.summary_rows(multi["params"], multi["uncertainties"])],
        converged=True, notes=[], curve=multi["curve"],
        multi_component=fitting_helpers.build_fitting_block(multi["params"], multi["uncertainties"],
                                                            multi["covariance"], multi["stats"]),
    )
    _panel("Multi-component decomposition — spectrum, components, composite and residual",
           _multi_figure(vlsr, graph3, multi["params"], g3_unit), "")

# Graph 4 (right column above) is drawn here so it reflects this run's table edits
with g4_slot:
    fig4 = None
    if graph3 is not None:
        traces4 = [("Graph 3", vlsr, graph3, theme["accent"], "solid")]
        if is_multi:
            if multi is not None and multi["params"]:
                traces4.append(("Composite model", vlsr, multi["curve"], styles.get_fit_line_color(), "dash"))
        elif result is not None and result.ok:
            traces4.append(("Fit" if not result.fell_back else f"Fit ({result.fit_type_used})", vlsr, result.curve,
                            styles.get_fit_line_color(), "dash"))
        fig4 = _figure(traces4, f"Intensity ({g3_unit})")
    _panel("Graph 4 — Fit of Graph 3", fig4, "Waiting for Graph 3.")


# ---------------------------------------------------------------------
# Commit fit to session — drives the progress bar and feeds Page 08's export/observation log. Not an explicit element
# in the mockup; added so the pipeline has a real "stage complete" trigger rather than auto-marking on every
# recompute (which would spam the audit log on every selector click).
# TODO: confirm against design
# ---------------------------------------------------------------------
def _stage_summary() -> dict[str, Any]:
    """Lightweight, JSON-serializable summary for pipeline_data (no full arrays -- those go in latest_fit).

    ``fit_type`` is the model actually fitted (differs from ``fit_type_requested`` after a fallback); the formula,
    PSS and pointing factor are recorded so a saved session states exactly what was fitted.
    """
    summary = {
        "fit_type": result.fit_type_used,
        "fit_type_requested": result.fit_type_requested,
        "fitted_quantity": (
            "Calibrated LCP + calibrated RCP + Pointing Correction"
            if getattr(resolved, "is_calibrated", False)
            else f"Graph 3 = {fitting_inputs.GRAPH3_FORMULA}"
        ),
        "parameters": [{"parameter": p, "value": v, "error": e} for p, v, e in result.rows],
        "converged": result.converged,
        "notes": list(result.notes),
        "spectrum_source": source_key,
        "intensity_unit": g3_unit,
        "pss_jy_per_k": pss.value,
        "pointing_correction_factor": pointing_factor,
        "n_channels": int(vlsr.size),
        "vlsr_range_kms": [float(vlsr.min()), float(vlsr.max())] if vlsr.size else [],
    }
    block = getattr(result, "multi_component", None)
    if block:
        summary["multi_component"] = block  # restored by _restore_multi_from_session on Load Session
    return summary


can_save = result is not None and result.ok and graph3_ready
save_col, next_col, _ = st.columns([1, 1.4, 3])
with save_col:
    save_clicked = st.button("Save fit to session", type="secondary", disabled=not can_save, use_container_width=True)
with next_col:
    # "Do this next" action -> primary (style guide §4). Enabled even without a saved fit so the pipeline can proceed.
    next_clicked = st.button("Continue to Export & Session →", type="primary", use_container_width=True,
                             key="fitting_next_btn")

if save_clicked:
    summary = _stage_summary()
    st.session_state.setdefault("pipeline_data", {})[THIS_STAGE_KEY] = summary
    if summary.get("multi_component"):
        # remember it so the page doesn't "restore" its own save (key is under the existing spectral_fitting_ namespace)
        st.session_state["spectral_fitting_multi_comp_saved_block"] = summary["multi_component"]
    # Full curves live in session_state directly (not pipeline_data) for Page 08's overlay/export -- the same
    # "summaries in pipeline_data, arrays in session_state" split as Pages 02/03/04. `spectrum_source` encodes
    # spectrum + PSS + pointing correction, so Page 08 refuses an overlay computed on different inputs.
    st.session_state["latest_fit"] = {
        "fit_type": result.fit_type_used,
        "spectrum_source": source_key,
        "intensity_unit": g3_unit,
        "vlsr": vlsr.tolist(),
        "fit_curve": result.curve.tolist(),
    }
    session_store.mark_stage_complete(THIS_STAGE_KEY)
    session_store.log_event(
        f"Spectral fit committed — {result.fit_type_used} fitted to Graph 3 "
        f"(PSS {pss.value:.4f}, pointing correction {pointing_factor:.4f}, {resolved.source_key} spectrum)"
    )
    session_store.checkpoint_session("Spectral fit committed")
    if not st.session_state.get("checkpoint_error"):
        st.success("Fit saved to session and checkpointed.")

if next_clicked:
    st.switch_page(NEXT_PAGE)
