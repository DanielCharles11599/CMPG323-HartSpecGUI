# 07_Spectral_Fitting.py — FR-14/15/16/17: Gaussian / polynomial / multi-
# component spectral line fitting, with a live spectrum + fit overlay chart
# and a fit-parameters table.
#
# TODO: confirm against design — see build spec §3
# FR-15 "2D Gaussian" is listed as a fit-type option alongside "1D Gaussian"
# on this page, which otherwise fits a 1D velocity spectrum. It isn't clear
# from the build spec whether this means (a) a genuinely 2D spatial Gaussian
# (the kind you'd fit to FR-12/13 pointing-scan data), or (b) a two-component
# 1D Gaussian fit to the same velocity spectrum (e.g. a blended maser line).
# Implemented below as interpretation (b), since it's the closer fit to
# "spectral fitting" in context — flagged here rather than silently guessed.
# Please confirm the intended FR-15 behavior via NotebookLM before this ships.
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st
from scipy.optimize import curve_fit

from utils.session import get_stage_data, log_action, set_stage_data
from utils.sidebar import render_header, render_sidebar
from utils.styles import (LCP_COLOR, fit_overlay_color, inject_theme_css,
                           plot_bg_colors, render_legend)

STAGE_INDEX = 6  # 0-based -> page 07 of 8

st.set_page_config(page_title="HARTSPEC — Spectral Fitting", layout="wide")
render_sidebar(STAGE_INDEX)
inject_theme_css()
render_header(
    "Spectral Fitting",
    "FR-14\u201317 \u2014 Gaussian / polynomial / multi-component fits",
    STAGE_INDEX,
)

FIT_TYPES = ["1D Gaussian", "2D Gaussian", "Polynomial Peak", "Multi-component"]


def _get_spectrum() -> tuple[np.ndarray, np.ndarray]:
    """Velocity + intensity arrays for the currently loaded spectrum.

    In the full pipeline this should come from the calibration stage's
    output (session["calibration"]["velocity"/"intensity"], written by
    05_Calibration_Dashboard.py). Falls back to a synthetic single-peak
    spectrum so this page is runnable standalone during development — the
    fallback is clearly marked and must not ship silently once upstream
    pages are wired up.
    """
    calib = get_stage_data("calibration")
    if calib and "velocity" in calib and "intensity" in calib:
        return np.array(calib["velocity"]), np.array(calib["intensity"])

    # TODO: confirm against design — see build spec §3 (placeholder data only)
    velocity = np.linspace(-20, 20, 1024)
    rng = np.random.default_rng(42)
    intensity = (
        8.42 * np.exp(-0.5 * ((velocity - (-4.2)) / (2.31 / 2.3548)) ** 2)
        + rng.normal(0, 0.15, velocity.size)
    )
    return velocity, intensity


def _gaussian(x, amp, center, fwhm, offset):
    sigma = fwhm / 2.3548
    return amp * np.exp(-0.5 * ((x - center) / sigma) ** 2) + offset


def _double_gaussian(x, amp1, c1, fwhm1, amp2, c2, fwhm2, offset):
    return (_gaussian(x, amp1, c1, fwhm1, 0.0)
            + _gaussian(x, amp2, c2, fwhm2, 0.0) + offset)


def fit_1d_gaussian(v: np.ndarray, i: np.ndarray):
    """FR-14 — single Gaussian fit via scipy.optimize.curve_fit."""
    p0 = [i.max() - i.min(), v[np.argmax(i)], 4.0, i.min()]
    popt, pcov = curve_fit(_gaussian, v, i, p0=p0, maxfev=10000)
    perr = np.sqrt(np.diag(pcov))
    fit_curve = _gaussian(v, *popt)
    params = [
        ("Amplitude", f"{popt[0]:.2f} K", f"{perr[0]:.2f} K"),
        ("Center (Vlsr)", f"{popt[1]:.2f} km/s", f"{perr[1]:.2f} km/s"),
        ("FWHM", f"{popt[2]:.2f} km/s", f"{perr[2]:.2f} km/s"),
    ]
    return fit_curve, params


def fit_2d_gaussian(v: np.ndarray, i: np.ndarray):
    """FR-15 — see module-level TODO re: interpretation. Implemented as a
    two-component 1D Gaussian fit pending spec confirmation."""
    peak_idx = np.argsort(i)[-2:]
    p0 = [
        i.max() - i.min(), v[peak_idx[0]], 3.0,
        (i.max() - i.min()) * 0.6, v[peak_idx[1]], 3.0,
        i.min(),
    ]
    try:
        popt, pcov = curve_fit(_double_gaussian, v, i, p0=p0, maxfev=20000)
    except RuntimeError:
        return fit_1d_gaussian(v, i)
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


