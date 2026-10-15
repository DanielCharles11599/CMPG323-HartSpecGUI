# 06_Pointing_Correction.py — FR-12/13: compass-grid pointing scans (user-picked peaks), offset calculation and the
# 2.5-sigma Go / No-Go quality check with the RULE-05 override workflow.
#
# How it works (UAT feedback: "black points that you click / enter values"):
#   1. clc/File_check.py (run from Page 01) sorted the selected files into observation blocks. A pointing scan is the
#      HPN / HPS / HPE / HPW files plus the on-source ON file (SPPOINT = 1) of a block -- utils/pointing_logic finds
#      them, using the spectra Page 02 already loaded (no FITS file is re-read here).
#   2. Each of the five compass panels shows that file's LCP and RCP spectra with a BLACK POINT on the peak. The point
#      starts on the strongest channel; the user moves it by clicking the spectrum (only if the optional
#      `streamlit-plotly-events` package is installed -- Streamlit 1.32 has no native Plotly click events) or by
#      typing a velocity. Either way it snaps to a real channel.
#   3. The five picked powers (mean of LCP and RCP at the channel) and the beam width from the FITS header go to the
#      REAL clc.Point_cor.pointcor() -- via utils/pointing_logic.compute_pointing(), which leaves Point_cor.py
#      untouched (see that module's header for the `global hp` / "../plots/" mitigation).
#   4. Below the results, the (LCP + RCP) * Pointing Correction graph shows the correction applied to the spectrum.
#   5. FR-13: utils/pointing_logic.evaluate_pointing_check() gives a Go / No-Go verdict: A) |NS offset| < 2.5 sigma_NS
#      AND B) the unmodified clc Stats_manager.Sig_point says every pointing peaks >= 2.5 sigma above the baseline
#      noise. A non-converging fit is a hard, non-overridable exception (UC-08): the failing panels are flagged and
#      the fits that did converge are still drawn. The
#      stage only completes -- and the correction factor is only published to Pages 07/08 -- after the user accepts a
#      Go, or signs off a No-Go with an override note + scientific justification (RULE-05). Verdict, override text
#      and all pointing values are stored in pipeline_data[...]["pointing_check"] (session JSON / checkpoints).
#
# If the session has no complete pointing scan (File_check was skipped/failed, or the selection had none), the page
# falls back to typing the five powers and the beam width by hand -- real inputs only, never mock values.
#
# Science notes (unchanged from the earlier revision; still need owner confirmation):
#   # TODO: confirm against design -- NS/EW offsets are reported as returned by pointcor(); mapping them to
#   # Azimuth/Elevation (the build spec's sample table) is not confirmed, and pointcor() computes no RMS residual.
#   # TODO: confirm against design -- using the LCP/RCP mean as "the" peak power is our reading; pointcor() takes one
#   # value per direction.
from __future__ import annotations

import html
from pathlib import Path
from typing import Any, Optional

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from utils import baseline_editor_bridge, fitting_inputs, pointing_logic, session_store, sidebar, spectrum_resolution
from utils import styles

try:  # optional: click-to-pick support; typed entry always works without it
    from streamlit_plotly_events import plotly_events
except ImportError:  # pragma: no cover -- depends on the deployment
    plotly_events = None

CURRENT_STAGE = 6
PAGE_STAGE_KEY = "06_pointing_correction"
SOURCE_BROWSER_STAGE_KEY = "01_source_browser"
NEXT_PAGE = "pages/07_Spectral_Fitting.py"
DIRECTIONS = list(pointing_logic.ROLES)  # N, S, E, W, Centre -- left-to-right per build spec §7
RESULT_CACHE_KEY = "pointing_result_cache"
LOGGED_SIGNATURE_KEY = "pointing_logged_signature"
BASELINE_STAGE_KEY = "04_baseline_editor"
OVERRIDE_OPEN_KEY = "pointing_override_open"
OVERRIDE_NOTE_KEY = "pointing_override_note"
OVERRIDE_JUSTIFICATION_KEY = "pointing_override_justification"
OVERRIDE_SIGNATURE_KEY = "pointing_override_signature"
STOP_PENDING_KEY = "pointing_stop_pending"


# ---------------------------------------------------------------------------
# Data access
# ---------------------------------------------------------------------------
def _loaded_spectra_by_basename() -> dict[str, dict[str, Any]]:
    """Spectra Page 02 loaded for the Page 01 selection, keyed by file basename (File_check's block entries)."""
    selection = st.session_state.get("pipeline_data", {}).get(SOURCE_BROWSER_STAGE_KEY, {})
    spectra: dict[str, dict[str, Any]] = {}
    for relative_name in selection.get("selected_files", []) or []:
        result = st.session_state.get(f"file_loader_ingest_result::{relative_name}")
        if result is not None and getattr(result, "ok", False) and result.spectrum is not None:
            spectra[Path(relative_name).name] = result.spectrum
    return spectra


