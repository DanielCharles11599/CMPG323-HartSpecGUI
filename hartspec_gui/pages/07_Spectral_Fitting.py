# 07_Spectral_Fitting.py — FR-14/15/16/17: Gaussian / polynomial / multi-
# component spectral line fitting, with a spectrum + fit overlay chart and a
# fit-parameters table.
#
# Wired against the utils/ modules actually in the repo:
#   utils/session_store.py     -- session_id, pipeline_data, audit log, stage
#                                  completion (init_session_state / log_event /
#                                  mark_stage_complete / completed_count)
#   utils/styles.py             -- theme tokens, inject_base_css, page header
#                                  (title + progress bar), LCP_COLOR/RCP_COLOR,
#                                  get_fit_line_color(), render_badge
#   utils/sidebar.py            -- render_sidebar (nav + theme toggle +
#                                  Save/Load/Reset, 1-indexed current_stage)
#   utils/baseline_editor_bridge.py -- read_bridge(), the real, confirmed
#                                  source of the Page 4 baseline-flattened
#                                  spectrum (see _resolve_spectrum below)
#
# No clc/Gaussf.py call is made directly. Following the same pattern already
# established in utils/baseline_polynomial_adapter.py (which avoids calling
# clc/Blocks.py directly because it has input()/plotting/file side effects),
# fitting here is a GUI-safe reproduction of standard Gaussian/polynomial
# fitting via scipy.optimize.curve_fit -- not a reinterpretation of any CLC
# algorithm, since clc/Gaussf.py's exact callable signature wasn't available
# to confirm against. Flagging this choice rather than guessing at
# clc.Gaussf's interface and calling it blind.
#
# TODO: confirm against design
# FR-15 "2D Gaussian" is listed as a fit-type option alongside "1D Gaussian"
# on this otherwise-1D (velocity spectrum) page. Two readings are possible:
# (a) a genuinely 2D spatial Gaussian (the kind fit to FR-12/13 pointing-scan
# data), or (b) a two-component 1D Gaussian fit to the same velocity
# spectrum (e.g. a blended maser line). Implemented below as (b), since it's
# the closer fit to "spectral fitting" in context -- please confirm the
# intended FR-15 behavior before this ships.
from __future__ import annotations

from typing import Any

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from scipy.optimize import curve_fit
from scipy.signal import find_peaks

from utils import baseline_editor_bridge, session_store, styles
from utils.sidebar import render_sidebar

THIS_STAGE_KEY = "07_spectral_fitting"
CURRENT_STAGE = 7  # 1-indexed, per utils/sidebar.py + utils/styles.py convention

FIT_TYPES = ["1D Gaussian", "2D Gaussian", "Polynomial Peak", "Multi-component"]
POLARIZATIONS = ("LCP", "RCP")

st.set_page_config(page_title="HARTSPEC — Spectral Fitting", layout="wide")
session_store.init_session_state()
render_sidebar(CURRENT_STAGE)
styles.inject_base_css()
styles.render_page_header(
    "Spectral Fitting",
    "FR-14–17 — Gaussian / polynomial / multi-component fits",
    CURRENT_STAGE,
    session_store.completed_count(),
)


