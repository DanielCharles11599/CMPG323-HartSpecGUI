# 07_Spectral_Fitting.py — FR-14–17: Gaussian / polynomial / multi-component fit UI.
#
# STATUS: visual scaffold only, matching the style/layout of Pages 01-05.
# Page 06 (Pointing Correction) doesn't exist yet, so this page deliberately
# has NO real fitting logic wired up -- no read from a Page 06 handoff, no
# call into clc/Gaussf.py (or whichever module ends up backing FR-14-17),
# and no pipeline_data write / mark_stage_complete() call. It renders the
# FIT TYPE selector, the spectrum+fit chart panel, and the fit-parameters
# table exactly per the build spec's layout (§7, page 07), with every data
# value shown as a "Not calculated" placeholder rather than inventing
# fabricated fit output.
#
# When Page 06 exists and a real fitting module is confirmed, this page
# needs: an upstream-completeness gate (see 04_Baseline_Editor.py's
# _upstream_complete() pattern), a real corrected-spectrum handoff, real
# Gaussian/polynomial/multi-component fit calls per the active FIT TYPE,
# and pipeline_data["07_spectral_fitting"] + mark_stage_complete() once a
# fit actually succeeds. None of that is guessed here.
#
# Table styling deliberately duplicates 02_File_Loader.py's page-local
# _render_table_header/_render_table_row helpers rather than importing a
# shared one from utils/styles.py -- that promotion was explicitly deferred
# in Page 02's own comment ("not done here without confirmation since
# styles.py is actively being edited by the team"), so this follows the
# same page-local pattern rather than touching the shared file.

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from utils import session_store, sidebar, styles

CURRENT_STAGE = 7

PAGE_TITLE = "Spectral Fitting"
PAGE_SUBTITLE = "FR-14–17 — Gaussian / polynomial / multi-component fits"

FIT_TYPE_OPTIONS = ["1D Gaussian", "2D Gaussian", "Polynomial Peak", "Multi-component"]

FIT_PARAMETER_ROWS = [
    ("Amplitude", "Not calculated", "—"),
    ("Center (Vlsr)", "Not calculated", "—"),
    ("FWHM", "Not calculated", "—"),
]

st.set_page_config(
    page_title="HARTSPEC — Spectral Fitting",
    layout="wide",
    initial_sidebar_state="expanded",
)

session_store.init_session_state()
sidebar.render_sidebar(current_stage=CURRENT_STAGE)
styles.inject_base_css()

_theme = styles.get_theme()


# --------------------------------------------------------------------------
# Page-local table helpers -- copied from 02_File_Loader.py on purpose, see
# module docstring. Keep any visual fix made there (header radius, stripe
# color, etc.) mirrored here until both are promoted to utils/styles.py.
# --------------------------------------------------------------------------
def _render_table_header(columns: list[tuple[str, str]]) -> None:
    theme = styles.get_theme()
    cells = "".join(
        f'<div style="flex:0 0 {width}; padding-left:10px; font-size:10px; '
        f'font-weight:600; color:{theme["table-header-text"]};">{label}</div>'
        for label, width in columns
    )
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; height:{styles.TABLE_HEADER_HEIGHT}px;
                    background-color:{theme['table-header-bg']}; border-radius:{styles.PANEL_RADIUS}px
                    {styles.PANEL_RADIUS}px 0 0;">
          {cells}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_table_row(cells_html: list[tuple[str, str]], striped: bool) -> None:
    theme = styles.get_theme()
    bg = theme["bg-panel-alt"] if striped else theme["bg-panel"]
    cells = "".join(
        f'<div style="flex:0 0 {width}; padding-left:10px; font-size:10.5px; '
        f'color:{theme["text-body"]};">{content}</div>'
        for content, width in cells_html
    )
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; height:{styles.TABLE_ROW_HEIGHT}px;
                    background-color:{bg}; border-bottom:1px solid {theme['border-subtle']};">
          {cells}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_legend(theme: dict[str, str]) -> None:
    """Spectrum / Fit swatch legend, per the style guide's chart-panel legend spec
    (10x10px swatch, 2px radius, 9px Regular text-muted label)."""
    st.markdown(
        f"""
        <div style="display:flex; gap:16px; margin-top:8px;">
          <div style="display:flex; align-items:center; gap:6px;">
            <span style="display:inline-block; width:10px; height:10px; border-radius:2px;
                        background-color:{styles.LCP_COLOR};"></span>
            <span style="font-size:9px; color:{theme['text-muted']};">Spectrum</span>
          </div>
          <div style="display:flex; align-items:center; gap:6px;">
            <span style="display:inline-block; width:10px; height:10px; border-radius:2px;
                        background-color:{styles.get_fit_line_color()};
                        border:1px dashed {styles.get_fit_line_color()};"></span>
            <span style="font-size:9px; color:{theme['text-muted']};">Fit</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


styles.render_page_header(
    title=PAGE_TITLE,
    subtitle=PAGE_SUBTITLE,
    current_stage=CURRENT_STAGE,
    completed_stages=session_store.completed_count(),
)


# FIT TYPE — four-way segmented control (FR-14 through FR-17), same pattern
# as 03_Bandpass_Correction.py's mode radio: st.radio horizontal, no custom
# pill CSS invented here (none exists in utils/styles.py for radios yet).
st.session_state.setdefault("spectral_fit_type", FIT_TYPE_OPTIONS[0])
st.markdown('<div class="hs-eyebrow">Fit type</div>', unsafe_allow_html=True)
st.radio(
    "Fit type",
    options=FIT_TYPE_OPTIONS,
    horizontal=True,
    key="spectral_fit_type",
    label_visibility="collapsed",
)


# Spectrum + fit overlay chart panel
with st.container(border=True):
    st.markdown(
        '<div class="hs-panel-title">Spectrum + fit overlay</div>',
        unsafe_allow_html=True,
    )

    fit_fig = go.Figure()
    fit_fig.add_annotation(
        text="Spectrum + fit overlay will appear here once fitting is wired up",
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(
            family="Inter, -apple-system, 'Segoe UI', sans-serif",
            size=13,
            color=_theme["text-muted"],
        ),
    )
    fit_fig.update_layout(
        paper_bgcolor=_theme["bg-panel"],
        plot_bgcolor=_theme["bg-panel"],
        margin=dict(l=48, r=16, t=20, b=40),
        height=320,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        font=dict(
            family="Inter, -apple-system, 'Segoe UI', sans-serif",
            size=11,
            color=_theme["text-body"],
        ),
    )
    st.plotly_chart(fit_fig, use_container_width=True, config={"displayModeBar": False})

    _render_legend(_theme)


# Fit-parameters table panel
with st.container(border=True):
    st.markdown(
        '<div class="hs-panel-title">Fit parameters</div>',
        unsafe_allow_html=True,
    )

    _render_table_header([("Parameter", "38.7%"), ("Value", "28.6%"), ("± Error", "28.6%")])
    for idx, (parameter, value, error) in enumerate(FIT_PARAMETER_ROWS):
        _render_table_row(
            [(parameter, "38.7%"), (value, "28.6%"), (error, "28.6%")],
            striped=idx % 2 == 1,
        )

    st.caption("Fit output will populate once Page 06 and the fitting backend are wired up.")