def _find_scans(spectra: dict[str, dict[str, Any]]) -> list[pointing_logic.PointingScan]:
    blocks = st.session_state.get("pipeline_data", {}).get(SOURCE_BROWSER_STAGE_KEY, {}).get("observation_blocks") or {}
    return pointing_logic.find_pointing_scans(blocks, spectra.get)


def _as_positive_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) and number > 0 else None


# ---------------------------------------------------------------------------
# Compass panels
# ---------------------------------------------------------------------------
def _panel_figure(spectrum: dict[str, Any], pick_index: int, theme: dict[str, str]) -> go.Figure:
    """LCP/RCP (fixed polarisation colours) with the black pick point on the LCP/RCP mean at the picked channel."""
    vlsr = np.asarray(spectrum["Vlsr"], dtype=float)
    lcp = np.asarray(spectrum["LCP"], dtype=float)
    rcp = np.asarray(spectrum["RCP"], dtype=float)
    fig = go.Figure()
    fig.add_scatter(x=vlsr, y=lcp, mode="lines", line=dict(color=styles.LCP_COLOR, width=1.0), showlegend=False,
                    hoverinfo="x+y")
    fig.add_scatter(x=vlsr, y=rcp, mode="lines", line=dict(color=styles.RCP_COLOR, width=1.0), showlegend=False,
                    hoverinfo="x+y")
    # Black with a white rim so it stays visible on the dark theme's dark panel too.
    fig.add_scatter(x=[vlsr[pick_index]], y=[pointing_logic.power_at_channel(lcp, rcp, pick_index)], mode="markers",
                    marker=dict(color="#000000", size=10, line=dict(color="#FFFFFF", width=1.5)), showlegend=False,
                    hoverinfo="skip")
    # Shared theming first, panel-specific sizing on top (see plotly_layout_theme()'s docstring for why).
    fig.update_layout(**styles.plotly_layout_theme(theme))
    fig.update_layout(height=160, margin=dict(l=8, r=8, t=8, b=8), showlegend=False)
    return fig


def _render_direction_panel(role: str, spectrum: dict[str, Any], scan_key: str, theme: dict[str, str]) -> float:
    """One compass panel; returns the power picked on it (mean of LCP and RCP at the chosen channel)."""
    vlsr = np.asarray(spectrum["Vlsr"], dtype=float)
    lcp, rcp = spectrum["LCP"], spectrum["RCP"]
    pick_key = f"pointing_pick::{scan_key}::{role}"
    if pick_key not in st.session_state:
        st.session_state[pick_key] = float(vlsr[pointing_logic.default_peak_index(vlsr, lcp, rcp)])

    st.markdown(f'<div class="hs-panel-title">{role}</div>', unsafe_allow_html=True)
    # The figure must be drawn from the CURRENT pick, but a click is only known after the chart renders -- so apply a
    # new click to session_state first (before the number_input below is created, which is the only legal moment).
    figure = _panel_figure(spectrum, pointing_logic.nearest_channel(vlsr, st.session_state[pick_key]), theme)
    keyboard_chart = styles.get_font_scale() > 100
    if plotly_events is not None:
        keyboard_chart = st.checkbox("Keyboard-accessible chart controls", value=keyboard_chart,
                                     key=f"pointing_keyboard::{scan_key}::{role}")
    if plotly_events is not None and not keyboard_chart:
        clicks = plotly_events(figure, click_event=True, override_height=170, key=f"pointing_click::{scan_key}::{role}")
        seen_key = f"pointing_click_seen::{scan_key}::{role}"
        if clicks and st.session_state.get(seen_key) != clicks[0]["x"]:
            st.session_state[seen_key] = clicks[0]["x"]  # remember it so a later typed value isn't overridden
            st.session_state[pick_key] = float(clicks[0]["x"])
            st.rerun()
    else:
        styles.render_plotly_chart(figure, use_container_width=True, theme=None, config={"displayModeBar": False})

    st.number_input(
        f"{role} peak velocity (km/s)", min_value=float(np.nanmin(vlsr)), max_value=float(np.nanmax(vlsr)),
        step=0.1, format="%.2f", key=pick_key, label_visibility="visible",
    )
    channel = pointing_logic.nearest_channel(vlsr, st.session_state[pick_key])
    power = pointing_logic.power_at_channel(lcp, rcp, channel)
    st.markdown(
        f'<div class="hs-file-caption">{vlsr[channel]:.2f} km/s · power {power:.4g} {spectrum.get("units", "")}</div>',
        unsafe_allow_html=True,
    )
    return power