# ---------------------------------------------------------------------
# Spectrum resolution
# ---------------------------------------------------------------------
def _resolve_spectrum() -> tuple[np.ndarray, dict[str, np.ndarray], str]:
    """Return (Vlsr, {"LCP": ..., "RCP": ...}, source_label).

    Fallback chain, most-processed source first:

    1. st.session_state["calibrated_spectrum"] -- TODO: confirm against
       design. No uploaded Page 05/06 module currently exposes the exact
       session_state key its final calibrated Vlsr/LCP/RCP output is written
       under (calibration_logic.py returns PWV/ATcor/PSS *coefficients*, not
       an already-calibrated spectrum array). "calibrated_spectrum" is a
       placeholder name chosen to match this codebase's existing
       "loaded_spectra" naming style -- confirm the real key with whoever
       wrote 05_Calibration_Dashboard.py / 06_Pointing_Correction.py.
    2. The Page 4 Dash bridge's baseline-flattened spectrum, via
       utils.baseline_editor_bridge.read_bridge(session_id). This IS a real,
       confirmed contract (see that module, and flatten_spectrum_for_orders()
       in utils/baseline_polynomial_adapter.py).
    3. The raw first entry of st.session_state["loaded_spectra"] (Page 02) --
       uncorrected, but lets the page still function if the user jumps
       straight to Page 07.
    4. A synthetic single-peak spectrum, only so this page is runnable
       standalone during development. Must not ship silently once 1/2/3
       above are reliably populated.
    """
    calibrated = st.session_state.get("calibrated_spectrum")
    if calibrated and {"Vlsr", "LCP", "RCP"} <= calibrated.keys():
        return (
            np.asarray(calibrated["Vlsr"], dtype=float),
            {pol: np.asarray(calibrated[pol], dtype=float) for pol in POLARIZATIONS},
            "Calibrated spectrum (Stage 05/06 output)",
        )

    bridge_state = baseline_editor_bridge.read_bridge(st.session_state.get("session_id", ""))
    flattened = (bridge_state or {}).get("flattened_spectrum")
    if flattened and {"Vlsr", "LCP", "RCP"} <= flattened.keys():
        return (
            np.asarray(flattened["Vlsr"], dtype=float),
            {pol: np.asarray(flattened[pol], dtype=float) for pol in POLARIZATIONS},
            "Baseline-flattened spectrum (Page 4 bridge — calibration not yet applied)",
        )

    loaded = st.session_state.get("loaded_spectra") or []
    if loaded and {"Vlsr", "LCP", "RCP"} <= loaded[0].keys():
        spec = loaded[0]
        return (
            np.asarray(spec["Vlsr"], dtype=float),
            {pol: np.asarray(spec[pol], dtype=float) for pol in POLARIZATIONS},
            "Raw loaded spectrum (Page 02 — no bandpass/baseline correction applied yet)",
        )

    # TODO: confirm against design — placeholder only, for standalone dev.
    vlsr = np.linspace(-20, 20, 1024)
    rng = np.random.default_rng(42)
    base = 8.42 * np.exp(-0.5 * ((vlsr + 4.2) / (2.31 / 2.3548)) ** 2)
    return (
        vlsr,
        {
            "LCP": base + rng.normal(0, 0.15, vlsr.size),
            "RCP": base * 0.96 + rng.normal(0, 0.15, vlsr.size),
        },
        "Synthetic placeholder spectrum — no real session data available",
    )


# ---------------------------------------------------------------------
# Fit models — GUI-safe scipy reproductions (see module header note)
# ---------------------------------------------------------------------
def _gaussian(x, amp, center, fwhm, offset):
    sigma = fwhm / 2.3548
    return amp * np.exp(-0.5 * ((x - center) / sigma) ** 2) + offset


def _double_gaussian(x, amp1, c1, fwhm1, amp2, c2, fwhm2, offset):
    return (_gaussian(x, amp1, c1, fwhm1, 0.0)
            + _gaussian(x, amp2, c2, fwhm2, 0.0) + offset)


def fit_1d_gaussian(v: np.ndarray, y: np.ndarray):
    """FR-14 — single Gaussian fit."""
    p0 = [y.max() - y.min(), v[np.argmax(y)], 4.0, y.min()]
    popt, pcov = curve_fit(_gaussian, v, y, p0=p0, maxfev=10000)
    perr = np.sqrt(np.diag(pcov))
    fit_curve = _gaussian(v, *popt)
    params = [
        ("Amplitude", f"{popt[0]:.2f} K", f"{perr[0]:.2f} K"),
        ("Center (Vlsr)", f"{popt[1]:.2f} km/s", f"{perr[1]:.2f} km/s"),
        ("FWHM", f"{popt[2]:.2f} km/s", f"{perr[2]:.2f} km/s"),
    ]
    return fit_curve, params


