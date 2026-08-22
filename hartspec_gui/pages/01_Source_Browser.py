# 01_Source_Browser.py — FR-01: file browser for source & frequency selection.
#
# Renders the grouped FITS/PSS file list, the frequency picker, and the
# selection-summary bar that hands the chosen file(s) off to
# 02_File_Loader.py. Layout/coordinates follow HARTSPEC-Page_Build_Spec.md §7
# (page 01); colors, type, and component styling follow HARTSPEC_Style_Guide.md
# §1-4. See the "Assumptions" note in the accompanying chat response for the
# utils/styles.py and utils/sidebar.py interface this page expects.
#
# Streamlit's layout is fluid, not an absolute-position canvas (style guide
# §3: "actual Streamlit width is fluid, treat [the 1440x900 frame] as the
# design reference only"). Pixel values from the build spec are therefore
# applied two ways:
#   - Where a value maps directly to a CSS property (font sizes, row heights,
#     radii, fixed-width controls like the frequency dropdown or buttons) it is
#     used exactly, as a named constant below.
#   - Where a value is an x/y canvas position for elements Streamlit lays out
#     via normal flow (panel order, left/right anchoring within a row), it is
#     translated into equivalent relative CSS (flexbox alignment, st.columns
#     ratios built from the spec's own pixel widths) rather than literal
#     position:absolute — see the column-ratio comments below.

import os
from typing import List

import streamlit as st
from dotenv import load_dotenv

from utils.styles import inject_theme_css
from utils.sidebar import render_sidebar, render_progress_bar
from utils.source_browser_logic import (
    FREQUENCY_OPTIONS,
    THIS_STAGE_KEY,
    all_filenames,
    append_audit_log,
    build_summary_text,
    completed_stages,
    files_by_name,
    get_source_groups,
    status_css_class,
)

load_dotenv()  # idempotent if Home.py already loaded it; keeps this page runnable standalone

# ---------------------------------------------------------------------------
# Page identity (build spec §7 header band + §5 sidebar nav label)
# ---------------------------------------------------------------------------
PAGE_KEY = THIS_STAGE_KEY  # "01_source_browser" — must match utils/sidebar.py's nav key for this page
TOTAL_STAGES = 8

# TODO: confirm against design — see build spec §3. The exact H1 copy for this
# page isn't given anywhere in the three source docs (only the subtitle is).
# "Source Browser" is inferred from the sidebar nav label ("01 Source Browser")
# with the stage number dropped, since the progress bar already shows
# "Stage 1 of 8".
PAGE_TITLE = "Source Browser"
PAGE_SUBTITLE = "FR-01 — file browser for source & frequency selection"

SESSIONS_PATH = os.environ.get("SESSIONS_PATH", "./data/sessions")

# Row/spacing constants lifted verbatim from build spec §7 (page 01 table).
FILE_ROW_SPACING_PX = 34
GROUP_HEADER_GAP_PX = 68 - FILE_ROW_SPACING_PX  # extra margin before a new group, on top of normal row spacing
BADGE_WIDTH_PX = 32.4
BADGE_HEIGHT_PX = 18
FREQUENCY_DROPDOWN_WIDTH_PX = 320
LOAD_BUTTON_WIDTH_PX = 190

st.set_page_config(page_title="HARTSPEC — Source Browser", layout="wide", initial_sidebar_state="expanded")

inject_theme_css()  # reads st.session_state["theme"], injects light/dark CSS variables (style guide §1)


# ---------------------------------------------------------------------------
# Session-state bootstrap
# ---------------------------------------------------------------------------
def _init_session_state() -> None:
    """Ensure the keys this page relies on exist.

    TODO: confirm against design — see build spec §3. The build spec (FR-19/
    FR-20) implies a session JSON with per-stage params and an audit log, but
    no canonical schema is written down in any of the three source docs. This
    is a self-contained placeholder; if a shared utils/session.py with an
    established schema already exists elsewhere in the codebase, these local
    keys should be replaced with calls into it so every page agrees on one
    contract.
    """
    st.session_state.setdefault("session_data", {"stages": {}, "audit_log": []})
    # Matches the build spec's demo state (spectrum_002.fits pre-selected in the
    # mocked summary bar text). A real deployment likely wants to start empty —
    # flagged rather than silently decided either way.
    st.session_state.setdefault("source_browser_selected_files", ["spectrum_002.fits"])
    st.session_state.setdefault("source_browser_frequency", FREQUENCY_OPTIONS[0])


_init_session_state()

_groups = get_source_groups()
_all_filenames = all_filenames(_groups)
_files_index = files_by_name(_groups)


# ---------------------------------------------------------------------------
# Selection callbacks
# ---------------------------------------------------------------------------
def _sync_selected_files_from_checkboxes() -> None:
    """Rebuild the ordered selected-files list from each file checkbox's state.

    Order follows group/file order in `_all_filenames`, not click order — a
    deliberate simplification; the "primary" file shown in the summary bar is
    just the first selected file in that fixed order.
    """
    st.session_state["source_browser_selected_files"] = [
        fn for fn in _all_filenames if st.session_state.get(f"file_cb_{fn}")
    ]