def _render_manual_entry() -> tuple[dict[str, float], float]:
    """Fallback when no pointing scan is available: type the five powers and the beam width."""
    st.info(
        "No complete pointing scan (HPN / HPS / HPE / HPW + ON) was found among the files loaded in this session, so "
        "enter the five half-power-point powers and the beam width by hand. Complete Pages 01–02 with a pointing "
        "observation selected to pick them from the spectra instead."
    )
    powers: dict[str, float] = {}
    for column, role in zip(st.columns(5), DIRECTIONS):
        with column, st.container(border=True):
            st.markdown(f'<div class="hs-panel-title">{role}</div>', unsafe_allow_html=True)
            powers[role] = st.number_input(f"{role} power", min_value=0.0, value=0.0, step=0.01, format="%.4f",
                                           key=f"pointing_manual::{role}", label_visibility="collapsed")
    hpbw = st.number_input("Half-power beam width (deg)", min_value=0.0, value=0.0, step=0.01, format="%.4f",
                           key="pointing_manual::hpbw")
    return powers, float(hpbw)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
def render_offset_table(offsets: dict[str, str], theme: dict[str, str], result: Any = None) -> None:
    """Render the pointing-correction results table using the shared table tokens."""
    rows = dict(offsets)
    unc = getattr(result, "uncertainties", None)
    if unc is not None:  # FR-12: the fit uncertainties belong in the results table too, not only on the cards
        for label, sigma, unit in (("North-South offset uncertainty (1σ)", unc.ns_sigma_deg, "°"),
                                   ("East-West offset uncertainty (1σ)", unc.ew_sigma_deg, "°"),
                                   ("Pointing correction uncertainty (1σ)", unc.pc_sigma, "")):
            rows[label] = "not available" if sigma is None else f"{sigma:.4f}{unit}"
    rms = getattr(result, "rms_residual", None)
    if rms is not None:
        rows["RMS residual of fit (power units)"] = f"{rms:.4g}"
    rows_html = ""
    for index, (metric, value) in enumerate(rows.items()):
        stripe = theme["bg-panel"] if index % 2 == 0 else theme["bg-panel-alt"]
        rows_html += (
            f'<tr style="height:{styles.TABLE_ROW_HEIGHT}px; background-color:{stripe};">'
            f'<td style="padding:10px; font-size:0.65625rem; color:{theme["text-body"]}; width:60%;">{metric}</td>'
            f'<td style="padding:10px; font-size:0.65625rem; color:{theme["text-body"]}; width:40%;">{value}</td>'
            "</tr>"
        )
    st.markdown(
        f"""
        <div style="background-color:{theme['bg-panel']}; border:1px solid {theme['border-subtle']};
                    border-radius:{styles.PANEL_RADIUS}px; overflow:hidden;">
            <table style="width:100%; border-collapse:collapse;">
                <thead>
                    <tr style="height:{styles.TABLE_HEADER_HEIGHT}px; background-color:{theme['table-header-bg']};">
                        <th style="text-align:left; padding:10px; font-size:0.625rem; font-weight:600;
                                   color:{theme['table-header-text']}; width:60%;">Metric</th>
                        <th style="text-align:left; padding:10px; font-size:0.625rem; font-weight:600;
                                   color:{theme['table-header-text']}; width:40%;">Value</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _compute(powers: dict[str, float], hpbw: Optional[float], scan_key: str, dirname: str) -> dict[str, Any]:
    """pointcor() on the picked values, cached per input signature so a rerun doesn't redo the fit and the PDF save."""
    signature = (scan_key, tuple(round(powers[r], 9) for r in DIRECTIONS), None if hpbw is None else round(hpbw, 9))
    cache = st.session_state.get(RESULT_CACHE_KEY)
    if cache and cache["signature"] == signature:
        return cache
    entry: dict[str, Any] = {"signature": signature, "result": None, "error": None, "failed_panels": (),
                             "failed_axis": None, "partial_curves": {}}
    try:
        plot_dir = session_store.SESSIONS_DIR / st.session_state["session_id"] / "plots"
        entry["result"] = pointing_logic.compute_pointing(powers, hpbw, dirname, plot_dir=plot_dir)
    except Exception as exc:  # noqa: BLE001 -- legacy fit code can fail in several ways; shown to the user below
        entry["error"] = f"{type(exc).__name__}: {exc}"
        entry["failed_panels"] = tuple(getattr(exc, "panels", ()))
        entry["failed_axis"] = getattr(exc, "axis", None)
        entry["partial_curves"] = getattr(exc, "partial_curves", {})
    st.session_state[RESULT_CACHE_KEY] = entry
    return entry


def _render_pointing_product_graph(pointing_factor: float, theme: dict[str, str]) -> None:
    """(LCP + RCP) * Pointing Correction on the current spectrum (owner-requested graph)."""
    resolved = spectrum_resolution.resolve_spectrum(
        st.session_state,
        read_bridge=baseline_editor_bridge.read_bridge,
        fingerprint=baseline_editor_bridge.spectrum_fingerprint,
    )
    with st.container(border=True):
        st.markdown('<div class="hs-panel-title">(LCP + RCP) × Pointing Correction</div>', unsafe_allow_html=True)
        if resolved.is_placeholder:
            st.info("No real spectrum is available in this session yet, so this graph can't be drawn. "
                    "Complete the earlier pipeline stages first.")
            return
        product = fitting_inputs.pointing_product(resolved.channels["LCP"], resolved.channels["RCP"], pointing_factor)
        fig = go.Figure()
        fig.add_scatter(x=resolved.vlsr, y=product, mode="lines", line=dict(color=theme["accent"], width=1.6),
                        name="(LCP + RCP) × Pointing Correction")
        fig.update_layout(**styles.plotly_layout_theme(theme))
        fig.update_layout(
            height=280, margin=dict(l=40, r=20, t=10, b=40), showlegend=False,
            xaxis=dict(title="Vlsr (km/s)", showgrid=False, zeroline=False, color=theme["text-muted"]),
            yaxis=dict(title=f"Intensity ({resolved.intensity_unit})", showgrid=False, zeroline=False,
                       color=theme["text-muted"]),
        )
        styles.render_plotly_chart(fig, use_container_width=True, theme=None, config={"displayModeBar": False})
        st.caption(f"Spectrum source: {resolved.source_label}")


def _signal_to_noise(scan: Any, spectra: dict[str, dict[str, Any]], scan_key: str) -> Optional[Any]:
    """Condition B inputs: the five scan spectra, the Page 04 baseline regions, the Centre panel's picked velocity.

    None for manual entry: there are no spectra, so condition B is skipped (not failed) -- see main().
    """
    if scan is None:
        return None
    stage = st.session_state.get("pipeline_data", {}).get(BASELINE_STAGE_KEY, {})
    blocks = stage.get("blocks") if isinstance(stage, dict) else None
    return pointing_logic.evaluate_signal_to_noise(
        {role: spectra[scan.files[role]] for role in DIRECTIONS}, blocks or [],
        float(st.session_state[f"pointing_pick::{scan_key}::Centre"]),
    )


def _render_pointing_fit(entry: dict[str, Any], powers: dict[str, float], hpbw: Optional[float],
                         theme: dict[str, str]) -> None:
    """FR-12: the Gaussian fitted by Point_cor.py (dashed) over the measured half-power points, NS and EW.

    Stays on screen for the whole session (US-12). A failed fit gets an inline error badge; a fit that never ran
    because pointcor() stopped at an earlier failure is labelled as such. Fits that did converge are still drawn.
    """
    result = entry["result"]
    curves = (result.fit_curves if result is not None else entry.get("partial_curves")) or {}
    failed_axis = entry.get("failed_axis")
    measured = pointing_logic.measured_points(powers, hpbw)
    with st.container(border=True):
        st.markdown('<div class="hs-panel-title">Pointing fit — measured half-power points and fitted Gaussian</div>',
                    unsafe_allow_html=True)
        for column, (axis, data) in zip(st.columns(2), measured.items()):
            with column:
                curve = curves.get(axis)
                fig = go.Figure()
                if curve is not None:
                    fig.add_scatter(x=curve["x"], y=curve["y"], mode="lines", name="Fit",
                                    line=dict(color=styles.get_fit_line_color(), width=1.6, dash="dash"))
                fig.add_scatter(x=data["x"], y=data["y"], mode="markers+text", name="Measured",
                                text=list(data["panels"]), textposition="top center",
                                marker=dict(color=styles.LCP_COLOR, size=9))
                if curve is not None:  # fitted offset, as in Point_cor.py's own figure
                    fig.add_vline(x=curve["centre"], line=dict(color=theme["text-muted"], width=1, dash="dot"))
                fig.update_layout(**styles.plotly_layout_theme(theme))
                fig.update_layout(height=240, margin=dict(l=40, r=20, t=10, b=40), showlegend=False,
                                  xaxis=dict(title=f"{axis} offset (deg)"), yaxis=dict(title="Power"))
                if curve is None:
                    st.caption(axis)
                else:
                    st.caption(f"{axis} — fitted centre {curve['centre']:+.4f}° · amplitude {curve['amplitude']:.4g}")
                styles.render_plotly_chart(fig, use_container_width=True, theme=None,
                                           config={"displayModeBar": False})
                if axis == failed_axis:
                    st.markdown(styles.render_badge("Gaussian fit failed to converge", "error"),
                                unsafe_allow_html=True)
                elif curve is None and failed_axis:
                    st.caption("Not fitted: Point_cor.py stopped at the earlier failure.")


# ---------------------------------------------------------------------------
# FR-13: verdict, persistence and the RULE-05 override workflow
# ---------------------------------------------------------------------------
def _saved_check(signature_id: str) -> Optional[dict[str, Any]]:
    """The stored pointing_check record, but only if it belongs to exactly the current inputs."""
    stage = st.session_state.get("pipeline_data", {}).get(PAGE_STAGE_KEY)
    record = stage.get("pointing_check") if isinstance(stage, dict) else None
    if isinstance(record, dict) and record.get("signature") == signature_id:
        return record
    return None


def _reset_override_widgets(signature_id: str) -> None:
    """Drop override text/state when the inputs changed: a sign-off never carries over to a different result."""
    if st.session_state.get(OVERRIDE_SIGNATURE_KEY) != signature_id:
        for key in (OVERRIDE_NOTE_KEY, OVERRIDE_JUSTIFICATION_KEY, OVERRIDE_OPEN_KEY, "pointing_stop_pending"):
            st.session_state.pop(key, None)
        st.session_state[OVERRIDE_SIGNATURE_KEY] = signature_id


def _toggle_override() -> None:
    st.session_state[OVERRIDE_OPEN_KEY] = not st.session_state.get(OVERRIDE_OPEN_KEY, False)


def _request_stop() -> None:
    """Open the inline "Stop reduction?" confirmation (no browser-native dialog)."""
    st.session_state[STOP_PENDING_KEY] = True


def _cancel_stop() -> None:
    st.session_state.pop(STOP_PENDING_KEY, None)


def _stage_record(
    *, result: Any, check: Any, signature_id: str, accepted: bool, saved: Optional[dict[str, Any]],
    input_source: str, scan_key: str, scan_files: dict[str, str], picked: dict[str, float],
    powers: dict[str, float], hpbw: Optional[float], offsets: dict[str, str],
) -> dict[str, Any]:
    """pipeline_data entry for this page.

    ``correction_factor`` -- the only value Pages 07/08 read -- is published only once the result is accepted, so a
    No-Go that has not been signed off can never reach the fit or the export. Everything else (including the factor,
    inside ``pointing_check``) is stored immediately for the audit trail.
    """
    previous = saved or {}
    stage: dict[str, Any] = {
        "input_source": input_source,
        "scan_key": scan_key,
        "scan_files": dict(scan_files),
        "picked_velocities": picked,
        "peak_powers": {role: float(powers[role]) for role in DIRECTIONS},
        "hpbw_deg": None if hpbw is None else float(hpbw),
        "pointing_check": pointing_logic.check_record(
            check, result, signature=signature_id, accepted=accepted,
            override_note=str(previous.get("override_note", "")),
            override_justification=str(previous.get("override_justification", "")),
        ),
    }
    rms_residual = getattr(result, "rms_residual", None)
    stage["rms_residual"] = None if rms_residual is None else float(rms_residual)
    decided_at = previous.get("decided_at")
    if accepted and decided_at:
        stage["pointing_check"]["decided_at"] = decided_at
    elif not accepted and previous.get("stopped"):
        stage["pointing_check"].update(stopped=True, decided_at=decided_at or "")
    if result is not None:
        stage.update(ns_offset_deg=result.ns_offset_deg, ew_offset_deg=result.ew_offset_deg,
                     hpbw_deg=result.hpbw_deg, **offsets)
        if accepted:
            stage["correction_factor"] = result.correction_factor
    return stage


def _commit_acceptance(result: Any, check: Any, signature_id: str, note: str = "", justification: str = "") -> None:
    """Accept a Go, or record a signed-off No-Go override; completes the stage and checkpoints."""
    stage = st.session_state["pipeline_data"][PAGE_STAGE_KEY]
    stage["correction_factor"] = result.correction_factor
    stage["pointing_check"] = pointing_logic.check_record(
        check, result, signature=signature_id, accepted=True,
        override_note=note, override_justification=justification,
    )
    stage["pointing_check"]["decided_at"] = session_store.checkpoint_store.utc_now()  # full UTC stamp for audit
    session_store.mark_stage_complete(PAGE_STAGE_KEY)
    if check.verdict == pointing_logic.VERDICT_NO_GO:
        session_store.log_event("Pointing No-Go overridden (RULE-05) — override note and justification recorded")
    else:
        session_store.log_event("Pointing check Go — correction accepted")
    session_store.checkpoint_session("Pointing correction accepted")


def _commit_stop() -> None:
    """RULE-05 "stop the reduction" branch: record the No-Go as stopped (no override), publish no factor."""
    stage = st.session_state["pipeline_data"][PAGE_STAGE_KEY]
    stage["pointing_check"]["stopped"] = True
    stage["pointing_check"]["decided_at"] = session_store.checkpoint_store.utc_now()
    stage.pop("correction_factor", None)
    st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)
    session_store.log_event("Pointing No-Go — reduction stopped by user (no override recorded)")
    session_store.checkpoint_session("Pointing reduction stopped at No-Go")


