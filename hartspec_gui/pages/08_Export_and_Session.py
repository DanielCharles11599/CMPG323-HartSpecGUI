# 08_Export_and_Session.py — FR-18/19/20: spectrum export (CSV/PDF/FITS),
# session history navigator, and the running observation log.
#
# Filename matches utils/sidebar.py's STAGES list exactly
# ("pages/08_Export_and_Session.py") -- sidebar.py uses st.switch_page(),
# which only validates its target at click time, so a mismatched filename
# here would silently 404 the moment someone clicked "08" in the sidebar
# rather than failing at import time.
#
# Wired against the utils/ modules actually in the repo:
#   utils/session_store.py -- session_id, pipeline_data, audit_log (list of
#                              {"ts", "message"} dicts, not plain strings),
#                              mark_stage_complete / completed_count,
#                              save_session / list_sessions / load_session
#                              (Save/Load/Reset are already rendered in the
#                              sidebar by utils/sidebar.py -- this page's own
#                              "Session history" panel is the separate FR-19
#                              on-page navigator, reusing the same functions)
#   utils/styles.py         -- theme tokens, inject_base_css, page header,
#                              LCP_COLOR/RCP_COLOR
#   utils/sidebar.py        -- render_sidebar (1-indexed current_stage)
#   utils/baseline_editor_bridge.py -- read_bridge(), same fallback source
#                              used on Page 07 for the spectrum arrays
from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st
from astropy.io import fits

from utils import baseline_editor_bridge, session_store, styles
from utils.sidebar import render_sidebar

THIS_STAGE_KEY = "08_export_and_session"
CURRENT_STAGE = 8  # 1-indexed, per utils/sidebar.py + utils/styles.py convention
POLARIZATIONS = ("LCP", "RCP")

st.set_page_config(page_title="HARTSPEC — Export & Session", layout="wide")
session_store.init_session_state()
render_sidebar(CURRENT_STAGE)
styles.inject_base_css()
styles.render_page_header(
    "Export & Session",
    "FR-18 / 19 / 20 — export, session history, observation log",
    CURRENT_STAGE,
    session_store.completed_count(),
)


# ---------------------------------------------------------------------
# Spectrum resolution — same fallback chain as Page 07's _resolve_spectrum().
# TODO: this logic is now duplicated across 07_Spectral_Fitting.py and this
# page. Both pages independently arrived at needing the same "which stage's
# spectrum is actually current" answer -- worth promoting to a small
# utils/spectrum_resolution.py once Page 05/06's real output key is
# confirmed (see the TODO inside), rather than letting the two page-local
# copies drift apart. Left as two copies for now since this task's scope
# was pages 07/08 only, not new utils modules.
# ---------------------------------------------------------------------
def _resolve_spectrum() -> tuple[np.ndarray, dict[str, np.ndarray], str]:
    """Return (Vlsr, {"LCP": ..., "RCP": ...}, source_label)."""
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
            "Raw loaded spectrum (Page 02 — no corrections applied yet)",
        )

    # TODO: confirm against design — placeholder only, for standalone dev.
    vlsr = np.linspace(-20, 20, 1024)
    rng = np.random.default_rng(7)
    lcp = 8.4 * np.exp(-0.5 * ((vlsr + 4.2) / 1.0) ** 2) + rng.normal(0, 0.15, vlsr.size)
    rcp = 8.1 * np.exp(-0.5 * ((vlsr + 4.2) / 1.0) ** 2) + rng.normal(0, 0.15, vlsr.size)
    return (vlsr, {"LCP": lcp, "RCP": rcp}, "Synthetic placeholder spectrum — no real session data available")


vlsr, channels, source_label = _resolve_spectrum()
lcp, rcp = channels["LCP"], channels["RCP"]

# ---------------------------------------------------------------------
# Final calibrated spectrum panel
# ---------------------------------------------------------------------
st.caption(f"Spectrum source: {source_label}")

styles.render_panel_open("Final calibrated spectrum")
import plotly.graph_objects as go  # local import: only this panel needs it

theme = styles.get_theme()
fig = go.Figure()
fig.add_scatter(x=vlsr, y=lcp, mode="lines", line=dict(color=styles.LCP_COLOR, width=1.6), name="LCP")
fig.add_scatter(x=vlsr, y=rcp, mode="lines", line=dict(color=styles.RCP_COLOR, width=1.6), name="RCP")

latest_fit = st.session_state.get("latest_fit")
if latest_fit:
    # Optional overlay of the fit Page 07 last saved, if any — purely a
    # display convenience, doesn't change what gets exported below.
    fig.add_scatter(
        x=latest_fit["vlsr"], y=latest_fit["fit_curve"], mode="lines",
        line=dict(color=styles.get_fit_line_color(), width=1.6, dash="dash"),
        name=f"Fit ({latest_fit['polarization']})",
    )

fig.update_layout(
    height=260, margin=dict(l=40, r=20, t=10, b=40),
    paper_bgcolor=theme["bg-panel"], plot_bgcolor=theme["bg-panel"],
    font=dict(color=theme["text-body"]),
    legend=dict(orientation="h", y=-0.25),
    xaxis=dict(title="Vlsr (km/s)", showgrid=False, zeroline=False, color=theme["text-muted"]),
    yaxis=dict(title="Intensity (K)", showgrid=False, zeroline=False, color=theme["text-muted"]),
)
st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
styles.render_panel_close()

