# 01_Source_Browser.py — FR-01: file browser for source & frequency selection.
#
# Renders the grouped FITS/PSS file list, the frequency picker, and the
# selection-summary bar that hands the chosen file(s) off to
# 02_File_Loader.py. Layout/coordinates follow HARTSPEC-Page_Build_Spec.md §7
# (page 01). Colors, type, session persistence, and shared chrome all come
# from the project's real utils modules rather than being reimplemented here:
#   - utils/styles.py    -> inject_base_css(), get_theme(), render_badge(),
#                            render_page_header() (title + subtitle + the
#                            pipeline progress bar, all in one call)
#   - utils/sidebar.py    -> render_sidebar(current_stage) (nav, theme
#                            toggle, Save/Load/Reset — fully self-contained)
#   - utils/session_store.py -> init_session_state(), log_event(),
#                            mark_stage_complete(), completed_count()
#
# Streamlit renders as a fluid HTML flow, not an absolute-position canvas
# (utils/styles.py's own module docstring makes the same point). Pixel
# values from the build spec are applied two ways:
#   - Fixed-size tokens (font sizes, row heights, radii, gaps) are applied
#     literally, as page-local constants below.
#   - x/y canvas positions for elements laid out via normal flow are
#     translated into relative CSS / st.columns ratios built from the
#     spec's own pixel widths, rather than literal position:absolute.

from typing import List

import streamlit as st

from utils import session_store, sidebar, styles
from utils.source_browser_logic import (
    FREQUENCY_OPTIONS,
    THIS_STAGE_KEY,
    all_filenames,
    build_summary_text,
    files_by_name,
    get_source_groups,
    status_css_class,
)

# ---------------------------------------------------------------------------
# Page identity
# ---------------------------------------------------------------------------
PAGE_STAGE_KEY = THIS_STAGE_KEY  # key used in session_store's pipeline_data / completed_stages
CURRENT_STAGE = 1  # 1-indexed — matches sidebar.STAGES order and styles.render_page_header

# TODO: confirm against design — see build spec §3. The exact H1 copy for this
# page isn't given anywhere in the three source docs (only the subtitle is).
# "Source Browser" is inferred from the sidebar nav label ("01  Source
# Browser") with the stage number dropped, since the progress bar already
# shows "Stage 1 of 8".
PAGE_TITLE = "Source Browser"
PAGE_SUBTITLE = "FR-01 — file browser for source & frequency selection"

# Row/spacing constants lifted verbatim from build spec §7 (page 01 table).
FILE_ROW_SPACING_PX = 34
GROUP_HEADER_GAP_PX = 68 - FILE_ROW_SPACING_PX  # extra margin before a new group, on top of normal row spacing
FREQUENCY_DROPDOWN_WIDTH_PX = 320

st.set_page_config(page_title="HARTSPEC — Source Browser", layout="wide", initial_sidebar_state="expanded")

# Every page calls this before touching st.session_state, per session_store.py's
# own module docstring — safe/idempotent even though render_sidebar() below
# also calls it defensively.
session_store.init_session_state()

sidebar.render_sidebar(current_stage=CURRENT_STAGE)
styles.inject_base_css()


# ---------------------------------------------------------------------------
# Page-local session state (working selections, not yet committed to
# session_store's pipeline_data — that only happens on "Load into Pipeline")
# ---------------------------------------------------------------------------
def _init_page_state() -> None:
    # Matches the build spec's demo state (spectrum_002.fits pre-selected in
    # the mocked summary bar text). A real deployment likely wants to start
    # empty — flagged rather than silently decided either way.
    st.session_state.setdefault("source_browser_selected_files", ["spectrum_002.fits"])
    st.session_state.setdefault("source_browser_frequency", FREQUENCY_OPTIONS[0])


