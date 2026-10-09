# 08_Export_and_Session.py — FR-18/19/20: spectrum export (CSV + graphs PDF), session history navigator, and the
# running observation log.
#
# System-owner changes in this revision:
#   * CSV is the only data export (FITS and TXT removed). It carries BOTH polarisations (LCP and RCP), the pair
#     average, Graph 3, the fit and the metadata as constant columns -- everything readable back from the one file.
#   * The PDF is graphs only (no tables, parameter values or log text).
#   * The observation log panel has a fixed height and scrolls, so the end of the page stays reachable.
#   # TODO: confirm against design -- the owners' extra CSV column list is still pending; see utils/export_logic.py.
#
# Filename matches utils/sidebar.py's STAGES list exactly ("pages/08_Export_and_Session.py") -- sidebar.py uses
# st.switch_page(), which only validates its target at click time, so a mismatched filename here would silently 404.
#
# Wired against the utils/ modules actually in the repo:
#   utils/session_store.py        -- session_id, pipeline_data, audit_log ({"ts","message"} dicts), stage completion,
#                                    save_session / list_sessions / load_session (FR-19 on-page navigator)
#   utils/styles.py               -- theme tokens, inject_base_css, page header, LCP_COLOR/RCP_COLOR
#   utils/sidebar.py              -- render_sidebar (1-indexed current_stage)
#   utils/spectrum_resolution.py  -- the shared "which spectrum is current?" chain, also used by Pages 06 and 07
#   utils/fitting_inputs.py       -- PSS / pointing correction / Graph 3 arithmetic, shared with Page 07
#   utils/export_logic.py         -- CSV and PDF builders (pure, unit-tested)
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from utils import (
    baseline_editor_bridge, export_logic, export_preview_logic, export_preview_ui, fitting_inputs, session_store,
    spectrum_resolution, styles,
)
from utils.sidebar import render_sidebar
from utils.observation_log_ui import render_observation_log

THIS_STAGE_KEY = "08_export_and_session"
CURRENT_STAGE = 8  # 1-indexed, per utils/sidebar.py + utils/styles.py convention
LOG_PANEL_HEIGHT = 240  # px; the log scrolls inside this (UAT feedback: limit the log panel's height)
FIT_STAGE_KEY = "07_spectral_fitting"

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
theme = styles.get_theme()

# ---------------------------------------------------------------------
# Resolve everything that goes into the export
# ---------------------------------------------------------------------
resolved = spectrum_resolution.resolve_spectrum(
    st.session_state,
    read_bridge=baseline_editor_bridge.read_bridge,
    fingerprint=baseline_editor_bridge.spectrum_fingerprint,
)
vlsr = resolved.vlsr
lcp, rcp = resolved.channels["LCP"], resolved.channels["RCP"]
unit = resolved.intensity_unit
pipeline_data = st.session_state.get("pipeline_data", {})
pss = fitting_inputs.pss_from_pipeline(pipeline_data)
pointing_factor = fitting_inputs.pointing_factor_from_pipeline(pipeline_data)
average, overall_mean = fitting_inputs.pair_average(lcp, rcp)

# FR-18's legacy RMS/peak statistics are calculated on the CLC final Stokes-I path.
# Keep them separate from the existing Graph 3/export arithmetic: this is a read-only
# preview derived from committed Pages 04-06 data and never rewrites spectrum/session state.
export_preview = export_preview_logic.preview_from_pipeline(
    st.session_state,
    read_bridge=baseline_editor_bridge.read_bridge,
    fingerprint=baseline_editor_bridge.spectrum_fingerprint,
)

# Exporting or "completing" the pipeline on synthetic data would put fabricated numbers in a file / audit trail.
export_blocked = resolved.is_placeholder

# Graph 3 only from the pre-calibration spectrum with real PSS + pointing inputs (same rule as Page 07).
graph3_ready = pss is not None and pointing_factor is not None and not resolved.is_placeholder \
    and not resolved.is_calibrated
graph3 = fitting_inputs.graph3(lcp, rcp, pss.value, pointing_factor) if graph3_ready else None
source_key = fitting_inputs.graph3_source_key(resolved.source_key, pss.value, pointing_factor) if graph3_ready else ""

# A saved fit is only used if it was computed on exactly this Graph 3 (same spectrum, PSS and pointing correction).
latest_fit = st.session_state.get("latest_fit")
fit_matches = bool(graph3_ready and latest_fit and latest_fit.get("spectrum_source") == source_key
                   and len(latest_fit.get("fit_curve", [])) == vlsr.size)
fit_curve = np.asarray(latest_fit["fit_curve"], dtype=float) if fit_matches else None
fit_summary = pipeline_data.get(FIT_STAGE_KEY) if fit_matches else None