# ---------------------------------------------------------------------------
# FR-12/13 presentation
# ---------------------------------------------------------------------------
def _render_metric_cards(result: Any, check: Any, theme: dict[str, str]) -> None:
    """pc, NS and EW offsets with their fit uncertainties (or an explicit 'not available')."""
    unc = getattr(result, "uncertainties", None)
    cards = (
        ("Pointing correction (pc)", f"{result.correction_factor:.4f}", getattr(unc, "pc_sigma", None), "", None),
        ("North-South offset", f"{result.ns_offset_deg:+.4f}°", getattr(unc, "ns_sigma_deg", None), "°",
         check.ns_ratio),
        ("East-West offset", f"{result.ew_offset_deg:+.4f}°", getattr(unc, "ew_sigma_deg", None), "°", None),
    )
    box = (f"background-color:{theme['bg-panel']}; border:1px solid {theme['border-subtle']}; "
           f"border-radius:{styles.PANEL_RADIUS}px; padding:12px 16px;")
    cells = ""
    for label, value, sigma, unit, ratio in cards:
        sigma_text = "uncertainty not available" if sigma is None else f"± {sigma:.4f}{unit}"
        ratio_html = ""
        if ratio is not None:
            ratio_text = f"|offset| / σ = {ratio:.2f} (Go below {check.threshold_sigma:g})"
            ratio_html = f'<div style="font-size:0.625rem; color:{theme["text-muted"]};">{ratio_text}</div>'
        cells += (
            f'<div style="{box}">'
            f'<div style="font-size:0.625rem; font-weight:600; color:{theme["text-muted"]};">{html.escape(label)}</div>'
            f'<div style="font-size:1.25rem; font-weight:700; color:{theme["text-heading"]};">{value}</div>'
            f'<div style="font-size:0.6875rem; color:{theme["text-body"]};">{sigma_text}</div>{ratio_html}</div>'
        )
    st.markdown(f'<div style="display:grid; grid-template-columns:repeat(3, 1fr); gap:12px;">{cells}</div>',
                unsafe_allow_html=True)


