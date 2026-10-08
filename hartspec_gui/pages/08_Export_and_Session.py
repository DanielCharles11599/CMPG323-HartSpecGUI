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
#                              mark_stage_complete / completed_before,
#                              save_session / list_sessions / load_session
#                              (Save/Load/Reset are already rendered in the
#                              sidebar by utils/sidebar.py -- this page's own
#                              "Session history" panel is the separate FR-19
#                              on-page navigator, reusing the same functions)
#   utils/styles.py         -- theme tokens, inject_base_css, page header,
#                              LCP_COLOR/RCP_COLOR
#   utils/sidebar.py        -- render_sidebar (1-indexed current_stage)
#   utils/spectrum_resolution.py -- the shared "which spectrum is current?" chain, also used by Page 07
#                              (was a page-local copy here that could drift from Page 07's)
from __future__ import annotations

import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from astropy.io import fits

from utils import baseline_editor_bridge, session_store, spectrum_resolution, styles
from utils.sidebar import render_sidebar

THIS_STAGE_KEY = "08_export_and_session"
CURRENT_STAGE = 8  # 1-indexed, per utils/sidebar.py + utils/styles.py convention

st.set_page_config(page_title="HARTSPEC — Export & Session", layout="wide")
session_store.init_session_state()
render_sidebar(CURRENT_STAGE)
styles.inject_base_css()
styles.render_page_header(
    "Export & Session",
    "FR-18 / 19 / 20 — export, session history, observation log",
    CURRENT_STAGE,
    # strictly-before-this-page count, per Build Spec section 6: this page must not read 8/8 while it is 8 of 8
    session_store.completed_before(CURRENT_STAGE),
)

resolved = spectrum_resolution.resolve_spectrum(
    st.session_state,
    read_bridge=baseline_editor_bridge.read_bridge,
    fingerprint=baseline_editor_bridge.spectrum_fingerprint,
)
vlsr = resolved.vlsr
lcp, rcp = resolved.channels["LCP"], resolved.channels["RCP"]
unit = resolved.intensity_unit
# Exporting or "completing" the pipeline on synthetic data would put fabricated numbers in a file / audit trail.
export_blocked = resolved.is_placeholder

# ---------------------------------------------------------------------
# Final calibrated spectrum panel
# ---------------------------------------------------------------------
st.caption(f"Spectrum source: {resolved.source_label}")
for note in resolved.notes:
    st.warning(note)
if export_blocked:
    st.error(
        "No real spectrum is available in this session -- the chart below is synthetic placeholder data. "
        "Export and completion are disabled; complete the earlier pipeline stages first."
    )
elif not resolved.is_calibrated:
    st.warning(
        f"This spectrum is not calibrated (units: {unit}). Complete Page 5 (Calibration Dashboard) before "
        "exporting a final spectrum."
    )

# The panel is only titled "Final calibrated spectrum" when it actually is one.
styles.render_panel_open("Final calibrated spectrum" if resolved.is_calibrated else "Spectrum (not calibrated)")
theme = styles.get_theme()
fig = go.Figure()
fig.add_scatter(x=vlsr, y=lcp, mode="lines", line=dict(color=styles.LCP_COLOR, width=1.6), name="LCP")
fig.add_scatter(x=vlsr, y=rcp, mode="lines", line=dict(color=styles.RCP_COLOR, width=1.6), name="RCP")

latest_fit = st.session_state.get("latest_fit")
if latest_fit and latest_fit.get("spectrum_source") == resolved.source_key:
    # Optional overlay of the fit Page 07 last saved, if any — purely a
    # display convenience, doesn't change what gets exported below.
    fig.add_scatter(
        x=latest_fit["vlsr"], y=latest_fit["fit_curve"], mode="lines",
        line=dict(color=styles.get_fit_line_color(), width=1.6, dash="dash"),
        name=f"Fit ({latest_fit['polarization']})",
    )
elif latest_fit:
    # Overlaying a fit computed on a different spectrum (e.g. saved before calibration was applied) would draw
    # a curve on the wrong intensity scale, so it is withheld rather than shown misleadingly.
    st.caption(
        "The fit saved on Page 07 was computed on a different spectrum "
        f"({latest_fit.get('spectrum_source', 'unknown source')}) and is not overlaid. Re-run and save it on Page 07."
    )