# ---------------------------------------------------------------------
# Notices
# ---------------------------------------------------------------------
st.caption(f"Spectrum source: {resolved.source_label}")
for note in resolved.notes:
    st.warning(note)
if export_blocked:
    st.error(
        "No real spectrum is available in this session -- the charts below are synthetic placeholder data. "
        "Export and completion are disabled; complete the earlier pipeline stages first."
    )
if not graph3_ready and not export_blocked:
    st.warning(
        "Graph 3 (and its fit) is not included in the export: it needs the PSS from Page 05 and the pointing "
        "correction from Page 06, applied to the pre-calibration spectrum."
    )
elif latest_fit and not fit_matches and graph3_ready:
    st.caption("The fit saved on Page 07 was computed on different data and is not included. Re-run and save it on "
               "Page 07.")


# ---------------------------------------------------------------------
# Charts (these are the graphs the PDF contains)
# ---------------------------------------------------------------------
def _chart(title: str, traces: list[tuple[str, Any, Any, str, str]], y_title: str, height: int = 260) -> None:
    """Themed full-width panel with one chart; backgrounds follow bg-panel (Plotly doesn't inherit them)."""
    styles.render_panel_open(title)
    fig = go.Figure()
    for name, x, y, color, dash in traces:
        fig.add_scatter(x=x, y=y, mode="lines", line=dict(color=color, width=1.6, dash=dash), name=name)
    fig.update_layout(**styles.plotly_layout_theme(theme))
    fig.update_layout(
        height=height, margin=dict(l=40, r=20, t=10, b=40),
        paper_bgcolor=theme["bg-panel"], plot_bgcolor=theme["bg-panel"],
        font=dict(color=theme["text-body"]),
        legend=dict(orientation="h", y=-0.25),
        xaxis=dict(title="Vlsr (km/s)", showgrid=False, zeroline=False, color=theme["text-muted"]),
        yaxis=dict(title=y_title, showgrid=False, zeroline=False, color=theme["text-muted"]),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False}, theme=None)
    styles.render_panel_close()


_chart("LCP and RCP", [("LCP", vlsr, lcp, styles.LCP_COLOR, "solid"), ("RCP", vlsr, rcp, styles.RCP_COLOR, "solid")],
       f"Intensity ({unit})")
export_preview_ui.render_export_preview(export_preview, theme=theme)
if graph3 is not None:
    traces = [("Graph 3", vlsr, graph3, theme["accent"], "solid")]
    if fit_curve is not None:
        traces.append((f"Fit ({latest_fit['fit_type']})", vlsr, fit_curve, styles.get_fit_line_color(), "dash"))
    _chart("Final spectrum — [(LCP + RCP) × PSS] + Pointing Correction", traces,
           f"Intensity ({fitting_inputs.GRAPH3_UNIT})")


# ---------------------------------------------------------------------
# Export buttons — CSV (all numbers) and PDF (graphs only) (FR-18)
# ---------------------------------------------------------------------
def _cached_bytes(kind: str, signature_parts: list[Any], build: Callable[[], bytes]) -> bytes:
    """Build once per distinct input and keep the bytes in session_state.

    st.download_button needs its data up front on every rerun; rebuilding a PDF each time would make every click on
    the page wait for matplotlib. The signature hashes the actual numbers, so any change rebuilds it.
    """
    digest = hashlib.md5()
    for part in signature_parts:
        digest.update(np.asarray(part).tobytes() if isinstance(part, np.ndarray) else repr(part).encode())
    key, cache = digest.hexdigest(), st.session_state.setdefault("export_cache", {})
    entry = cache.get(kind)
    if not entry or entry[0] != key:
        cache[kind] = (key, build())
    return cache[kind][1]


metadata = export_logic.build_metadata(
    spectrum=st.session_state.get("loaded_spectrum"),
    spectrum_source=resolved.source_key,
    intensity_unit=unit,
    pss=pss,
    pointing_factor=pointing_factor,
    fit_summary=fit_summary,
)
csv_bytes = export_logic.build_export_csv(
    vlsr=vlsr, lcp=lcp, rcp=rcp, average=average, unit=unit, calibrated=graph3, fit_curve=fit_curve,
    metadata=metadata,
)