def _render_verdict_panel(check: Any, accepted: bool, theme: dict[str, str]) -> None:
    """Go / No-Go status badge plus the reasons behind a No-Go."""
    if check.verdict == pointing_logic.VERDICT_GO:
        badge = styles.render_badge("Go", "ok")
    elif accepted:
        badge = styles.render_badge("No-Go — overridden", "info")
    elif check.overridable:
        badge = styles.render_badge("No-Go", "warning")
    else:
        badge = styles.render_badge("No-Go — fit failed", "error")
    reasons = "".join(f"<li>{html.escape(reason)}</li>" for reason in check.reasons)
    reasons_html = (f'<ul style="margin:8px 0 0 18px; font-size:0.75rem; color:{theme["text-body"]};">{reasons}</ul>'
                    if reasons else "")
    snr = check.snr
    snr_html = ""
    extra = (" (Sig_point not applicable to manual entry)" if check.snr_skipped
             else " and Sig_point signal-to-noise")
    if snr is not None and snr.evaluated and snr.panel_snr:
        values = ", ".join(f"{role} {value:.1f}" for role, value in snr.panel_snr)
        snr_html = (f'<div style="margin-top:6px; font-size:0.6875rem; color:{theme["text-muted"]};">'
                    f'Peak / baseline rms at {snr.peak_velocity_kms:.2f} km/s — {html.escape(values)}</div>')
        if snr.resampled:
            snr_html += (f'<div style="margin-top:4px; font-size:0.6875rem; color:{theme["text-muted"]};">'
                         f'Interpolated onto the Centre velocity grid for this check only: '
                         f'{html.escape("; ".join(snr.resampled))}</div>')
    st.markdown(
        f'<div style="margin:{styles.SECTION_GAP}px 0 4px;">{badge} '
        f'<span style="font-size:0.75rem; color:{theme["text-body"]};">'
        f'Pointing check — |NS offset| below {check.threshold_sigma:g}σ{extra}</span>'
        f'{reasons_html}{snr_html}</div>',
        unsafe_allow_html=True,
    )


