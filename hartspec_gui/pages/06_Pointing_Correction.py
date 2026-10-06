# 06_Pointing_Correction.py -- FR-12/13: compass-grid pointing scans + offset
# calculation.
#
# Runs off the shared utils/styles.py and utils/sidebar.py only -- no page-local
# theme tokens, CSS, or table markup are (re)invented here.
#
# Layout note: five equal, edge-to-edge N/S/E/W/Centre panels use st.columns(5) +
# st.container(border=True) -- the latter is the mechanism styles.inject_base_css
# already targets via its [data-testid="stVerticalBlockBorderWrapper"] rule.
#
# CHART THEMING (this revision): _pointing_scan_figure() previously set
# tickfont=dict(size=8) with no `color` key at all, which does NOT inherit
# the figure's top-level layout.font color -- Plotly's default tick color
# was left in place, effectively invisible against a dark bg-panel. Fixed
# by calling styles.plotly_layout_theme(theme) first and layering the
# panel-specific overrides (height, margins, no titles) on top of it,
# rather than hand-rolling axis dicts here. See that helper's own
# docstring in utils/styles.py for the full root-cause explanation --
# this is the reference pattern every other chart-producing page should
# follow too.
#
# Science note -- READ BEFORE TRUSTING THIS PAGE'S NUMBERS:
#
# 1. clc/Point_cor.py's `pointcor()` still uses `global hp` (set as a side effect
#    inside pointcor(), read by gaussf() during curve_fit). The project prompt
#    states this global-variable conflict was already fixed in Phase 0 -- the
#    file as delivered says otherwise. In a Streamlit server, that global is
#    shared across every concurrent session in the process, so two users running
#    this page at once could race on it mid-fit. NOT worked around here --
#    per the project prompt, a leftover that looks unfixed gets flagged and
#    confirmed, not silently patched or silently trusted.
#    # TODO: confirm against design -- is `hp` already guarded elsewhere (e.g. a
#    process-level lock), or does this genuinely still need Phase 0 work?
#
# 2. pointcor() returns (correction_factor, ns_offset_deg, ew_offset_deg) -- not
#    the (Azimuth offset, Elevation offset, RMS residual) triple the build spec's
#    sample table showed. NS/EW -> Elevation/Azimuth is a common telescope
#    convention but not confirmed here, and pointcor() never computes an RMS
#    residual (it discards curve_fit's covariance matrix). The table below shows
#    exactly what the function returns, correctly labeled, rather than forcing it
#    into the build spec's field names.
#    # TODO: confirm against design -- the real FR-12/13 field mapping, and
#    whether RMS residual should come from a (Phase-0, GUI-integration-only)
#    change to pointcor()'s return value, a separate calculation, or be dropped.
#
# 3. pointcor() also writes a matplotlib PDF to a hardcoded relative path
#    ("../plots/...", outside the mandated /data/ layout) and uses pyplot's
#    global current-figure state, which has its own thread-safety caveats in a
#    multi-user server. Not modified here; the call below is wrapped so a
#    missing ../plots/ directory doesn't crash the page, but the underlying
#    behavior is unchanged.
#
# 4. Real per-direction scan *peak* readings (the single power values pointcor()
#    actually needs at each half-power point) aren't sourced from anywhere yet --
#    nothing upstream in this pipeline currently extracts them. The illustrative
#    scan curves in each compass panel and the values fed into pointcor() below
#    are both clearly-marked mock data pending that plumbing.
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from clc import Point_cor
from utils import session_store, sidebar, styles

CURRENT_STAGE = 6
# Follows the "0N_description" stage-key convention used by Pages 01/03/04/05/07
# (see 01_source_browser, 03_bandpass_correction, 04_baseline_editor,
# 05_calibration_dashboard, 07_spectral_fitting). Nothing downstream currently
# gates on this key, but Page 06 previously had no key at all -- so it could
# never be recorded complete, permanently capping the progress bar and leaving
# no audit-log trace that pointing correction ever ran.
PAGE_STAGE_KEY = "06_pointing_correction"
DIRECTIONS = ["N", "S", "E", "W", "Centre"]  # left-to-right order per build spec §7 --
# NOT a geographic cross layout, reproduce exactly.

