# 03_Bandpass_Correction.py — FR-04: mode selector + bandpass-corrected
# spectrum overlay.
#
# Renders the Frequency Switch / Position Switch mode pill, runs the
# corresponding bandpass correction, and plots the resulting LCP/RCP
# spectrum. Layout/coordinates follow HARTSPEC-Page_Build_Spec.md §7 (page
# 03). Colors, type, session persistence, and shared chrome all come from the
# project's real utils modules rather than being reimplemented here:
#   - utils/styles.py    -> inject_base_css(), get_theme(), render_page_header()
#                            (title + subtitle + the pipeline progress bar,
#                            all in one call), LCP_COLOR / RCP_COLOR (fixed,
#                            never themed -- style guide §1)
#   - utils/sidebar.py    -> render_sidebar(current_stage) (nav, theme
#                            toggle, Save/Load/Reset -- fully self-contained)
#   - utils/session_store.py -> init_session_state(), log_event(),
#                            mark_stage_complete(), completed_count()
#   - utils/bandpass_correction_logic.py -> the actual FR-04 math (kept out of
#                            this file so it's testable without a Streamlit
#                            runtime -- see that module's own docstring for
#                            why it doesn't call clc.Baseline.freq_switch /
#                            clc.Baseline.pos_switch directly)
#
# Streamlit renders as a fluid HTML flow, not an absolute-position canvas
# (utils/styles.py's own module docstring makes the same point). Pixel
# values from the build spec are applied two ways:
#   - Fixed-size tokens (font sizes, radii, gaps) are applied literally, as
#     page-local constants below.
#   - x/y canvas positions for elements laid out via normal flow are
#     translated into relative CSS / st.columns ratios built from the spec's
#     own pixel widths, matching the pattern in 01_Source_Browser.py.

import plotly.graph_objects as go
import streamlit as st

from utils import session_store, sidebar, styles
from utils.bandpass_correction_logic import (
    MODE_OPTIONS,
    THIS_STAGE_KEY,
    get_corrected_spectrum,
    stage_summary,
)

# ---------------------------------------------------------------------------
# Page identity
# ---------------------------------------------------------------------------
PAGE_STAGE_KEY = THIS_STAGE_KEY  # key used in session_store's pipeline_data / completed_stages
CURRENT_STAGE = 3  # 1-indexed — matches sidebar.STAGES order and styles.render_page_header

# TODO: confirm against design — see build spec §3, same situation as
# 01_Source_Browser.py's PAGE_TITLE: the exact H1 copy isn't given anywhere in
# the three source docs (only the subtitle is). "Bandpass Correction" is
# inferred from the sidebar nav label ("03  Bandpass Correction") with the
# stage number dropped, since the progress bar already shows "Stage 3 of 8".
PAGE_TITLE = "Bandpass Correction"
PAGE_SUBTITLE = "FR-04 — mode selector + spectrum overlay"

# Chart panel title text, given verbatim in build spec §7 (page 03 table).
CHART_PANEL_TITLE = "Bandpass-corrected spectrum"

# Pill widths from build spec §7 (page 03 table) — used to size the
# st.columns() ratios below so the two pills approximate their spec widths
# instead of splitting evenly.
_FREQ_SWITCH_PILL_WIDTH_PX = 180
_POS_SWITCH_PILL_WIDTH_PX = 180

st.set_page_config(page_title="HARTSPEC — Bandpass Correction", layout="wide", initial_sidebar_state="expanded")

# Every page calls this before touching st.session_state, per session_store.py's
# own module docstring — safe/idempotent even though render_sidebar() below
# also calls it defensively.
session_store.init_session_state()

sidebar.render_sidebar(current_stage=CURRENT_STAGE)
styles.inject_base_css()


# ---------------------------------------------------------------------------
# Page-local session state
# ---------------------------------------------------------------------------
def _init_page_state() -> None:
    # Frequency Switch is the active pill in the mockup (build spec §7, page
    # 03), so it's the default here too.
    st.session_state.setdefault("bandpass_mode", MODE_OPTIONS[0])
    st.session_state.setdefault("bandpass_last_logged_mode", None)


_init_page_state()


def _on_mode_select(mode: str) -> None:
    st.session_state["bandpass_mode"] = mode


# ---------------------------------------------------------------------------
# Page-scoped CSS — only for the handful of classes utils/styles.py's
# inject_base_css() doesn't already define. Matches the pattern in
# 01_Source_Browser.py: colors come from styles.get_theme() (not CSS custom
# properties), since that's the convention inject_base_css() itself uses.
#
# TODO: confirm against design — the style guide (§3/§4) gives pills their
# own 16px full radius, distinct from the 6px button radius. Reusing
# st.button(type="primary"/"secondary") below gets the right fill/border/text
# colors "for free" from inject_base_css()'s existing button rules, but at
# button radius, not pill radius, since Streamlit only exposes button "kind"
# (not a scoped per-instance class) to target with CSS. A `.hs-pill` rule
# added to utils/styles.py (global, keyed off a wrapper container) would be
# the right permanent fix so every future pill on the site gets it at once,
# rather than duplicating a scoped override in each page that has one.
# ---------------------------------------------------------------------------
_theme = styles.get_theme()