_init_page_state()

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
# Page-scoped CSS — only for the handful of classes utils/styles.py's
# inject_base_css() doesn't already define (.hs-title/.hs-subtitle/.hs-panel/
# .hs-panel-title/.hs-eyebrow/.hs-badge and the button/selectbox rules are
# already global; no need to redefine them here). Colors come from
# styles.get_theme() rather than CSS custom properties, since that's how
# inject_base_css() itself does it — this file matches that same pattern
# instead of introducing a var(--x) convention the rest of the app doesn't use.
# ---------------------------------------------------------------------------
_theme = styles.get_theme()

st.markdown(
    f"""
    <style>
    .hs-group-header {{
        margin-top: {GROUP_HEADER_GAP_PX}px;
        margin-bottom: 8px;
    }}
    .hs-group-header:first-of-type {{ margin-top: 0; }}
    .hs-group-label {{
        font-size: 14px;
        font-weight: 600;
        color: {_theme['text-body']};
    }}
    .hs-group-count {{
        font-size: 11px;
        color: {_theme['text-muted']};
        margin-top: 4px;
    }}
    .hs-file-name {{
        font-size: 14px;
        color: {_theme['text-body']};
        line-height: 1.2;
    }}
    .hs-file-caption {{
        font-size: 11px;
        color: {_theme['text-muted']};
        margin-top: 2px;
    }}
    .hs-summary-text {{
        font-size: 13px;
        color: {_theme['text-body']};
    }}
    /* utils/styles.py already sets a border-radius on this test id for
       st.container(border=True); this only adds the section-gap margin the
       raw .hs-panel div class gets for free, so panels built from real
       Streamlit widgets fall in line with panels built from render_panel_open/close. */
    [data-testid="stVerticalBlockBorderWrapper"] {{
        margin-bottom: {styles.SECTION_GAP}px;
    }}
    div[data-testid="stCheckbox"] {{
        margin-bottom: {FILE_ROW_SPACING_PX - 24}px;
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
# Panel 1 — Sources & Frequencies: grouped file list
# build spec §7 p.01: x=244 y=104 w=1172 h=380
#
# Uses st.container(border=True) rather than styles.render_panel_open/close:
# those two helpers open/close a raw <div class="hs-panel"> across separate
# st.markdown calls, which doesn't actually enclose *live* Streamlit widgets
# (checkboxes, in this case) rendered in between — each st.markdown call is
# its own isolated HTML fragment, so the div doesn't stay open across them.
# st.container(border=True) is the one that visually groups real widgets, and
# utils/styles.py already has a border-radius rule for it
# ([data-testid="stVerticalBlockBorderWrapper"]), so this isn't introducing a
# pattern the rest of the CSS doesn't anticipate.
# TODO: confirm against design — st.container(border=True) uses Streamlit's
# default border/background rather than the exact bg-panel/border-default
# hex tokens; if pixel-exact panel fill/border matters, that rule in
# utils/styles.py is the right place to add background-color/border-color too
# (it would then apply to every page consistently, not just this one).
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
                st.markdown(
                    styles.render_badge(source_file.status, status_css_class(source_file.status)),
                    unsafe_allow_html=True,
                )


# ---------------------------------------------------------------------------
# Frequency picker (no border — sits directly on the page, 16px section gap)
# build spec §7 p.01: eyebrow y=500, dropdown y=518, w=320 (both outside the
# 380px-tall panel above, which ends at y=484 — 500-484=16px matches the
# style guide §3 section-gap token, i.e. styles.SECTION_GAP)
# ---------------------------------------------------------------------------
freq_col, _spacer_col = st.columns(
    [FREQUENCY_DROPDOWN_WIDTH_PX, styles.CONTENT_WIDTH - FREQUENCY_DROPDOWN_WIDTH_PX]
)
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
    st.session_state["pipeline_data"][PAGE_STAGE_KEY] = {
        "selected_files": selected_files,
        "frequency": st.session_state["source_browser_frequency"],
    }
    session_store.mark_stage_complete(PAGE_STAGE_KEY)

    primary_label = selected_files[0] if len(selected_files) == 1 else f"{len(selected_files)} files"
    session_store.log_event(f"Loaded {primary_label} into pipeline")

    st.switch_page("pages/02_File_Loader.py")