def _render_actions(result: Any, check: Any, signature_id: str, accepted: bool) -> None:
    """Accept & proceed (Go), or the override form (No-Go). Nothing proceeds without one of the two."""
    if result is None:
        st.button("Accept & Proceed to Spectral Fitting →", type="primary", disabled=True, key="pointing_next_btn")
        return
    if accepted:
        if st.button("Continue to Spectral Fitting →", type="primary", key="pointing_next_btn"):
            st.switch_page(NEXT_PAGE)
        return
    if check.verdict == pointing_logic.VERDICT_GO:
        if st.button("Accept & Proceed to Spectral Fitting →", type="primary", key="pointing_next_btn"):
            _commit_acceptance(result, check, signature_id)
            st.switch_page(NEXT_PAGE)
        return

    saved = _saved_check(signature_id)
    stopped = bool(saved and saved.get("stopped"))
    if stopped:
        st.warning("Reduction stopped at the pointing check. No correction factor is passed to Spectral Fitting or "
                   "Export. You can still record an override below to continue.")
    st.button("Hide override form" if st.session_state.get(OVERRIDE_OPEN_KEY) else "Override No-Go…",
              key="pointing_override_toggle", on_click=_toggle_override)
    if st.session_state.get(STOP_PENDING_KEY):
        st.caption("Stop the reduction here? The No-Go verdict is recorded without an override and no correction "
                   "factor is passed to Spectral Fitting or Export. An override can still be recorded afterwards.")
        confirm_col, cancel_col, _spacer = st.columns([1, 1, 6])
        with confirm_col:
            if st.button("Stop reduction", type="primary", key="pointing_stop_confirm_btn",
                         use_container_width=True):
                _commit_stop()
                st.session_state.pop(STOP_PENDING_KEY, None)
                st.rerun()
        with cancel_col:
            st.button("Cancel", key="pointing_stop_cancel_btn", on_click=_cancel_stop, use_container_width=True)
    elif not stopped:
        st.button("Stop reduction here…", key="pointing_stop_btn", on_click=_request_stop)
    if not st.session_state.get(OVERRIDE_OPEN_KEY):
        return
    st.markdown('<div class="hs-eyebrow">Override (RULE-05)</div>', unsafe_allow_html=True)
    note = st.text_area("Override note", key=OVERRIDE_NOTE_KEY, height=80)
    justification = st.text_area("Scientific justification", key=OVERRIDE_JUSTIFICATION_KEY, height=120)
    st.caption("Both fields are required. They are saved with the verdict and pointing values in the session record.")
    ready = bool(note.strip() and justification.strip())
    if st.button("Record override & proceed to Spectral Fitting →", type="primary", disabled=not ready,
                 key="pointing_override_confirm_btn"):
        _commit_acceptance(result, check, signature_id, note.strip(), justification.strip())
        st.switch_page(NEXT_PAGE)