# ---------------------------------------------------------------------
# Export buttons — CSV / PDF / FITS (FR-18)
# ---------------------------------------------------------------------
col_csv, col_pdf, col_fits, _ = st.columns([1, 1, 1, 3])

with col_csv:
    df = pd.DataFrame({"Vlsr_kms": vlsr, "LCP_K": lcp, "RCP_K": rcp})
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    if st.download_button(
        "Export CSV", csv_bytes, file_name="hartspec_spectrum.csv",
        mime="text/csv", type="secondary", use_container_width=True,
    ):
        session_store.log_event("Spectrum exported — CSV")

with col_pdf:
    # TODO: confirm against design
    # No PDF-capable library is in the pinned requirements.txt (pandas /
    # plotly / astropy / numpy / scipy only). Two real options: `kaleido`
    # (static Plotly image export, then embed the PNG in a minimal PDF) or
    # `reportlab` (build a text + plot report directly). Flagging instead of
    # silently adding an unpinned dependency -- confirm which one with the
    # team, then this button wires straight into that library.
    if st.button("Export PDF", type="secondary", use_container_width=True):
        st.warning(
            "PDF export needs a library decision (kaleido vs reportlab) not "
            "yet in requirements.txt — confirm with the team before wiring "
            "this up. See the TODO in 08_Export_and_Session.py."
        )

with col_fits:
    buf = io.BytesIO()
    primary_hdu = fits.PrimaryHDU()
    cols = fits.ColDefs([
        fits.Column(name="VLSR", format="D", unit="km/s", array=vlsr),
        fits.Column(name="LCP", format="D", unit="K", array=lcp),
        fits.Column(name="RCP", format="D", unit="K", array=rcp),
    ])
    hdul = fits.HDUList([primary_hdu, fits.BinTableHDU.from_columns(cols)])
    hdul.writeto(buf)
    if st.download_button(
        "Export FITS", buf.getvalue(), file_name="hartspec_spectrum.fits",
        mime="application/fits", type="secondary", use_container_width=True,
    ):
        session_store.log_event("Spectrum exported — FITS")

st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------
# Session history navigator (FR-19)
# ---------------------------------------------------------------------
def _describe_session(payload: dict[str, Any]) -> str:
    """Best-effort one-line description of a saved session's contents.

    session_store.save_session()'s payload has no free-text "label" field
    (only session_id / saved_at / pipeline_data / completed_stages /
    audit_log), so the mockup's descriptive rows (e.g. "W3(OH) — HI line
    reduction") have to be assembled from whatever pipeline_data stage
    summaries happen to be present, rather than read off a stored field.
    Falls back to a plain session-id label when nothing usable is found.
    """
    pipeline_data = payload.get("pipeline_data", {})
    fitting = pipeline_data.get("07_spectral_fitting")
    if fitting:
        return f"{fitting.get('polarization', '')} — {fitting.get('fit_type', 'fit')} committed".strip(" —")
    bandpass = pipeline_data.get("03_bandpass_correction")
    if bandpass:
        return f"Bandpass — {bandpass.get('mode', 'correction')}"
    source = pipeline_data.get("01_source_browser")
    if source:
        return "Source Browser selection saved"
    return f"Session {payload.get('session_id', '')}"


def _format_timestamp(iso_ts: str) -> str:
    try:
        return datetime.fromisoformat(iso_ts).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return iso_ts or ""


st.markdown('<div class="hs-eyebrow" style="font-size:13px;text-transform:none;">Session history</div>',
            unsafe_allow_html=True)

recent_sessions = session_store.list_sessions()[:3]
if not recent_sessions:
    st.caption("No saved sessions yet — use “Save Session” in the sidebar.")
else:
    for path in recent_sessions:
        try:
            payload = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        ts_label = _format_timestamp(payload.get("saved_at", ""))
        desc = _describe_session(payload)
        c1, c2, c3 = st.columns([2, 6, 1])
        c1.markdown(f'<span style="font-size:13px;">{ts_label}</span>', unsafe_allow_html=True)
        c2.markdown(f'<span style="font-size:13px;">{desc}</span>', unsafe_allow_html=True)
        if c3.button("Load", key=f"load_{path.name}", type="secondary"):
            session_store.load_session(path)
            session_store.log_event(f"Session loaded — {path.stem}")
            st.rerun()

st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Observation Log Panel (FR-20) — real audit trail, not static text.
# audit_log entries are {"ts": "HH:MM:SS", "message": str} dicts, per
# session_store.log_event() -- not plain strings.
# ---------------------------------------------------------------------
styles.render_panel_open("Observation Log Panel (FR-20)")
audit_entries = st.session_state.get("audit_log", [])
log_text = "\n".join(f"{entry['ts']} {entry['message']}" for entry in audit_entries)
st.code(log_text or "No actions logged yet this session.", language=None)
styles.render_panel_close()

# ---------------------------------------------------------------------
# Mark export stage complete — the last stage key, so the progress bar
# reads 8/8 once this fires.
# ---------------------------------------------------------------------
if st.button("Mark export complete", type="primary"):
    st.session_state.setdefault("pipeline_data", {})[THIS_STAGE_KEY] = {
        "exported": True,
        "n_channels": int(vlsr.size),
    }
    session_store.mark_stage_complete(THIS_STAGE_KEY)
    session_store.log_event("Export stage marked complete")
    st.success("Pipeline complete — all 8 stages recorded in this session.")