def _graph_specs() -> list[export_logic.GraphSpec]:
    """The graphs the PDF contains: the ones on Pages 06/07 (no numbers tables, no metadata)."""
    specs = [
        export_logic.GraphSpec("LCP", f"Intensity ({unit})", [export_logic.GraphTrace("LCP", vlsr, lcp,
                                                                                     styles.LCP_COLOR)]),
        export_logic.GraphSpec("RCP", f"Intensity ({unit})", [export_logic.GraphTrace("RCP", vlsr, rcp,
                                                                                     styles.RCP_COLOR)]),
        export_logic.GraphSpec("Average of each LCP/RCP pair — (LCP + RCP) / 2", f"Intensity ({unit})",
                               [export_logic.GraphTrace("(LCP + RCP) / 2", vlsr, average, "#587BBD")],
                               hline=overall_mean, hline_label="Overall average"),
    ]
    if pointing_factor is not None:
        specs.append(export_logic.GraphSpec(
            "(LCP + RCP) × Pointing Correction", f"Intensity ({unit})",
            [export_logic.GraphTrace("(LCP + RCP) × PC", vlsr, fitting_inputs.pointing_product(lcp, rcp,
                                                                                               pointing_factor),
                                     "#587BBD")]))
    if graph3 is not None:
        graph3_unit = fitting_inputs.GRAPH3_UNIT
        specs.append(export_logic.GraphSpec(
            "Graph 3 — [(LCP + RCP) × PSS] + Pointing Correction", f"Intensity ({graph3_unit})",
            [export_logic.GraphTrace("Graph 3", vlsr, graph3, "#587BBD")]))
        if fit_curve is not None:
            specs.append(export_logic.GraphSpec(
                "Graph 4 — Fit of Graph 3", f"Intensity ({graph3_unit})",
                [export_logic.GraphTrace("Graph 3", vlsr, graph3, "#587BBD"),
                 export_logic.GraphTrace("Fit", vlsr, fit_curve, export_logic.FIT_COLOR_PRINT, dashed=True)]))
    return specs


pdf_bytes: Optional[bytes] = None
pdf_error: Optional[str] = None
if not export_blocked:
    try:
        pdf_bytes = _cached_bytes(
            "pdf", [vlsr, lcp, rcp, graph3 if graph3 is not None else "", fit_curve if fit_curve is not None else "",
                    pointing_factor, resolved.source_key, unit, metadata["source_name"]],
            lambda: export_logic.build_graphs_pdf(_graph_specs(), "HARTSPEC — " + (metadata["source_name"] or
                                                                                  "spectrum")),
        )
    except ImportError:
        pdf_error = "PDF export needs the `matplotlib` package, which is not in requirements.txt yet."
    except Exception as exc:  # noqa: BLE001 -- shown to the user instead of crashing the page
        pdf_error = f"The PDF could not be built: {exc}"

col_csv, col_pdf, _ = st.columns([1, 1.3, 3])
with col_csv:
    if st.download_button(
        "Export CSV", csv_bytes, file_name="hartspec_spectrum.csv", mime="text/csv", type="secondary",
        use_container_width=True, disabled=export_blocked,
    ):
        session_store.log_event(f"Spectrum exported — CSV ({resolved.source_key}, LCP + RCP, {unit})")
with col_pdf:
    if st.download_button(
        "Export graphs (PDF)", pdf_bytes or b"", file_name="hartspec_graphs.pdf", mime="application/pdf",
        type="secondary", use_container_width=True, disabled=export_blocked or pdf_bytes is None,
    ):
        session_store.log_event(f"Graphs exported — PDF ({resolved.source_key})")
if pdf_error:
    st.caption(pdf_error)

st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------
# Session history navigator (FR-19)
# ---------------------------------------------------------------------
def _describe_session(payload: dict[str, Any]) -> str:
    """Best-effort one-line description of a saved session's contents.

    save_session()'s payload has no free-text "label" field, so the mockup's descriptive rows (e.g. "W3(OH) — HI line
    reduction") are assembled from whichever pipeline_data stage summaries are present. Falls back to a plain
    session-id label when nothing usable is found.
    """
    pipeline_data = payload.get("pipeline_data", {})

    # A malformed history entry must not crash the history display.
    if not isinstance(pipeline_data, dict):
        pipeline_data = {}

    fitting = pipeline_data.get("07_spectral_fitting")
    if isinstance(fitting, dict) and fitting:
        fit_type = fitting.get("fit_type", "fit")
        polarization = fitting.get("polarization", "")
        prefix = f"{polarization} — " if polarization else ""
        return f"{prefix}{fit_type} committed (Graph 3)"

    pointing = pipeline_data.get("06_pointing_correction")
    if isinstance(pointing, dict) and pointing:
        return "Pointing correction computed"

    bandpass = pipeline_data.get("03_bandpass_correction")
    if isinstance(bandpass, dict) and bandpass:
        return f"Bandpass — {bandpass.get('mode', 'correction')}"
    if pipeline_data.get("01_source_browser"):
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
# Observation Log Panel (FR-20) — read-only events and current recorded parameters.
# The new panel does not append events, change stage data or alter checkpoint behaviour.
# ---------------------------------------------------------------------
render_observation_log(st.session_state, theme=theme, height=LOG_PANEL_HEIGHT)

# ---------------------------------------------------------------------
# Mark export stage complete — the last stage key, so the progress bar reads 8/8 once this fires (on later
# pages/visits; this page's own header counts only stages before it).
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


session_store.checkpoint_session("Export/session actions recorded")