def main() -> None:
    """Render the Pointing Correction page (FR-12/13)."""
    st.set_page_config(page_title="HARTSPEC -- Pointing Correction", layout="wide")
    session_store.init_session_state()
    sidebar.render_sidebar(current_stage=CURRENT_STAGE)
    styles.inject_base_css()

    theme = styles.get_theme()
    styles.render_page_header(
        title="Pointing Correction",
        subtitle="Compass grid & offset calculation",
        current_stage=CURRENT_STAGE,
        # strictly-before-this-page count (Build Spec §6); replaces the hand-kept stage tuple this page used to carry
        completed_stages=session_store.completed_before(CURRENT_STAGE),
    )

    spectra = _loaded_spectra_by_basename()
    scans = _find_scans(spectra)

    powers: dict[str, float] = {}
    slots: dict[str, Any] = {}
    hpbw: Optional[float] = None
    scan_key, dirname, input_source = "manual", "manual", "manual entry"

    if scans:
        scan_options = {scan.key: scan for scan in scans}
        if st.session_state.get("pointing_scan_key") not in scan_options:
            st.session_state["pointing_scan_key"] = scans[0].key
        if len(scans) > 1:
            selected_scan = st.selectbox("Pointing scan", list(scan_options), key="pointing_scan_key",
                                         format_func=lambda key: scan_options[key].label)
        else:
            selected_scan = scans[0].key
        scan = scan_options[selected_scan]
        scan_key, dirname, input_source = scan.key, scan.block, f"pointing scan: {scan.label}"
        st.caption(
            "Click a spectrum (if click-to-pick is installed) or type a velocity to move the black point onto the "
            "peak. Each panel's value is the mean of LCP and RCP at that channel. The panels stay on screen for the "
            "whole session so the fit can be re-examined."
        )
        for column, role in zip(st.columns(5), DIRECTIONS):
            with column, st.container(border=True):
                powers[role] = _render_direction_panel(role, spectra[scan.files[role]], scan_key, theme)
                slots[role] = st.empty()  # filled below if this panel's fit failed
        hpbw = _as_positive_float(spectra[scan.files["Centre"]].get("HPBW"))
        if hpbw is None:
            st.warning("The beam width (HPBW) could not be read from the on-source file's header. Enter it below.")
            hpbw = _as_positive_float(st.number_input("Half-power beam width (deg)", min_value=0.0, value=0.0,
                                                      step=0.01, format="%.4f", key=f"pointing_hpbw::{scan_key}"))
    else:
        powers, hpbw_entered = _render_manual_entry()
        hpbw = hpbw_entered if hpbw_entered > 0 else None

    st.markdown(f"<div style='height:{styles.SECTION_GAP}px;'></div>", unsafe_allow_html=True)

    entry: Optional[dict[str, Any]] = None
    if hpbw is not None and all(powers.get(role, 0) > 0 for role in DIRECTIONS):
        entry = _compute(powers, hpbw, scan_key, dirname)
    else:
        st.caption("Enter a positive power for all five directions and a beam width to calculate the correction.")

    if entry is None:
        st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)
        st.session_state["pipeline_data"].pop(PAGE_STAGE_KEY, None)
        session_store.checkpoint_session("Pointing parameters recorded")
        _render_actions(None, None, "", False)
        return

    result = entry["result"]
    if entry["error"]:
        st.warning(f"clc.Point_cor.pointcor() could not compute the correction: {entry['error']}")

    # FR-13: verdict for exactly these inputs; an earlier sign-off only counts if the inputs are unchanged.
    signature_id = pointing_logic.signature_id(entry["signature"])
    snr = _signal_to_noise(scan if scans else None, spectra, scan_key) if result is not None else None
    check = (pointing_logic.evaluate_pointing_check(result, snr, snr_required=bool(scans))
             if result is not None
             else pointing_logic.failed_fit_check(entry["error"] or "no result", entry.get("failed_panels", ())))
    if result is None:  # UC-08 exception flow: flag the affected panels (Centre is shared, so it is not flagged)
        failed_badge = styles.render_badge("Gaussian fit failed to converge", "error")
        for name in check.failed_panels:
            role = pointing_logic.PANEL_ROLE.get(name, name)
            if role != "Centre" and role in slots:
                slots[role].markdown(failed_badge, unsafe_allow_html=True)
    _reset_override_widgets(signature_id)
    saved = _saved_check(signature_id)
    accepted = bool(result is not None and saved and saved.get("accepted") and saved.get("verdict") == check.verdict)

    offsets: dict[str, str] = {}
    if result is not None:
        offsets = {
            "North-South offset": f"{result.ns_offset_deg}°",
            "East-West offset": f"{result.ew_offset_deg}°",
            "Pointing correction factor": f"{result.correction_factor:.4f}",
            "Half-power beam width used": f"{result.hpbw_deg:g}°",
        }
    picked = {
        role: float(st.session_state[f"pointing_pick::{scan_key}::{role}"]) for role in DIRECTIONS
    } if scans else {}
    st.session_state["pipeline_data"][PAGE_STAGE_KEY] = _stage_record(
        result=result, check=check, signature_id=signature_id, accepted=accepted, saved=saved,
        input_source=input_source, scan_key=scan_key, scan_files=dict(scan.files) if scans else {},
        picked=picked, powers=powers, hpbw=hpbw, offsets=offsets,
    )
    if accepted:
        session_store.mark_stage_complete(PAGE_STAGE_KEY)
    else:
        st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)

    if st.session_state.get(LOGGED_SIGNATURE_KEY) != entry["signature"]:
        st.session_state[LOGGED_SIGNATURE_KEY] = entry["signature"]
        if result is not None:
            session_store.log_event(
                f"Pointing correction computed ({input_source}) — NS {result.ns_offset_deg}°, "
                f"EW {result.ew_offset_deg}°, correction factor {result.correction_factor:.4f} — "
                f"check: {check.verdict}"
            )
        else:
            session_store.log_event(f"Pointing fit did not converge ({input_source}) — check: {check.verdict}")

    if result is not None:
        _render_metric_cards(result, check, theme)
    _render_verdict_panel(check, accepted, theme)
    _render_pointing_fit(entry, powers, hpbw, theme)
    # Results table stays hidden while the override form is open (keeps the form uncluttered; cards show the values).
    if result is not None and not st.session_state.get(OVERRIDE_OPEN_KEY):
        st.markdown(f"<div style='height:{styles.SECTION_GAP}px;'></div>", unsafe_allow_html=True)
        render_offset_table(offsets, theme, result)
    if result is not None:
        st.markdown(f"<div style='height:{styles.SECTION_GAP}px;'></div>", unsafe_allow_html=True)
        _render_pointing_product_graph(result.correction_factor, theme)

    session_store.checkpoint_session("Pointing parameters recorded")
    _render_actions(result, check, signature_id, accepted)


if __name__ == "__main__":
    main()
    