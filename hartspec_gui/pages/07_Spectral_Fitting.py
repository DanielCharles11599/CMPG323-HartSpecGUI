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
# The Plotly
# figures are built by utils/fit_figures.py (pure, unit-tested). FR mapping: FR-14 1D Gaussian (clc/Gaussf.py), FR-15
# Polynomial Peak (clc/fit_max.py), FR-16 2D Gaussian (clc/2D_Gauss_fit.py, on st.session_state.map_2d_data), FR-17
# Multi-component (clc/Spec_comp.py). The clc/ calls go through the adapters in utils/fitting_helpers.py.
#   # TODO: confirm against design -- Graph 3 ADDS the pointing correction factor as written in the owner's formula;
#   # pointcor() returns a multiplicative factor. See utils/fitting_inputs.py.
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


from utils import (baseline_editor_bridge, fit_figures, fitting_helpers, fitting_inputs, session_store,
                   spectrum_resolution, styles)
from utils.sidebar import render_sidebar
from utils.spectral_fitting_logic import FIT_TYPES, FitResult

THIS_STAGE_KEY = "07_spectral_fitting"
CURRENT_STAGE = 7  # 1-indexed, per utils/sidebar.py + utils/styles.py convention
NEXT_PAGE = "pages/08_Export_and_Session.py"
MULTI_FIT_TYPE = "Multi-component"  # must match the label in utils.spectral_fitting_logic.FIT_TYPES
GAUSSIAN_FIT_TYPE = "1D Gaussian"
POLYNOMIAL_FIT_TYPE = "Polynomial Peak"
FIT_2D_TYPE = "2D Gaussian"
MAP_STATE_KEY = "map_2d_data"  # {"data": (Ny, Nx), "x": (Nx,), "y": (Ny,)} written by Stage 2 / Stage 6
# Graph 3 is a combined trace, so it must not look like pure LCP (blue) or RCP (orange): neutral slate / cyan by theme.
GRAPH3_COLORS = {"light": "#4B5563", "dark": "#22D3EE"}

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
graph3_color = GRAPH3_COLORS[styles.get_theme_name()]


def _figure(traces: list[tuple[str, Any, Any, str, str]], y_title: str, height: int = 280,
            hline: Optional[float] = None, window: Optional[tuple[float, float]] = None) -> go.Figure:
    """Themed line chart (see utils/fit_figures.py). traces = (name, x, y, colour, dash); window = highlighted km/s."""
    return fit_figures.spectrum_figure(traces, y_title, theme, styles.plotly_layout_theme(theme), height=height,
                                       hline=hline, window=window)


def _run_clc_fit(fit_type_name: str, v: np.ndarray, y: np.ndarray, scope: str, unit_label: str
                 ) -> tuple[Optional[FitResult], Optional[tuple[float, float]], Optional[dict[str, Any]]]:
    """FR-14 / FR-15: render the controls, run the clc adapter, return (result, window to highlight, saved options).

    1D Gaussian (clc/Gaussf.py): amplitude and centre sliders and an HPBW spin box. Amplitude and centre are the
    curve_fit starting point; the HPBW is held fixed (Gaussf.py takes it as a constant).
    Polynomial Peak (clc/fit_max.py): peak velocity and half-width (in CHANNELS, as fit_max takes it) inputs --
    Streamlit 1.32 has no Plotly click events (CON-06) -- plus a 2nd-4th order selector.
    Widget keys include ``scope`` so they reset when the underlying data changes.
    """
    if fit_type_name == GAUSSIAN_FIT_TYPE:
        amp0, center0, hpbw0 = fitting_helpers.default_gaussian_guess(v, y)
        amp_max = amp0 * 2.0 if amp0 > 0 else 1.0
        c1, c2, c3 = st.columns(3)
        amp = c1.slider("Amplitude (initial guess)", 0.0, amp_max, float(min(max(amp0, 0.0), amp_max)),
                        step=amp_max / 200.0, key=f"fit_1d_amp_{scope}")
        center = c2.slider("Center velocity (km/s, initial guess)", float(v.min()), float(v.max()), center0,
                           step=float(np.mean(np.abs(np.diff(v)))), key=f"fit_1d_center_{scope}")
        hpbw = c3.number_input("HPBW (km/s, held fixed)", min_value=0.01, value=float(max(hpbw0, 0.01)), step=0.1,
                               format="%.2f", key=f"fit_1d_hpbw_{scope}")
        with st.spinner("Fitting spectrum..."):  # always shown; usually well inside the 2 s budget (NFR-01)
            result = fitting_helpers.run_gaussf(v, y, hpbw, amp, center, unit_label)
        return result, None, {"amplitude_initial_guess": float(amp), "center_initial_guess_kms": float(center),
                              "hpbw_kms_fixed": float(hpbw)}
    if fit_type_name == POLYNOMIAL_FIT_TYPE:
        step = float(np.mean(np.abs(np.diff(v))))
        c1, c2, c3 = st.columns(3)
        peak = c1.number_input("Peak velocity (km/s)", min_value=float(v.min()), max_value=float(v.max()),
                               value=float(v[np.argmax(y)]), step=0.1, format="%.2f", key=f"fit_poly_peak_{scope}")
        # TODO: confirm against design -- the default half-width is a placeholder; the spec gives none.
        half = c2.number_input("Half-width window (channels)", min_value=1, step=1,
                               value=fitting_helpers.DEFAULT_HALF_WIDTH_CHANNELS, key=f"fit_poly_half_{scope}",
                               help="Channels on either side of the peak velocity, as clc/fit_max.py takes it.")
        order = c3.selectbox("Polynomial order", fitting_helpers.POLYNOMIAL_ORDERS,
                             index=len(fitting_helpers.POLYNOMIAL_ORDERS) - 1,
                             format_func=lambda o: {2: "2nd order", 3: "3rd order", 4: "4th order"}[o],
                             key=f"fit_poly_order_{scope}")
        st.caption(f"Window ≈ ±{int(half) * step:.2f} km/s around the channel nearest the peak velocity.")
        with st.spinner("Fitting spectrum..."):
            result = fitting_helpers.run_fit_max(v, y, float(peak), int(half), int(order), unit_label)
        window = fitting_helpers.fit_max_window(v, float(peak), int(half))
        return result, window, {"peak_velocity_kms": float(peak), "half_width_channels": int(half),
                                "polynomial_order": int(order),
                                "window_kms": list(window) if window is not None else None}
    return None, None, None


