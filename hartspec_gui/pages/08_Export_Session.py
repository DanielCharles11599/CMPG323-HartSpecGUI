# 08_Export_Session.py — FR-18/19/20: spectrum export (CSV/PDF/FITS),
# session history navigator, and the running observation log.
from __future__ import annotations

import io
import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from astropy.io import fits

from utils.session import (get_stage_data, list_saved_sessions, load_session,
                            log_action, set_stage_data)
from utils.sidebar import render_header, render_sidebar
from utils.styles import (LCP_COLOR, RCP_COLOR, inject_theme_css,
                           plot_bg_colors, render_legend)

STAGE_INDEX = 7  # 0-based -> page 08 of 8

st.set_page_config(page_title="HARTSPEC — Export & Session", layout="wide")
render_sidebar(STAGE_INDEX)
inject_theme_css()
render_header(
    "Export & Session",
    "FR-18 / 19 / 20 \u2014 export, session history, observation log",
    STAGE_INDEX,
)


def _get_final_spectrum():
    """LCP/RCP calibrated spectrum for export.

    In the full pipeline this should come from session["calibration"]
    ("velocity"/"lcp"/"rcp"), written by 05_Calibration_Dashboard.py.
    Falls back to synthetic data for standalone development, matching the
    same pattern used on page 07 — must not ship silently once upstream
    pages are wired up.
    """
    calib = get_stage_data("calibration")
    if calib and {"velocity", "lcp", "rcp"} <= calib.keys():
        return (np.array(calib["velocity"]), np.array(calib["lcp"]), np.array(calib["rcp"]))
    # TODO: confirm against design — see build spec §3 (placeholder data only)
    velocity = np.linspace(-20, 20, 1024)
    rng = np.random.default_rng(7)
    lcp = 8.4 * np.exp(-0.5 * ((velocity + 4.2) / 1.0) ** 2) + rng.normal(0, 0.15, velocity.size)
    rcp = 8.1 * np.exp(-0.5 * ((velocity + 4.2) / 1.0) ** 2) + rng.normal(0, 0.15, velocity.size)
    return velocity, lcp, rcp


velocity, lcp, rcp = _get_final_spectrum()

# ---------------------------------------------------------------------
# Final calibrated spectrum panel
# ---------------------------------------------------------------------
st.markdown('<div class="hs-panel">', unsafe_allow_html=True)
st.markdown('<div class="hs-panel-title">Final calibrated spectrum</div>', unsafe_allow_html=True)

fig = go.Figure()
fig.add_scatter(x=velocity, y=lcp, mode="lines", line=dict(color=LCP_COLOR, width=1.6),
                 name="LCP", showlegend=False)
fig.add_scatter(x=velocity, y=rcp, mode="lines", line=dict(color=RCP_COLOR, width=1.6),
                 name="RCP", showlegend=False)
fig.update_layout(
    height=260, margin=dict(l=40, r=20, t=10, b=40),
    xaxis=dict(title="Vlsr (km/s)", showgrid=False, zeroline=False),
    yaxis=dict(title="Intensity (K)", showgrid=False, zeroline=False),
    **plot_bg_colors(),
)
st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
st.markdown(render_legend([("LCP", LCP_COLOR), ("RCP", RCP_COLOR)]), unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Export buttons — CSV / PDF / FITS (FR-18)
# ---------------------------------------------------------------------
col_csv, col_pdf, col_fits, _ = st.columns([1, 1, 1, 3])

with col_csv:
    df = pd.DataFrame({"velocity_kms": velocity, "lcp_K": lcp, "rcp_K": rcp})
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    if st.download_button("Export CSV", csv_bytes, file_name="hartspec_spectrum.csv",
                           mime="text/csv", type="secondary", use_container_width=True):
        log_action("Spectrum exported \u2014 CSV")

with col_pdf:
    # TODO: confirm against design — see build spec §3
    # No PDF-capable library is in the pinned requirements.txt (pandas /
    # plotly / astropy / numpy / scipy only). Two real options: `kaleido`
    # (static Plotly image export, then embed the PNG in a minimal PDF) or
    # `reportlab` (build a text + plot report directly). Flagging instead
    # of silently adding an unpinned dependency — confirm which one with
    # the team, then this button wires straight into that library.
    if st.button("Export PDF", type="secondary", use_container_width=True):
        st.warning(
            "PDF export needs a library decision (kaleido vs reportlab) not "
            "yet in requirements.txt \u2014 confirm with the team before wiring "
            "this up. See the TODO in 08_Export_Session.py."
        )

with col_fits:
    buf = io.BytesIO()
    primary_hdu = fits.PrimaryHDU()
    cols = fits.ColDefs([
        fits.Column(name="VELOCITY", format="D", unit="km/s", array=velocity),
        fits.Column(name="LCP", format="D", unit="K", array=lcp),
        fits.Column(name="RCP", format="D", unit="K", array=rcp),
    ])
    hdul = fits.HDUList([primary_hdu, fits.BinTableHDU.from_columns(cols)])
    hdul.writeto(buf)
    if st.download_button("Export FITS", buf.getvalue(), file_name="hartspec_spectrum.fits",
                           mime="application/fits", type="secondary", use_container_width=True):
        log_action("Spectrum exported \u2014 FITS")

st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Session history navigator (FR-19)
# ---------------------------------------------------------------------
st.markdown(
    '<div class="hs-eyebrow" style="font-size:13px;text-transform:none;">Session history</div>',
    unsafe_allow_html=True,
)

recent = list_saved_sessions(limit=3)
if not recent:
    st.caption("No saved sessions yet \u2014 use \u201cSave Session\u201d in the sidebar.")
else:
    for path in recent:
        payload = json.loads(path.read_text())
        ts = payload.get("session_id", path.stem)
        desc = payload.get("label", "Session")
        c1, c2, c3 = st.columns([2, 6, 1])
        c1.markdown(f'<span style="font-size:13px;">{ts}</span>', unsafe_allow_html=True)
        c2.markdown(f'<span style="font-size:13px;">{desc}</span>', unsafe_allow_html=True)
        if c3.button("Load", key=f"load_{path.name}", type="secondary"):
            load_session(path)
            st.rerun()

st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Observation Log Panel (FR-20) — real audit trail, not static text
# ---------------------------------------------------------------------
st.markdown('<div class="hs-panel">', unsafe_allow_html=True)
st.markdown('<div class="hs-panel-title">Observation Log Panel (FR-20)</div>', unsafe_allow_html=True)
log_text = "\n".join(st.session_state.get("audit_log", [])) or "No actions logged yet this session."
st.markdown(f'<div class="hs-log">{log_text}</div>', unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Mark export stage complete — the last stage key, so the progress bar
# reads 8/8 once this fires.
# ---------------------------------------------------------------------
if st.button("Mark export complete", type="primary"):
    set_stage_data("export", {"exported": True})
    log_action("Export stage marked complete")
    st.success("Pipeline complete \u2014 all 8 stages recorded in this session.")