def fit_2d_gaussian(v: np.ndarray, y: np.ndarray):
    """FR-15 — see module-level TODO re: interpretation. Implemented as a
    two-component 1D Gaussian fit pending spec confirmation."""
    peak_idx = np.argsort(y)[-2:]
    p0 = [
        y.max() - y.min(), v[peak_idx[0]], 3.0,
        (y.max() - y.min()) * 0.6, v[peak_idx[1]], 3.0,
        y.min(),
    ]
    try:
        popt, pcov = curve_fit(_double_gaussian, v, y, p0=p0, maxfev=20000)
    except RuntimeError:
        return fit_1d_gaussian(v, y)
    perr = np.sqrt(np.diag(pcov))
    fit_curve = _double_gaussian(v, *popt)
    params = [
        ("Amplitude 1", f"{popt[0]:.2f} K", f"{perr[0]:.2f} K"),
        ("Center 1 (Vlsr)", f"{popt[1]:.2f} km/s", f"{perr[1]:.2f} km/s"),
        ("FWHM 1", f"{popt[2]:.2f} km/s", f"{perr[2]:.2f} km/s"),
        ("Amplitude 2", f"{popt[3]:.2f} K", f"{perr[3]:.2f} K"),
        ("Center 2 (Vlsr)", f"{popt[4]:.2f} km/s", f"{perr[4]:.2f} km/s"),
        ("FWHM 2", f"{popt[5]:.2f} km/s", f"{perr[5]:.2f} km/s"),
    ]
    return fit_curve, params


def fit_polynomial_peak(v: np.ndarray, y: np.ndarray, order: int = 4):
    """FR-16 — polynomial fit around the line peak."""
    coeffs = np.polyfit(v, y, order)
    fit_curve = np.polyval(coeffs, v)
    peak_v = v[np.argmax(fit_curve)]
    params = [(f"Coefficient x^{order - k}", f"{c:.4g}", "—")
              for k, c in enumerate(coeffs)]
    params.append(("Peak Vlsr", f"{peak_v:.2f} km/s", "—"))
    return fit_curve, params


