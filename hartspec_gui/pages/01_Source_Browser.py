# 01_Source_Browser.py — FR-01: Source & Frequency Browser.
#
# Replaces clc's Interact.py (terminal menu — naturally superseded by real
# Streamlit widgets) and clc's File_check.py (file sorting — see the
# run_file_check_placeholder() call below, which is NOT yet the real
# integration; clc/File_check.py's actual signature wasn't available when
# this was written).
#
# Flow: a user-editable FITS directory path -> a live directory-tree scan
# (FITS-only, .fits/.fit) -> Source Name / Frequency filter dropdowns
# populated from what's actually found -> a nested-expander tree view of the
# matching files -> on "Load into Pipeline", the filtered FITS paths, chosen
# source name, chosen frequency, and earliest observation date are written to
# st.session_state (via utils/session_store.py's pipeline_data) — nothing is
# written to disk permanently by this page itself, aside from the (currently
# placeholder) File_check.py-driven observation-block files in the session's
# workspace folder.
#
# Shared chrome/session logic comes from the project's real utils modules:
#   - utils/styles.py         -> inject_base_css(), get_theme(), render_badge(),
#                                 render_page_header()
#   - utils/sidebar.py        -> render_sidebar(current_stage)
#   - utils/session_store.py  -> init_session_state(), log_event(),
#                                 mark_stage_complete(), completed_count(),
#                                 SESSIONS_DIR

from pathlib import Path

import streamlit as st

from utils import session_store, sidebar, styles
from utils.source_browser_logic import (
    THIS_STAGE_KEY,
    build_summary_text,
    default_fits_directory,
    distinct_frequencies_mhz,
    distinct_source_names,
    earliest_observation_date,
    matching_files,
    run_file_check_placeholder,
    scan_fits_directory_tree,
    status_css_class,
)

# ---------------------------------------------------------------------------
# Page identity
# ---------------------------------------------------------------------------
PAGE_STAGE_KEY = THIS_STAGE_KEY
CURRENT_STAGE = 1  # 1-indexed — matches sidebar.STAGES order and styles.render_page_header

# TODO: confirm against design. The exact H1 copy isn't given anywhere in the
# source docs; inferred from the sidebar nav label ("01  Source Browser")
# with the stage number dropped, since the progress bar already shows
# "Stage 1 of 8".
PAGE_TITLE = "Source Browser"
PAGE_SUBTITLE = "FR-01 — source & frequency browser"

st.set_page_config(page_title="HARTSPEC — Source Browser", layout="wide", initial_sidebar_state="expanded")

# Every page calls this before touching st.session_state, per session_store.py's
# own module docstring — safe/idempotent even though render_sidebar() below
# also calls it defensively.
session_store.init_session_state()

sidebar.render_sidebar(current_stage=CURRENT_STAGE)
styles.inject_base_css()


# ---------------------------------------------------------------------------
# Page-scoped CSS — only for classes utils/styles.py's inject_base_css()
# doesn't already define (.hs-title/.hs-subtitle/.hs-panel/.hs-panel-title/
# .hs-eyebrow/.hs-badge and the button/selectbox rules are already global).
# Colors come from styles.get_theme() rather than CSS custom properties,
# matching how inject_base_css() itself does it.
# ---------------------------------------------------------------------------
_theme = styles.get_theme()