fig.update_layout(**styles.plotly_layout_theme(theme))
fig.update_layout(
    height=260, margin=dict(l=40, r=20, t=10, b=40),
    paper_bgcolor=theme["bg-panel"], plot_bgcolor=theme["bg-panel"],
    font=dict(color=theme["text-body"]),
    legend=dict(orientation="h", y=-0.25),
    xaxis=dict(title="Vlsr (km/s)", showgrid=False, zeroline=False, color=theme["text-muted"]),
    yaxis=dict(title=f"Intensity ({unit})", showgrid=False, zeroline=False, color=theme["text-muted"]),
)
st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False}, theme=None)
styles.render_panel_close()

# ---------------------------------------------------------------------
# Export buttons — CSV / PDF / FITS (FR-18)
# ---------------------------------------------------------------------
col_csv, col_pdf, col_fits, _ = st.columns([1, 1, 1, 3])

with col_csv:
    # Column names carry the real unit (K before calibration, Jy after) -- they used to be hardcoded "_K".
    df = pd.DataFrame({"Vlsr_kms": vlsr, f"LCP_{unit}": lcp, f"RCP_{unit}": rcp})
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    if st.download_button(
        "Export CSV", csv_bytes, file_name="hartspec_spectrum.csv",
        mime="text/csv", type="secondary", use_container_width=True, disabled=export_blocked,
    ):
        session_store.log_event(f"Spectrum exported — CSV ({resolved.source_key}, {unit})")

with col_pdf:
    # TODO: confirm against design
    # No PDF-capable library is in the pinned requirements.txt (pandas /
    # plotly / astropy / numpy / scipy only). Two real options: `kaleido`
    # (static Plotly image export, then embed the PNG in a minimal PDF) or
    # `reportlab` (build a text + plot report directly). Flagging instead of
    # silently adding an unpinned dependency -- confirm which one with the
    # team, then this button wires straight into that library.
    if st.button("Export PDF", type="secondary", use_container_width=True, disabled=export_blocked):
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
        fits.Column(name="LCP", format="D", unit=unit, array=lcp),
        fits.Column(name="RCP", format="D", unit=unit, array=rcp),
    ])
    hdul = fits.HDUList([primary_hdu, fits.BinTableHDU.from_columns(cols)])
    hdul.writeto(buf)
    if st.download_button(
        "Export FITS", buf.getvalue(), file_name="hartspec_spectrum.fits",
        mime="application/fits", type="secondary", use_container_width=True, disabled=export_blocked,
    ):
        session_store.log_event(f"Spectrum exported — FITS ({resolved.source_key}, {unit})")

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
    # A damaged history entry must not crash the page before Load can validate it.
    if not isinstance(pipeline_data, dict):
        pipeline_data = {}
    fitting = pipeline_data.get("07_spectral_fitting")
    if isinstance(fitting, dict) and fitting:
        return f"{fitting.get('polarization', '')} — {fitting.get('fit_type', 'fit')} committed".strip(" —")
    bandpass = pipeline_data.get("03_bandpass_correction")
    if isinstance(bandpass, dict) and bandpass:
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
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        ts_label = _format_timestamp(payload.get("saved_at", ""))
        desc = _describe_session(payload)
        c1, c2, c3 = st.columns([2, 6, 1])
        c1.markdown(f'<span style="font-size:13px;">{ts_label}</span>', unsafe_allow_html=True)
        c2.markdown(f'<span style="font-size:13px;">{desc}</span>', unsafe_allow_html=True)
        if c3.button("Load", key=f"load_{path.name}", type="secondary"):
            try:
                # The shared action logs and navigates to the replay entry page
                # on success, before this page can process the new session.
                session_store.load_session(path)
            except (OSError, UnicodeError, ValueError) as exc:
                # The store validates before changing state; keep the current
                # reduction usable when a saved file is damaged or not a session.
                st.error(f"Could not load session; the current session is unchanged. {exc}")

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
# reads 8/8 once this fires (on later pages/visits; this page's own header
# counts only stages before it).
# ---------------------------------------------------------------------
if st.button("Mark export complete", type="primary", disabled=export_blocked):
    st.session_state.setdefault("pipeline_data", {})[THIS_STAGE_KEY] = {
        "exported": True,
        "n_channels": int(vlsr.size),
        "spectrum_source": resolved.source_key,
        "intensity_unit": unit,
    }
    session_store.mark_stage_complete(THIS_STAGE_KEY)
    session_store.log_event("Export stage marked complete")
    # Only claim the whole pipeline is done if it is -- this button previously always said so.
    not_complete = [key for key in session_store.STAGE_KEYS if key not in st.session_state["completed_stages"]]
    if not_complete:
        st.warning("Export recorded, but these stages are not complete in this session: " + ", ".join(not_complete))
    else:
        st.success("Pipeline complete — all 8 stages recorded in this session.")