# Mock half-power-point readings + beam width, standing in for real scan data.
# HPBW matches the sample value already used on page 02 ("0.23°") for consistency.
# TODO: confirm against design -- replace with real values once upstream scan
# extraction exists.
MOCK_SCAN_PEAKS = {"north": 0.92, "south": 0.87, "east": 0.90, "west": 0.85, "cen": 1.00}
MOCK_HPBW_DEG = 0.23
MOCK_DIRNAME = "spectrum_002.fits"


def _pointing_scan_figure(direction: str, theme: dict[str, str]) -> go.Figure:
    """Build an illustrative pointing-scan plot (amplitude vs. angular offset).

    # TODO: confirm against design. This is a full mock scan curve for display
    # only -- it is NOT the same data pointcor() consumes (which only needs the
    # single half-power-point readings in MOCK_SCAN_PEAKS, not a full curve).
    """
    offsets = np.linspace(-5, 5, 41)
    mock_peak_offset = {"N": 0.3, "S": -0.2, "E": 0.1, "W": -0.4, "Centre": 0.0}[direction]
    amplitude = np.exp(-((offsets - mock_peak_offset) ** 2) / (2 * 1.4**2))

    fig = go.Figure()
    fig.add_scatter(
        x=offsets,
        y=amplitude,
        mode="lines",
        line=dict(color=theme["accent"], width=1.6),
        showlegend=False,
    )
    # Shared theming (backgrounds, axis line color, tick/title/legend font
    # color) first, panel-specific sizing/margins layered on top -- see
    # plotly_layout_theme()'s docstring for why the ordering matters.
    fig.update_layout(**styles.plotly_layout_theme(theme))
    fig.update_layout(
        height=160,
        margin=dict(l=8, r=8, t=8, b=8),
        showlegend=False,
    )
    return fig


def _run_pointing_correction() -> dict[str, str] | None:
    """Call the real clc.Point_cor.pointcor() with mock half-power-point inputs.

    Returns:
        A dict of display-ready fields matching pointcor()'s ACTUAL return
        contract (correction factor, NS offset, EW offset) -- not the build
        spec's assumed Azimuth/Elevation/RMS fields, per the module docstring
        above. None if the call raised (e.g. the hardcoded "../plots/" save
        path doesn't exist in this environment).
    """
    peaks = MOCK_SCAN_PEAKS
    try:
        correction_factor, ns_offset_deg, ew_offset_deg = Point_cor.pointcor(
            north=peaks["north"],
            south=peaks["south"],
            east=peaks["east"],
            west=peaks["west"],
            cen=peaks["cen"],
            hpbw=MOCK_HPBW_DEG,
            dirname=MOCK_DIRNAME,
        )
    except Exception as exc:  # noqa: BLE001 -- surfaced to the user below, not swallowed
        st.warning(
            "clc.Point_cor.pointcor() raised while computing the pointing correction "
            f"(likely its hardcoded `../plots/` save path): {exc}"
        )
        return None

    return {
        "North-South offset": f"{ns_offset_deg}°",
        "East-West offset": f"{ew_offset_deg}°",
        "Pointing correction factor": f"{correction_factor:.4f}",
    }


def render_compass_grid(theme: dict[str, str]) -> None:
    """Render the five equal N/S/E/W/Centre pointing-scan panels."""
    columns = st.columns(5)
    for column, direction in zip(columns, DIRECTIONS):
        with column, st.container(border=True):
            st.markdown(f'<div class="hs-panel-title">{direction}</div>', unsafe_allow_html=True)
            fig = _pointing_scan_figure(direction, theme)
            st.plotly_chart(fig, use_container_width=True, theme=None)