st.markdown(
    f"""
    <style>
    .hs-file-name {{
        font-size: 13px;
        color: {_theme['text-body']};
        line-height: 1.3;
    }}
    .hs-file-caption {{
        font-size: 11px;
        color: {_theme['text-muted']};
        margin-bottom: 8px;
    }}
    .hs-summary-text {{
        font-size: 13px;
        color: {_theme['text-body']};
    }}
    [data-testid="stVerticalBlockBorderWrapper"] {{
        margin-bottom: {styles.SECTION_GAP}px;
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
# Directory path input
# ---------------------------------------------------------------------------
st.session_state.setdefault("source_browser_fits_dir", default_fits_directory())

st.markdown('<div class="hs-eyebrow">FITS Directory</div>', unsafe_allow_html=True)
fits_dir_str = st.text_input(
    "FITS directory",
    key="source_browser_fits_dir",
    label_visibility="collapsed",
)


@st.cache_data(ttl=30, show_spinner="Scanning FITS directory…")
def _cached_scan(directory: str):
    """Cached wrapper around scan_fits_directory_tree().

    Streamlit reruns this whole script on every widget interaction — without
    caching, every dropdown change would re-walk the directory and re-read
    every FITS header from disk again. A 30s TTL keeps browsing snappy while
    still picking up newly-arrived files within half a minute.
    """
    return scan_fits_directory_tree(Path(directory))


tree = _cached_scan(fits_dir_str)

if tree is None:
    st.markdown(
        f'<div class="hs-file-caption">Directory "{fits_dir_str}" was not found. '
        f'Check the path and try again.</div>',
        unsafe_allow_html=True,
    )
    st.stop()


# ---------------------------------------------------------------------------
# Source Name / Frequency filter dropdowns — options come from what's
# actually found on disk, not a fixed list.
# ---------------------------------------------------------------------------
source_options = distinct_source_names(tree)
frequency_options = distinct_frequencies_mhz(tree)

if not source_options or not frequency_options:
    st.markdown(
        '<div class="hs-file-caption">No FITS files with readable source/frequency headers '
        'were found in this directory yet.</div>',
        unsafe_allow_html=True,
    )
    st.stop()

# Reset a stored selection that's no longer valid (e.g. the user changed the
# directory and the previously-selected source name doesn't exist here) —
# st.selectbox raises if its stored value isn't in the current options list.
if st.session_state.get("source_browser_source_name") not in source_options:
    st.session_state["source_browser_source_name"] = source_options[0]
if st.session_state.get("source_browser_frequency_mhz") not in frequency_options:
    st.session_state["source_browser_frequency_mhz"] = frequency_options[0]

filter_cols = st.columns(2)
with filter_cols[0]:
    st.markdown('<div class="hs-eyebrow">Source Name</div>', unsafe_allow_html=True)
    selected_source = st.selectbox(
        "Source Name",
        options=source_options,
        key="source_browser_source_name",
        label_visibility="collapsed",
    )
with filter_cols[1]:
    st.markdown('<div class="hs-eyebrow">Frequency</div>', unsafe_allow_html=True)
    selected_frequency = st.selectbox(
        "Frequency",
        options=frequency_options,
        format_func=lambda f: f"{f:.3f} MHz",
        key="source_browser_frequency_mhz",
        label_visibility="collapsed",
    )


# ---------------------------------------------------------------------------
# Directory tree view — nested expandable containers, pruned to only show
# branches that contain at least one file matching the current filters.
# ---------------------------------------------------------------------------
def _render_tree(node, source_filter, frequency_filter, depth: int = 0) -> None:
    if node is None or not matching_files(node, source_filter, frequency_filter):
        return  # prune branches with nothing matching, at any depth

    with st.expander(node.name or "/", expanded=(depth == 0)):
        for source_file in node.files:
            if source_file.source_name != source_filter or source_file.frequency_mhz != frequency_filter:
                continue
            badge_html = styles.render_badge(source_file.status, status_css_class(source_file.status))
            st.markdown(
                f'<div class="hs-file-name">{source_file.filename}</div>'
                f'<div class="hs-file-caption">{source_file.size_mb:.1f}MB · {badge_html}</div>',
                unsafe_allow_html=True,
            )
        for child in node.subdirectories:
            _render_tree(child, source_filter, frequency_filter, depth + 1)


with st.container(border=True):
    st.markdown('<div class="hs-panel-title">Source Browser — FR-01</div>', unsafe_allow_html=True)
    _render_tree(tree, selected_source, selected_frequency)


# ---------------------------------------------------------------------------
# Selection summary + "Load into Pipeline"
# ---------------------------------------------------------------------------
filtered_files = matching_files(tree, selected_source, selected_frequency)
earliest_date = earliest_observation_date(filtered_files)

with st.container(border=True):
    summary_text = build_summary_text(filtered_files, selected_source, selected_frequency, earliest_date)
    st.markdown(f'<div class="hs-summary-text">{summary_text}</div>', unsafe_allow_html=True)
    st.write("")

    load_clicked = st.button(
        "Load into Pipeline →",
        type="primary",
        disabled=not filtered_files,
        key="load_into_pipeline_btn",
    )

if load_clicked:
    # TODO: NOT the real clc.File_check integration — see run_file_check_placeholder()'s
    # own docstring in utils/source_browser_logic.py. Replace once clc/File_check.py's
    # signature is confirmed.
    workspace_dir = session_store.SESSIONS_DIR / st.session_state["session_id"] / "workspace"
    run_file_check_placeholder([f.path for f in filtered_files], workspace_dir)

    st.session_state["pipeline_data"][PAGE_STAGE_KEY] = {
        "fits_file_paths": [str(f.path) for f in filtered_files],
        "source_name": selected_source,
        "frequency_mhz": selected_frequency,
        "earliest_observation_date": earliest_date,
    }
    session_store.mark_stage_complete(PAGE_STAGE_KEY)

    session_store.log_event(
        f"Loaded {len(filtered_files)} file(s) for {selected_source} at {selected_frequency:.3f} MHz"
    )

    st.switch_page("pages/02_File_Loader.py")
