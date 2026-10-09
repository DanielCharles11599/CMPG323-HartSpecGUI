# 06_Pointing_Correction.py — FR-12/13: compass-grid pointing scans (user-picked peaks) + offset calculation.
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
    if plotly_events is not None:
        clicks = plotly_events(figure, click_event=True, override_height=170, key=f"pointing_click::{scan_key}::{role}")
        seen_key = f"pointing_click_seen::{scan_key}::{role}"
        if clicks and st.session_state.get(seen_key) != clicks[0]["x"]:
            st.session_state[seen_key] = clicks[0]["x"]  # remember it so a later typed value isn't overridden
            st.session_state[pick_key] = float(clicks[0]["x"])
            st.rerun()
    else:
        st.plotly_chart(figure, use_container_width=True, theme=None, config={"displayModeBar": False})

    st.number_input(
        f"{role} peak velocity (km/s)", min_value=float(np.nanmin(vlsr)), max_value=float(np.nanmax(vlsr)),
        step=0.1, format="%.2f", key=pick_key, label_visibility="collapsed",
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
def render_offset_table(offsets: dict[str, str], theme: dict[str, str]) -> None:
    """Render the pointing-correction results table using the shared table tokens."""
    rows_html = ""
    for index, (metric, value) in enumerate(offsets.items()):
        stripe = theme["bg-panel"] if index % 2 == 0 else theme["bg-panel-alt"]
        rows_html += (
            f'<tr style="height:{styles.TABLE_ROW_HEIGHT}px; background-color:{stripe};">'
            f'<td style="padding:10px; font-size:10.5px; color:{theme["text-body"]}; width:60%;">{metric}</td>'
            f'<td style="padding:10px; font-size:10.5px; color:{theme["text-body"]}; width:40%;">{value}</td>'
            "</tr>"
        )
    st.markdown(
        f"""
        <div style="background-color:{theme['bg-panel']}; border:1px solid {theme['border-subtle']};
                    border-radius:{styles.PANEL_RADIUS}px; overflow:hidden;">
            <table style="width:100%; border-collapse:collapse;">
                <thead>
                    <tr style="height:{styles.TABLE_HEADER_HEIGHT}px; background-color:{theme['table-header-bg']};">
                        <th style="text-align:left; padding:10px; font-size:10px; font-weight:600;
                                   color:{theme['table-header-text']}; width:60%;">Metric</th>
                        <th style="text-align:left; padding:10px; font-size:10px; font-weight:600;
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
    entry: dict[str, Any] = {"signature": signature, "result": None, "error": None}
    try:
        plot_dir = session_store.SESSIONS_DIR / st.session_state["session_id"] / "plots"
        entry["result"] = pointing_logic.compute_pointing(powers, hpbw, dirname, plot_dir=plot_dir)
    except Exception as exc:  # noqa: BLE001 -- legacy fit code can fail in several ways; shown to the user below
        entry["error"] = f"{type(exc).__name__}: {exc}"
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
        st.plotly_chart(fig, use_container_width=True, theme=None, config={"displayModeBar": False})
        st.caption(f"Spectrum source: {resolved.source_label}")


def main() -> None:
    """Render the Pointing Correction page (FR-12/13)."""
    st.set_page_config(page_title="HARTSPEC -- Pointing Correction", layout="wide")
    session_store.init_session_state()
    sidebar.render_sidebar(current_stage=CURRENT_STAGE)
    styles.inject_base_css()

    theme = styles.get_theme()
    styles.render_page_header(
        title="Pointing Correction",
        subtitle="FR-12 / 13 -- compass grid & offset calculation",
        current_stage=CURRENT_STAGE,
        # strictly-before-this-page count (Build Spec §6); replaces the hand-kept stage tuple this page used to carry
        completed_stages=session_store.completed_before(CURRENT_STAGE),
    )

    spectra = _loaded_spectra_by_basename()
    scans = _find_scans(spectra)

    powers: dict[str, float] = {}
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
            "peak. Each panel's value is the mean of LCP and RCP at that channel."
        )
        for column, role in zip(st.columns(5), DIRECTIONS):
            with column, st.container(border=True):
                powers[role] = _render_direction_panel(role, spectra[scan.files[role]], scan_key, theme)
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

    result = entry["result"] if entry else None
    if entry and entry["error"]:
        st.warning(f"clc.Point_cor.pointcor() could not compute the correction: {entry['error']}")

    if result is not None:
        offsets = {
            "North-South offset": f"{result.ns_offset_deg}°",
            "East-West offset": f"{result.ew_offset_deg}°",
            "Pointing correction factor": f"{result.correction_factor:.4f}",
            "Half-power beam width used": f"{result.hpbw_deg:g}°",
        }
        render_offset_table(offsets, theme)

        st.session_state["pipeline_data"][PAGE_STAGE_KEY] = {
            # Numeric values are what Pages 07/08 read (fitting_inputs.pointing_factor_from_pipeline).
            "correction_factor": result.correction_factor,
            "ns_offset_deg": result.ns_offset_deg,
            "ew_offset_deg": result.ew_offset_deg,
            "hpbw_deg": result.hpbw_deg,
            "peak_powers": result.powers,
            "input_source": input_source,
            "scan_key": scan_key,
            "scan_files": dict(scan.files) if scans else {},
            "picked_velocities": {
                role: float(st.session_state[f"pointing_pick::{scan_key}::{role}"])
                for role in DIRECTIONS
            } if scans else {},
            **offsets,
        }
        session_store.mark_stage_complete(PAGE_STAGE_KEY)
        if st.session_state.get(LOGGED_SIGNATURE_KEY) != entry["signature"]:
            st.session_state[LOGGED_SIGNATURE_KEY] = entry["signature"]
            session_store.log_event(
                f"Pointing correction computed ({input_source}) — NS {result.ns_offset_deg}°, "
                f"EW {result.ew_offset_deg}°, correction factor {result.correction_factor:.4f}"
            )

        st.markdown(f"<div style='height:{styles.SECTION_GAP}px;'></div>", unsafe_allow_html=True)
        _render_pointing_product_graph(result.correction_factor, theme)
    else:
        st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)
        st.session_state["pipeline_data"].pop(PAGE_STAGE_KEY, None)

    session_store.checkpoint_session("Pointing parameters recorded")

    if st.button("Continue to Spectral Fitting →", type="primary", disabled=result is None,
                 key="pointing_next_btn"):
        st.switch_page(NEXT_PAGE)


if __name__ == "__main__":
    main()