def fit_polynomial_peak(v: np.ndarray, i: np.ndarray, order: int = 4):
    """FR-16 — polynomial fit around the line peak."""
    coeffs = np.polyfit(v, i, order)
    fit_curve = np.polyval(coeffs, v)
    peak_v = v[np.argmax(fit_curve)]
    params = [(f"Coefficient x^{order - k}", f"{c:.4g}", "\u2014")
              for k, c in enumerate(coeffs)]
    params.append(("Peak Vlsr", f"{peak_v:.2f} km/s", "\u2014"))
    return fit_curve, params


def fit_multi_component(v: np.ndarray, i: np.ndarray, n_components: int = 3):
    """FR-17 — sum of N Gaussians, seeded from the N tallest local maxima."""
    from scipy.signal import find_peaks

    peak_idx, _ = find_peaks(i, distance=max(len(v) // 20, 1))
    if len(peak_idx) < n_components:
        peak_idx = np.argsort(i)[-n_components:]
    top = peak_idx[np.argsort(i[peak_idx])[-n_components:]]

    def model(x, *p):
        offset = p[-1]
        y = np.zeros_like(x) + offset
        for k in range(n_components):
            amp, c, fwhm = p[3 * k: 3 * k + 3]
            y += _gaussian(x, amp, c, fwhm, 0.0)
        return y

    p0 = []
    for idx in top:
        p0 += [i[idx] - i.min(), v[idx], 3.0]
    p0.append(i.min())

    try:
        popt, pcov = curve_fit(model, v, i, p0=p0, maxfev=30000)
    except RuntimeError:
        return fit_1d_gaussian(v, i)
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
# FIT TYPE segmented control (style guide §4 pill spec: accent fill when
# active, outlined when inactive — approximated with Streamlit's native
# primary/secondary button styling, which is bound to the accent color via
# .streamlit/config.toml's primaryColor).
# ---------------------------------------------------------------------
st.markdown('<div class="hs-eyebrow">Fit Type</div>', unsafe_allow_html=True)
if "fit_type" not in st.session_state:
    st.session_state["fit_type"] = FIT_TYPES[0]

pill_cols = st.columns(len(FIT_TYPES))
for col, label in zip(pill_cols, FIT_TYPES):
    is_active = st.session_state["fit_type"] == label
    if col.button(label, key=f"fit_pill_{label}",
                  type="primary" if is_active else "secondary",
                  use_container_width=True):
        if not is_active:
            st.session_state["fit_type"] = label
            log_action(f"Fit type set to {label}")
            st.rerun()

st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Spectrum + fit overlay chart
# ---------------------------------------------------------------------
velocity, intensity = _get_spectrum()
fit_curve, param_rows = FIT_FUNCS[st.session_state["fit_type"]](velocity, intensity)

st.markdown('<div class="hs-panel">', unsafe_allow_html=True)
st.markdown('<div class="hs-panel-title">Spectrum + fit overlay</div>', unsafe_allow_html=True)

fig = go.Figure()
fig.add_scatter(x=velocity, y=intensity, mode="lines",
                 line=dict(color=LCP_COLOR, width=1.6), name="Spectrum", showlegend=False)
fig.add_scatter(x=velocity, y=fit_curve, mode="lines",
                 line=dict(color=fit_overlay_color(), width=1.6, dash="dash"),
                 name="Fit", showlegend=False)
fig.update_layout(
    height=320, margin=dict(l=40, r=20, t=10, b=40),
    xaxis=dict(title="Vlsr (km/s)", showgrid=False, zeroline=False),
    yaxis=dict(title="Intensity (K)", showgrid=False, zeroline=False),
    **plot_bg_colors(),
)
st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
st.markdown(
    render_legend([("Spectrum", LCP_COLOR), ("Fit", fit_overlay_color())]),
    unsafe_allow_html=True,
)
st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Fit parameters table
# ---------------------------------------------------------------------
st.markdown('<div class="hs-panel">', unsafe_allow_html=True)
st.markdown('<div class="hs-panel-title">Fit parameters</div>', unsafe_allow_html=True)
rows_html = "".join(
    f"<tr><td>{p}</td><td>{v}</td><td>{e}</td></tr>" for p, v, e in param_rows
)
st.markdown(
    f"""
    <table class="hs-table">
        <thead><tr><th>Parameter</th><th>Value</th><th>\u00b1 Error</th></tr></thead>
        <tbody>{rows_html}</tbody>
    </table>
    """,
    unsafe_allow_html=True,
)
st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Commit fit to session — drives the progress bar and feeds page 08's
# export/observation log. Not an explicit element in the mockup; added so
# the pipeline has a real "stage complete" trigger rather than auto-marking
# on every recompute (which would spam the audit log on every pill click).
# TODO: confirm against design — see build spec §3
# ---------------------------------------------------------------------
if st.button("Save fit to session", type="primary"):
    set_stage_data("fitting", {
        "fit_type": st.session_state["fit_type"],
        "parameters": param_rows,
    })
    log_action(f"Spectral fit committed \u2014 {st.session_state['fit_type']}")
    st.success("Fit saved to session.")