st.markdown(
    f"""
    <style>
    .hs-legend-row {{
        display: flex;
        align-items: center;
        gap: 24px;
        margin-top: 10px;
    }}
    .hs-legend-item {{
        display: flex;
        align-items: center;
        gap: 8px;
    }}
    .hs-legend-swatch {{
        width: 10px;
        height: 10px;
        border-radius: 2px;
        display: inline-block;
    }}
    .hs-legend-label {{
        font-size: 9px;
        color: {_theme['text-muted']};
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Header band (title + subtitle + pipeline progress bar, all one call)
# ---------------------------------------------------------------------------
styles.render_page_header(
    title=PAGE_TITLE,
    subtitle=PAGE_SUBTITLE,
    current_stage=CURRENT_STAGE,
    completed_stages=session_store.completed_count(),
)


# ---------------------------------------------------------------------------
# Mode selector — "Frequency Switch" / "Position Switch" segmented pill
# build spec §7 p.03: eyebrow y=104, pills y=122, w=122 / w=115.5
# ---------------------------------------------------------------------------
st.markdown('<div class="hs-eyebrow">Mode</div>', unsafe_allow_html=True)

_remaining_width = styles.CONTENT_WIDTH - _FREQ_SWITCH_PILL_WIDTH_PX - _POS_SWITCH_PILL_WIDTH_PX
mode_cols = st.columns([_FREQ_SWITCH_PILL_WIDTH_PX, _POS_SWITCH_PILL_WIDTH_PX, _remaining_width])

active_mode = st.session_state["bandpass_mode"]

with mode_cols[0]:
    st.button(
        "Frequency Switch",
        key="mode_freq_switch",
        type="primary" if active_mode == "Frequency Switch" else "secondary",
        use_container_width=True,
        on_click=_on_mode_select,
        args=("Frequency Switch",),
    )
with mode_cols[1]:
    st.button(
        "Position Switch",
        key="mode_pos_switch",
        type="primary" if active_mode == "Position Switch" else "secondary",
        use_container_width=True,
        on_click=_on_mode_select,
        args=("Position Switch",),
    )

st.write("")  # approximates the gap between the pill row and the chart panel below (y=122+32 -> y=174)


# ---------------------------------------------------------------------------
# Spectrum chart panel
# build spec §7 p.03: x=244 y=174 w=1172 h=440
# ---------------------------------------------------------------------------
mode = st.session_state["bandpass_mode"]

try:
    corrected = get_corrected_spectrum(mode)
except ValueError as exc:
    st.error(str(exc))
    st.stop()

with st.container(border=True):
    st.markdown(f'<div class="hs-panel-title">{CHART_PANEL_TITLE}</div>', unsafe_allow_html=True)

    fig = go.Figure()
    fig.add_scatter(
        x=corrected["Vlsr"],
        y=corrected["LCP"],
        mode="lines",
        line=dict(color=styles.LCP_COLOR, width=1.6),
        name="LCP",
        hovertemplate="Vlsr=%{x:.2f} km/s<br>LCP=%{y:.3f} K<extra></extra>",
    )
    fig.add_scatter(
        x=corrected["Vlsr"],
        y=corrected["RCP"],
        mode="lines",
        line=dict(color=styles.RCP_COLOR, width=1.6),
        name="RCP",
        hovertemplate="Vlsr=%{x:.2f} km/s<br>RCP=%{y:.3f} K<extra></extra>",
    )
    # No fit overlay on this page — style guide's fit-overlay convention
    # (dashed red/light-red line) only applies starting at page 07 Spectral
    # Fitting, per build spec §7 p.03 ("No fit line on this page").
    fig.update_layout(
        showlegend=False,  # custom legend row rendered below, per build spec's separate swatch/label elements
        paper_bgcolor=_theme["bg-panel"],
        plot_bgcolor=_theme["bg-panel"],
        margin=dict(l=48, r=16, t=8, b=40),
        height=384,
        xaxis=dict(
            title="Vlsr (km/s)",
            showgrid=False,
            zeroline=False,
            showline=True,
            linecolor=_theme["border-subtle"],
            color=_theme["text-muted"],
        ),
        yaxis=dict(
            title="Tsys (K)",
            showgrid=False,
            zeroline=False,
            showline=True,
            linecolor=_theme["border-subtle"],
            color=_theme["text-muted"],
        ),
        font=dict(family="Inter, -apple-system, 'Segoe UI', sans-serif", size=11, color=_theme["text-body"]),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # Custom legend row — build spec §7 p.03 lists LCP/RCP swatch+label as
    # separate positioned elements below the plot area rather than Plotly's
    # built-in legend, so it's reproduced as plain HTML here instead.
    st.markdown(
        f"""
        <div class="hs-legend-row">
          <div class="hs-legend-item">
            <span class="hs-legend-swatch" style="background-color:{styles.LCP_COLOR};"></span>
            <span class="hs-legend-label">LCP</span>
          </div>
          <div class="hs-legend-item">
            <span class="hs-legend-swatch" style="background-color:{styles.RCP_COLOR};"></span>
            <span class="hs-legend-label">RCP</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Stage completion
#
# TODO: confirm against design — unlike 01_Source_Browser.py's explicit
# "Load into Pipeline →" button, build spec §7 p.03 doesn't describe a
# continue/commit control for this page, and sidebar.py's nav buttons are
# always clickable regardless of completion state (no gating). In the
# absence of a spec'd CTA, this stage is marked complete as soon as a
# corrected spectrum has been computed for the selected mode (i.e. on every
# render), which is effectively "the moment the user has looked at this
# page" rather than an explicit commit action. Flag for the team: is an
# explicit button wanted here after all, or is auto-complete-on-view the
# intended pattern for pages without a mocked CTA?
# ---------------------------------------------------------------------------
st.session_state["pipeline_data"][PAGE_STAGE_KEY] = stage_summary(mode, corrected)
session_store.mark_stage_complete(PAGE_STAGE_KEY)

if st.session_state["bandpass_last_logged_mode"] != mode:
    session_store.log_event(f"Bandpass correction applied — {mode}")
    st.session_state["bandpass_last_logged_mode"] = mode