def _json_curve(curve: np.ndarray) -> list[Optional[float]]:
    """Curve -> JSON-safe list (NaN outside a polynomial window becomes null; JSON has no NaN)."""
    return [float(x) if np.isfinite(x) else None for x in np.asarray(curve, dtype=float)]


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
is_2d = fit_type == FIT_2D_TYPE
st.caption("The fit is applied to Graph 3 and shown in Graph 4. Graphs 1 and 2 show the input channels.")
# Describe the existing implementation honestly; do not change fitting algorithms here.
if fit_type == FIT_2D_TYPE:
    st.info(
        "The 2D Gaussian fit works on the spatial map, not on Graph 3: set the seven starting values below and press "
        "'Fit 2D Gaussian'. Graph 4 is not used in this mode."
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
fit_options_summary: Optional[dict[str, Any]] = None  # controls used, saved with the fit
window: Optional[tuple[float, float]] = None  # polynomial window highlighted on Graphs 3 and 4
preserved: Optional[dict[str, Any]] = None  # last valid fit of this type, shown when the new fit fails
if graph3_ready:
    if resolved.is_calibrated:
        # Page 05 already applied ATcor and PSS.
        graph3 = lcp + rcp + pointing_factor
    else:
        graph3 = fitting_inputs.graph3(
            lcp, rcp, pss.value, pointing_factor
        )
    source_key = fitting_inputs.graph3_source_key(resolved.source_key, pss.value, pointing_factor)
    if fit_type in (GAUSSIAN_FIT_TYPE, POLYNOMIAL_FIT_TYPE):
        result, window, fit_options_summary = _run_clc_fit(fit_type, vlsr, graph3, source_key,
                                                           fitting_inputs.GRAPH3_UNIT)
        # last valid fit per fit type, kept in session_state so a failed refit does not blank the plot
        last_key = f"spectral_fitting_last_good_{fit_type}"
        if result.ok:
            st.session_state[last_key] = {"source": source_key, "fit_type_used": result.fit_type_used,
                                          "curve": result.curve, "curve_x": result.curve_x, "rows": result.rows}
        else:
            previous = st.session_state.get(last_key)
            if previous and previous["source"] == source_key:
                preserved = previous

saved_fit = st.session_state.get("latest_fit")
if saved_fit and graph3_ready and saved_fit.get("spectrum_source") != source_key:
    st.warning("The fit saved earlier was computed on different data (another spectrum, PSS or pointing correction). "
               "Save again to update it.")
if result is not None:
    for note in result.notes:
        (st.warning if result.ok else st.error)(note)
if preserved is not None:
    st.caption("Showing the previous valid fit of this type (not the failed one above); it cannot be saved.")

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
        None if graph3 is None else _figure([("Graph 3", vlsr, graph3, graph3_color, "solid")],
                                            f"Intensity ({g3_unit})", window=window),
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
    """Dual-panel decomposition plot (see utils/fit_figures.py): data + components + composite over the residual."""
    return fit_figures.multi_figure(v, y, params, unit_label, theme, styles.plotly_layout_theme(theme),
                                    data_color=graph3_color, fit_color=styles.get_fit_line_color())


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


def _render_2d_fit() -> dict[str, Any]:
    """FR-16 controls + results table + covariance table (inside the open 'Fit parameters' panel).

    Seven spin boxes give the starting guesses p0 for clc/2D_Gauss_fit.py's twoD_Gaussian; 'Fit 2D Gaussian' runs
    curve_fit. The last VALID fit stays in session_state, so a failed refit keeps the previous result on screen.
    Returns the state needed to plot and save: map, synthetic flag, stored fit (or None).
    """
    ss = st.session_state
    raw = ss.get(MAP_STATE_KEY)
    map_data = fitting_helpers.coerce_map_2d(raw)
    synthetic = map_data is None
    if synthetic:
        if raw is not None:
            st.warning(f"st.session_state.{MAP_STATE_KEY} is malformed (needs 'data' of shape (Ny, Nx) plus 'x' and "
                       "'y' axes, all finite) and was ignored.")
        st.info("2D Gaussian fitting requires 2D mapped observation data. No usable map is in this session, so a "
                "synthetic test map is shown instead; it cannot be saved.")
        try:
            map_data = fitting_helpers.synthetic_map_2d()
        except fitting_helpers.ClcLoadError as exc:
            st.error(f"No test map could be generated: {exc}")
            return {"map": None, "synthetic": True, "stored": None}
    scope = f"{map_data.data.shape[0]}x{map_data.data.shape[1]}_{float(map_data.data.sum()):.6g}_{synthetic}"
    defaults = fitting_helpers.default_p0_2d(map_data.x, map_data.y, map_data.data)
    labels = ("Amplitude", "X center", "Y center", "Major axis σ_x", "Minor axis σ_y", "Position angle (°)", "Offset")
    values: list[float] = []
    for row in (range(0, 4), range(4, 7)):
        for col, i in zip(st.columns(len(row)), row):
            values.append(float(col.number_input(
                labels[i], value=float(defaults[i]), format="%.4f", min_value=1e-6 if i in (3, 4) else None,
                key=f"fit_2d_{i}_{scope}")))
    p0 = tuple(values)
    if st.button("Fit 2D Gaussian", type="primary", key="spectral_fitting_2d_run"):
        with st.spinner("Fitting spectrum..."):
            fit = fitting_helpers.run_2d_gauss(map_data.x, map_data.y, map_data.data, p0, map_data.unit,
                                               map_data.axis_unit)
        if fit.ok:
            ss["spectral_fitting_2d_state"] = {"scope": scope, "p0": p0, "result": fit}
            for note in fit.notes:
                st.warning(note) if not fit.converged else st.caption(note)
        else:
            st.error(f"{fit.notes[0]} The previous valid fit, if any, is kept.")
    stored = ss.get("spectral_fitting_2d_state")
    if stored is not None and stored["scope"] != scope:
        stored = None  # fit belongs to a different map
    if stored is not None:
        if stored["p0"] != p0:
            st.caption("The starting values changed since this fit -- press 'Fit 2D Gaussian' to refit.")
        styles.render_dataframe(pd.DataFrame(list(stored["result"].rows), columns=["Parameter", "Value", "± Error"]),
                                hide_index=True, use_container_width=True)
        st.caption("Covariance matrix (clc units: position angle in radians):")
        styles.render_dataframe(fitting_helpers.covariance_dataframe(stored["result"]), use_container_width=True)
    else:
        st.caption("Press 'Fit 2D Gaussian' to fit the map.")
    return {"map": map_data, "synthetic": synthetic, "stored": stored}


styles.render_panel_open("Fit parameters")
multi: Optional[dict[str, Any]] = None
two_d: Optional[dict[str, Any]] = None
if is_2d:
    two_d = _render_2d_fit()
elif is_multi:
    if graph3 is not None:
        multi = _render_multi_component(vlsr, graph3, g3_unit)
    else:
        st.caption("Waiting for Graph 3 before components can be fitted.")
elif result is not None and result.rows:
    param_df = pd.DataFrame(list(result.rows), columns=["Parameter", "Value", "± Error"])
    styles.render_dataframe(param_df, hide_index=True, use_container_width=True)
elif preserved is not None:
    st.caption("Parameters of the previous valid fit:")
    styles.render_dataframe(pd.DataFrame(list(preserved["rows"]), columns=["Parameter", "Value", "± Error"]),
                            hide_index=True, use_container_width=True)
else:
    st.caption("No fit parameters -- the fit did not produce a result.")
styles.render_panel_close()

if two_d is not None and two_d["map"] is not None:
    _stored = two_d["stored"]
    _panel(
        "2D Gaussian — observed map with fitted model contours",
        fit_figures.map_figure(
            two_d["map"].data, two_d["map"].x, two_d["map"].y, None if _stored is None else _stored["result"].model,
            f"Intensity ({two_d['map'].unit})", two_d["map"].axis_unit, theme, styles.plotly_layout_theme(theme),
            fit_color=styles.get_fit_line_color()),
    )

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
    if is_2d:
        st.info("Graph 4 is not used for 2D Gaussian fits -- see the map below.")
    elif graph3 is not None:
        traces4 = [("Graph 3", vlsr, graph3, graph3_color, "solid")]
        if is_multi:
            if multi is not None and multi["params"]:
                traces4.append(("Composite model", vlsr, multi["curve"], styles.get_fit_line_color(), "dash"))
        elif result is not None and result.ok:
            traces4.append(("Fit" if not result.fell_back else f"Fit ({result.fit_type_used})",
                            vlsr if result.curve_x is None else result.curve_x, result.curve,
                            styles.get_fit_line_color(), "dash"))
        elif preserved is not None:
            traces4.append((f"Fit ({preserved['fit_type_used']}, previous valid)",
                            vlsr if preserved["curve_x"] is None else preserved["curve_x"], preserved["curve"],
                            styles.get_fit_line_color(), "dash"))
        fig4 = _figure(traces4, f"Intensity ({g3_unit})", window=window)
    if not is_2d:
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
    if fit_options_summary is not None:
        summary["fit_options"] = fit_options_summary
    block = getattr(result, "multi_component", None)
    if block:
        summary["multi_component"] = block  # restored by _restore_multi_from_session on Load Session
    return summary


def _json_cov(cov: np.ndarray) -> list[list[Optional[float]]]:
    """Covariance -> JSON-safe nested lists (non-finite entries become null)."""
    return [[float(c) if np.isfinite(c) else None for c in row] for row in np.asarray(cov, dtype=float)]


def _commit_2d(state: dict[str, Any]) -> None:
    """Save a 2D Gaussian fit: stage summary, audit entry, checkpoint. It has no spectrum curve, so no latest_fit."""
    stored = state["stored"]
    fit = stored["result"]
    summary = {
        "fit_type": FIT_2D_TYPE, "fit_type_requested": FIT_2D_TYPE,
        "fitted_quantity": f"2D spatial map (st.session_state.{MAP_STATE_KEY})",
        "parameters": [{"parameter": p, "value": v, "error": e} for p, v, e in fit.rows],
        "covariance": _json_cov(fit.pcov), "covariance_parameters": list(fitting_helpers.COV_LABELS_2D),
        "converged": fit.converged, "notes": list(fit.notes),
        "fit_options": {"initial_guess": list(stored["p0"]), "position_angle_unit": "degrees"},
        "map_shape": [int(n) for n in state["map"].data.shape],
    }
    st.session_state.setdefault("pipeline_data", {})[THIS_STAGE_KEY] = summary
    # A 2D fit has no curve on the velocity axis; drop any earlier spectral overlay so Page 08 cannot show an older
    # fit as if it belonged to this commit.
    st.session_state.pop("latest_fit", None)
    session_store.mark_stage_complete(THIS_STAGE_KEY)
    session_store.log_event(f"Spectral fit committed — {FIT_2D_TYPE} fitted to the {summary['map_shape'][0]} x "
                            f"{summary['map_shape'][1]} map")
    session_store.checkpoint_session("Spectral fit committed")
    if not st.session_state.get("checkpoint_error"):
        st.success("Fit saved to session and checkpointed.")


if is_2d:
    # a synthetic test map is development-only data: refuse to save it (same policy as the placeholder spectrum)
    can_save = bool(two_d and two_d["map"] is not None and not two_d["synthetic"] and two_d["stored"] is not None)
else:
    can_save = result is not None and result.ok and graph3_ready
save_col, next_col, _ = st.columns([1, 1.4, 3])
with save_col:
    save_clicked = st.button("Save fit to session", type="secondary", disabled=not can_save, use_container_width=True)
with next_col:
    # "Do this next" action -> primary (style guide §4). Enabled even without a saved fit so the pipeline can proceed.
    next_clicked = st.button("Continue to Export & Session →", type="primary", use_container_width=True,
                             key="fitting_next_btn")

if save_clicked and is_2d:
    _commit_2d(two_d)
elif save_clicked:
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
        # Page 08 plots/exports this channel-for-channel, so a window fit's curve is resampled onto the full axis
        "fit_curve": _json_curve(fitting_helpers.align_curve(vlsr, result.curve, getattr(result, "curve_x", None))),
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