def _on_file_toggle() -> None:
    _sync_selected_files_from_checkboxes()


def _on_group_toggle(group_filenames: List[str]) -> None:
    """Select-all/none convenience toggle for a group's checkbox.

    TODO: confirm against design — the build spec shows a checkbox at the group
    header ("Group header row: 10x10 checkbox...") but doesn't say what it
    does. Implemented as "select all files in this group", since the FR-01
    file list can carry more than one file forward (page 02's validation table
    shows three files — a spectrum plus a PSS file — validated together), which
    also only makes sense if multi-select is the intended model. Flag if the
    real intent was something else (e.g. a collapse/expand control).
    """
    group_key = f"group_cb_{group_filenames[0]}"
    new_value = st.session_state[group_key]
    for fn in group_filenames:
        st.session_state[f"file_cb_{fn}"] = new_value
    _sync_selected_files_from_checkboxes()


# ---------------------------------------------------------------------------
# Page-scoped CSS
#
# Assumes inject_theme_css() has already defined CSS custom properties named
# after the style-guide §1 tokens (e.g. --bg-panel, --text-muted,
# --status-ok-bg). See the chat response for the full list assumed.
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <style>
    .hs-title {{
        font-family: 'Inter', sans-serif;
        font-size: 24px;
        font-weight: 700;
        color: var(--text-heading);
        margin: 0 0 2px 0;
    }}
    .hs-subtitle {{
        font-family: 'Inter', sans-serif;
        font-size: 13px;
        font-weight: 400;
        color: var(--text-muted);
        margin: 0 0 16px 0;
    }}
    .hs-panel-title {{
        font-family: 'Inter', sans-serif;
        font-size: 11px;
        font-weight: 600;
        color: var(--text-body);
        margin-bottom: 12px;
    }}
    .hs-eyebrow {{
        font-family: 'Inter', sans-serif;
        font-size: 10px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.03em;
        margin-bottom: 6px;
    }}
    .hs-group-header {{
        margin-top: {GROUP_HEADER_GAP_PX}px;
        margin-bottom: 8px;
    }}
    .hs-group-header:first-of-type {{ margin-top: 0; }}
    .hs-group-label {{
        font-family: 'Inter', sans-serif;
        font-size: 14px;
        font-weight: 600;
        color: var(--text-body);
    }}
    .hs-group-count {{
        font-family: 'Inter', sans-serif;
        font-size: 11px;
        color: var(--text-muted);
        margin-top: 4px;
    }}
    .hs-file-name {{
        font-family: 'Inter', sans-serif;
        font-size: 14px;
        color: var(--text-body);
        line-height: 1.2;
    }}
    .hs-file-caption {{
        font-family: 'Inter', sans-serif;
        font-size: 11px;
        color: var(--text-muted);
        margin-top: 2px;
    }}
    .hs-badge {{
        display: inline-block;
        min-width: {BADGE_WIDTH_PX}px;
        height: {BADGE_HEIGHT_PX}px;
        line-height: {BADGE_HEIGHT_PX}px;
        text-align: center;
        padding: 0 10px;
        border-radius: 9px;
        font-family: 'Inter', sans-serif;
        font-size: 10px;
        font-weight: 600;
        white-space: nowrap;
    }}
    .hs-badge-ok {{ background: var(--status-ok-bg); color: var(--status-ok-text); }}
    .hs-badge-warning {{ background: var(--status-warning-bg); color: var(--status-warning-text); }}
    .hs-badge-error {{ background: var(--status-error-bg); color: var(--status-error-text); }}
    .hs-badge-info {{ background: var(--status-info-bg); color: var(--status-info-text); }}
    .hs-summary-text {{
        font-family: 'Inter', sans-serif;
        font-size: 13px;
        color: var(--text-body);
    }}
    div[data-testid="stVerticalBlockBorderWrapper"] {{
        background: var(--bg-panel);
        border-color: var(--border-default) !important;
        border-radius: 8px !important;
    }}
    div[data-testid="stButton"] button {{
        border-radius: 6px;
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        font-size: 12px;
        height: 32px;
    }}
    div[data-testid="stCheckbox"] {{
        margin-bottom: {FILE_ROW_SPACING_PX - 24}px;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Sidebar + header band (build spec §7: identical position on every page)
# ---------------------------------------------------------------------------
render_sidebar(active_page_key=PAGE_KEY)
render_progress_bar(
    completed_stages=completed_stages(st.session_state["session_data"], PAGE_KEY),
    total_stages=TOTAL_STAGES,
)

st.markdown(f'<div class="hs-title">{PAGE_TITLE}</div>', unsafe_allow_html=True)
st.markdown(f'<div class="hs-subtitle">{PAGE_SUBTITLE}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Panel 1 — Sources & Frequencies: grouped file list
# build spec §7 p.01: x=244 y=104 w=1172 h=380
# ---------------------------------------------------------------------------
with st.container(border=True):
    st.markdown('<div class="hs-panel-title">Source Browser — FR-01</div>', unsafe_allow_html=True)

    for group in _groups:
        group_filenames = [f.filename for f in group.files]

        # Resync the group's own checkbox to reflect its children's current
        # state before instantiating it, so "select all" doesn't drift out of
        # sync when a file is unchecked individually. (No indeterminate state
        # is available on a plain st.checkbox — an all-or-nothing display is
        # the closest honest approximation.)
        group_key = f"group_cb_{group_filenames[0]}"
        st.session_state[group_key] = all(
            st.session_state.get(f"file_cb_{fn}", fn in st.session_state["source_browser_selected_files"])
            for fn in group_filenames
        )

        header_cols = st.columns([40, 1132])  # ratios derived from spec x=260 checkbox / label region
        with header_cols[0]:
            st.checkbox(
                f"Select all files in {group.label}",
                key=group_key,
                label_visibility="collapsed",
                on_change=_on_group_toggle,
                args=(group_filenames,),
            )
        with header_cols[1]:
            st.markdown(
                f'<div class="hs-group-header">'
                f'<span class="hs-group-label">{group.label}</span>'
                f'<div class="hs-group-count">{group.displayed_count} files</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        for source_file in group.files:
            file_key = f"file_cb_{source_file.filename}"
            st.session_state.setdefault(
                file_key, source_file.filename in st.session_state["source_browser_selected_files"]
            )

            # Column ratios derived from spec x-positions: checkbox+indent (54),
            # filename+caption (1048), right-anchored status badge (70).
            row_cols = st.columns([54, 1048, 70])
            with row_cols[0]:
                st.checkbox(
                    source_file.filename,
                    key=file_key,
                    label_visibility="collapsed",
                    on_change=_on_file_toggle,
                )
            with row_cols[1]:
                st.markdown(
                    f'<div class="hs-file-name">{source_file.filename}</div>'
                    f'<div class="hs-file-caption">{source_file.file_type} · '
                    f'{source_file.size_mb:.0f}MB</div>',
                    unsafe_allow_html=True,
                )
            with row_cols[2]:
                badge_class = status_css_class(source_file.status)
                st.markdown(
                    f'<span class="hs-badge hs-badge-{badge_class}">{source_file.status}</span>',
                    unsafe_allow_html=True,
                )


# ---------------------------------------------------------------------------
# Frequency picker (no border — sits directly on the page, 16px section gap)
# build spec §7 p.01: eyebrow y=500, dropdown y=518, w=320 (both outside the
# 380px-tall panel above, which ends at y=484 — 500-484=16px matches the
# style guide §3 section-gap token)
# ---------------------------------------------------------------------------
freq_col, _spacer_col = st.columns([FREQUENCY_DROPDOWN_WIDTH_PX, 1172 - FREQUENCY_DROPDOWN_WIDTH_PX])
with freq_col:
    st.markdown('<div class="hs-eyebrow">Frequency</div>', unsafe_allow_html=True)
    frequency = st.selectbox(
        "Frequency",
        options=FREQUENCY_OPTIONS,
        index=FREQUENCY_OPTIONS.index(st.session_state["source_browser_frequency"]),
        label_visibility="collapsed",
        key="source_browser_frequency",
    )


# ---------------------------------------------------------------------------
# Panel 2 — Selection summary bar
# build spec §7 p.01: x=244 y=570 w=1172 h=90; text and button both left-
# aligned at x=260, stacked vertically (button below text, not beside it)
# ---------------------------------------------------------------------------
selected_files = st.session_state["source_browser_selected_files"]

with st.container(border=True):
    summary_text = build_summary_text(selected_files, _files_index, st.session_state["source_browser_frequency"])
    st.markdown(f'<div class="hs-summary-text">{summary_text}</div>', unsafe_allow_html=True)
    st.write("")  # approximates the ~20px gap between summary text and button

    load_clicked = st.button(
        "Load into Pipeline →",
        type="primary",
        disabled=not selected_files,
        key="load_into_pipeline_btn",
    )

if load_clicked:
    session_data = st.session_state["session_data"]
    session_data["stages"][PAGE_KEY] = {
        "selected_files": selected_files,
        "frequency": st.session_state["source_browser_frequency"],
    }
    primary_label = selected_files[0] if len(selected_files) == 1 else f"{len(selected_files)} files"
    append_audit_log(session_data, f"Loaded {primary_label} into pipeline")

    # TODO: confirm against design — see build spec §3. Session persistence to
    # SESSIONS_PATH is not yet wired here since no canonical session-file naming
    # scheme is given in the three source docs (only that JSON files live under
    # /data/sessions/). Wire this up once utils/session.py (or equivalent) is
    # confirmed, rather than inventing a filename convention here.

    try:
        st.switch_page("pages/02_File_Loader.py")
    except Exception:
        st.rerun()