def render_offset_table(offsets: dict[str, str], theme: dict[str, str]) -> None:
    """Render the pointing-correction results table using the shared table tokens."""
    rows_html = ""
    for index, (metric, value) in enumerate(offsets.items()):
        stripe = theme["bg-panel"] if index % 2 == 0 else theme["bg-panel-alt"]
        rows_html += (
            f'<tr style="height:{styles.TABLE_ROW_HEIGHT}px; background-color:{stripe};">'
            f'<td style="padding:10px; font-size:10.5px; color:{theme["text-body"]}; width:60%;">'
            f"{metric}</td>"
            f'<td style="padding:10px; font-size:10.5px; color:{theme["text-body"]}; width:40%;">'
            f"{value}</td>"
            "</tr>"
        )

    st.markdown(
        f"""
        <div style="background-color:{theme['bg-panel']}; border:1px solid {theme['border-subtle']};
                    border-radius:{styles.PANEL_RADIUS}px; overflow:hidden;">
            <table style="width:100%; border-collapse:collapse;">
                <thead>
                    <tr style="height:{styles.TABLE_HEADER_HEIGHT}px;
                               background-color:{theme['table-header-bg']};">
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


# Stages strictly before Page 6 -- used for the shared header progress bar, so
# this page's own completion never counts toward its own "N/8 complete"
# (Style Guide §4 / Build Spec §6; Page 04 does the same).
UPSTREAM_STAGE_KEYS = (
    "01_source_browser",
    "file_loader",
    "03_bandpass_correction",
    "04_baseline_editor",
    "05_calibration_dashboard",
)


def _completed_upstream_count() -> int:
    """Count only stages strictly before Page 6 for the shared progress bar."""
    completed = st.session_state["completed_stages"]
    return sum(stage_key in completed for stage_key in UPSTREAM_STAGE_KEYS)


def main() -> None:
    """Render the Pointing Correction page (FR-12/13)."""
    st.set_page_config(page_title="HARTSPEC -- Pointing Correction", layout="wide")
    # Explicit, like every other page -- previously this page only got
    # session state initialised as a side effect of render_sidebar().
    session_store.init_session_state()
    sidebar.render_sidebar(current_stage=CURRENT_STAGE)
    styles.inject_base_css()

    # Captured before recomputing below, so the audit log only records the
    # first completion rather than on every Streamlit rerun (same pattern as
    # 05_Calibration_Dashboard.py).
    was_page_complete = PAGE_STAGE_KEY in st.session_state["completed_stages"]

    theme = styles.get_theme()
    styles.render_page_header(
        title="Pointing Correction",
        subtitle="FR-12 / 13 -- compass grid & offset calculation",
        current_stage=CURRENT_STAGE,
        completed_stages=_completed_upstream_count(),
    )

    render_compass_grid(theme)

    st.markdown(f"<div style='height:{styles.SECTION_GAP}px;'></div>", unsafe_allow_html=True)

    offsets = _run_pointing_correction()
    if offsets is not None:
        render_offset_table(offsets, theme)

        # Recorded honestly as mock-derived: the half-power-point readings fed
        # into pointcor() are still MOCK_SCAN_PEAKS (see module docstring, note
        # 4), so a saved session must not read as a real pointing measurement.
        # TODO: confirm against design -- drop this marker once real upstream
        # scan extraction replaces the mock inputs.
        st.session_state["pipeline_data"][PAGE_STAGE_KEY] = {
            **offsets,
            "input_source": "MOCK -- no real scan extraction yet",
        }
        session_store.mark_stage_complete(PAGE_STAGE_KEY)
        if not was_page_complete:
            session_store.log_event(
                "Pointing correction computed (mock scan inputs) — "
                f"NS {offsets['North-South offset']}, "
                f"EW {offsets['East-West offset']}, "
                f"correction factor {offsets['Pointing correction factor']}"
            )
    else:
        st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)
        st.session_state["pipeline_data"].pop(PAGE_STAGE_KEY, None)


if __name__ == "__main__":
    main()