def fit_multi_component(v: np.ndarray, y: np.ndarray, n_components: int = 3):
    """FR-17 — sum of N Gaussians, seeded from the N tallest local maxima."""
    peak_idx, _ = find_peaks(y, distance=max(len(v) // 20, 1))
    if len(peak_idx) < n_components:
        peak_idx = np.argsort(y)[-n_components:]
    top = peak_idx[np.argsort(y[peak_idx])[-n_components:]]

    def model(x, *p):
        offset = p[-1]
        out = np.zeros_like(x) + offset
        for k in range(n_components):
            amp, c, fwhm = p[3 * k: 3 * k + 3]
            out += _gaussian(x, amp, c, fwhm, 0.0)
        return out

    p0 = []
    for idx in top:
        p0 += [y[idx] - y.min(), v[idx], 3.0]
    p0.append(y.min())

    try:
        popt, pcov = curve_fit(model, v, y, p0=p0, maxfev=30000)
    except RuntimeError:
        return fit_1d_gaussian(v, y)
    perr = np.sqrt(np.diag(pcov))
    fit_curve = model(v, *popt)
    params = []
    for k in range(n_components):
        amp, c, fwhm = popt[3 * k: 3 * k + 3]
        ea, ec, ef = perr[3 * k: 3 * k + 3]
        params.append((f"Amplitude {k + 1}", f"{amp:.2f} K", f"{ea:.2f} K"))
        params.append((f"Center {k + 1} (Vlsr)", f"{c:.2f} km/s", f"{ec:.2f} km/s"))
        params.append((f"FWHM {k + 1}", f"{fwhm:.2f} km/s", f"{ef:.2f} km/s"))
    return fit_curve, params


FIT_FUNCS = {
    "1D Gaussian": fit_1d_gaussian,
    "2D Gaussian": fit_2d_gaussian,
    "Polynomial Peak": fit_polynomial_peak,
    "Multi-component": fit_multi_component,
}

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
# Spectrum + fit overlay chart
# ---------------------------------------------------------------------
vlsr, channels, source_label = _resolve_spectrum()
y = channels[polarization]
fit_curve, param_rows = FIT_FUNCS[fit_type](vlsr, y)

st.caption(f"Spectrum source: {source_label}")

styles.render_panel_open("Spectrum + fit overlay")
fig = go.Figure()
fig.add_scatter(
    x=vlsr, y=y, mode="lines",
    line=dict(color=styles.LCP_COLOR if polarization == "LCP" else styles.RCP_COLOR, width=1.6),
    name=f"Spectrum ({polarization})",
)
fig.add_scatter(
    x=vlsr, y=fit_curve, mode="lines",
    line=dict(color=styles.get_fit_line_color(), width=1.6, dash="dash"),
    name="Fit",
)
theme = styles.get_theme()
fig.update_layout(
    height=320, margin=dict(l=40, r=20, t=10, b=40),
    paper_bgcolor=theme["bg-panel"], plot_bgcolor=theme["bg-panel"],
    font=dict(color=theme["text-body"]),
    legend=dict(orientation="h", y=-0.2),
    xaxis=dict(title="Vlsr (km/s)", showgrid=False, zeroline=False, color=theme["text-muted"]),
    yaxis=dict(title="Intensity (K)", showgrid=False, zeroline=False, color=theme["text-muted"]),
)
st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
styles.render_panel_close()

# ---------------------------------------------------------------------
# Fit parameters table
# ---------------------------------------------------------------------
styles.render_panel_open("Fit parameters")
import pandas as pd  # local import: only this panel needs it

param_df = pd.DataFrame(param_rows, columns=["Parameter", "Value", "± Error"])
st.dataframe(param_df, hide_index=True, use_container_width=True)
styles.render_panel_close()

# ---------------------------------------------------------------------
# Commit fit to session — drives the progress bar and feeds Page 08's
# export/observation log. Not an explicit element in the mockup; added so
# the pipeline has a real "stage complete" trigger rather than auto-marking
# on every recompute (which would spam the audit log on every pill click).
# TODO: confirm against design
# ---------------------------------------------------------------------
def _stage_summary(fit_type: str, polarization: str, params: list[tuple[str, str, str]]) -> dict[str, Any]:
    """Lightweight, JSON-serializable summary for pipeline_data -- mirrors
    bandpass_correction_logic.stage_summary()'s pattern of NOT duplicating
    full spectrum/fit arrays into session persistence."""
    return {
        "fit_type": fit_type,
        "polarization": polarization,
        "parameters": [{"parameter": p, "value": v, "error": e} for p, v, e in params],
        "n_channels": int(vlsr.size),
        "vlsr_range_kms": [float(vlsr.min()), float(vlsr.max())] if vlsr.size else [],
    }


if st.button("Save fit to session", type="primary"):
    st.session_state.setdefault("pipeline_data", {})[THIS_STAGE_KEY] = _stage_summary(
        fit_type, polarization, param_rows
    )
    # Full fit curve kept in session_state directly (not pipeline_data) for
    # Page 08 to reuse if it wants to overlay the fit on the export chart --
    # same "summaries in pipeline_data, arrays in session_state" split used
    # by Page 02/03/04.
    st.session_state["latest_fit"] = {
        "fit_type": fit_type,
        "polarization": polarization,
        "vlsr": vlsr.tolist(),
        "fit_curve": fit_curve.tolist(),
    }
    session_store.mark_stage_complete(THIS_STAGE_KEY)
    session_store.log_event(f"Spectral fit committed — {fit_type} ({polarization})")
    st.success("Fit saved to session.")
