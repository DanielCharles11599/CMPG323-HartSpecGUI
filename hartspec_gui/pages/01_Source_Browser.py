# 01_Source_Browser.py — FR-01: Source & Frequency Browser.
#
# Replaces clc's Interact.py (terminal menu — naturally superseded by real
# Streamlit widgets) and runs clc's File_check.py (observation-block sorting)
# for real on "Load into Pipeline" — see run_observation_block_sort() in
# utils/source_browser_logic.py and File_check.run_file_check().
#
# Flow: a user-editable FITS directory path -> a live directory-tree scan
# (FITS-only, .fits/.fit) -> Source Name / Frequency filter dropdowns
# populated from what's actually found -> a nested-expander tree view of the
# matching files -> on "Load into Pipeline", the filtered FITS paths, chosen
# source name, chosen frequency, and earliest observation date are written to
# st.session_state (via utils/session_store.py's pipeline_data) — nothing is
# written to disk permanently by this page itself, aside from the File_check.py
# observation-block files in the session's workspace folder.
#
# UAT-feedback revision (system owners):
#   1. The FITS directory can now be picked with a "Browse…" button that
#      opens an in-page folder navigator (Up / open subfolder / "Select this
#      folder"); the chosen path is written into the text box automatically.
#      The text box still works for pasting a path.
#   2. The Source Browser panel is a fixed-height, scrollable panel, so the
#      selection summary and "Load into Pipeline" stay reachable on a large
#      archive.
#   3. "Load into Pipeline" runs the real clc.File_check (Phase 0 revision)
#      instead of the placeholder. If File_check fails, the page says so and
#      offers "Continue without block sorting" rather than blocking the hand-off.
#
# 2026-08-28 fix: "Load into Pipeline" used to write the selected files only
# under the "fits_file_paths" key. 02_File_Loader.py reads a "selected_files"
# key that this page never wrote, so it always fell back to its own dev
# default regardless of what was picked here. Now writes both keys -- see
# utils/source_browser_logic.py's build_selected_files() for the details.
#
# Shared chrome/session logic comes from the project's real utils modules:
#   - utils/styles.py         -> inject_base_css(), get_theme(), render_badge(),
#                                 render_page_header()
#   - utils/sidebar.py        -> render_sidebar(current_stage)
#   - utils/session_store.py  -> init_session_state(), log_event(),
#                                 mark_stage_complete(), completed_count(),
#                                 SESSIONS_DIR

import html
import uuid
from pathlib import Path

import streamlit as st

from utils import fits_ingest, session_store, sidebar, stage_invalidation, styles
from utils.source_browser_logic import (
    THIS_STAGE_KEY,
    build_selected_files,
    build_summary_text,
    count_fits_files,
    default_fits_directory,
    distinct_frequencies_mhz,
    distinct_source_names,
    earliest_observation_date,
    filter_by_filename,
    group_files_by_month,
    latest_observation_date,
    list_subdirectories,
    matching_files,
    parent_directory,
    run_observation_block_sort,
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
PAGE_SUBTITLE = "Source & frequency browser"

# Scrollable panel heights (px). TODO: confirm against design — build spec §7 gives the whole Sources & Frequencies
# panel as 380px tall (title + list); 320 leaves room for the panel title inside that.
BROWSER_PANEL_HEIGHT = 320
FOLDER_LIST_HEIGHT = 240

# session_state keys for the folder navigator and the File_check error hand-off
KEY_BROWSE_OPEN = "source_browser_browse_open"
KEY_BROWSE_PATH = "source_browser_browse_path"
KEY_SORT_ERROR = "source_browser_file_check_error"

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
        font-size: 0.8125rem;
        color: {_theme['text-body']};
        line-height: 1.3;
    }}
    .hs-file-caption {{
        font-size: 0.6875rem;
        color: {_theme['text-muted']};
        margin-bottom: 8px;
    }}
    .hs-summary-text {{
        font-size: 0.8125rem;
        color: {_theme['text-body']};
    }}
    [data-testid="stVerticalBlockBorderWrapper"] {{
        margin-bottom: {styles.SECTION_GAP}px;
    }}
    /* Scrollable containers nested inside a bordered panel shouldn't add a second gap. */
    [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlockBorderWrapper"] {{
        margin-bottom: 0;
    }}
    /* The month-grouped browse view (group_files_by_month()) renders one
       st.expander() per group. Both the header text and the panel border
       are native Streamlit chrome, not HTML this page controls -- they
       fall back to Streamlit's static base theme (.streamlit/config.toml),
       which doesn't react to st.session_state["theme"] (Style Guide §5).
       Same root cause and same fix as 02_File_Loader.py's expander/widget
       CSS: forced here with theme tokens and !important, since Streamlit's
       own expander CSS carries specificity a plain rule won't reliably
       beat. border-default is the Style Guide's token for card/input
       borders generally, which an expander panel matches.
    */
    /* These overrides belong to Page 01's main content only. Do not let
       them recolor the shared sidebar's session expanders/widgets. */
    [data-testid="stAppViewContainer"] [data-testid="stExpander"] {{
        border-color: {_theme['border-default']} !important;
    }}
    [data-testid="stAppViewContainer"] [data-testid="stExpander"] summary,
    [data-testid="stAppViewContainer"] [data-testid="stExpander"] summary p,
    [data-testid="stAppViewContainer"] [data-testid="stExpander"] summary span,
    [data-testid="stAppViewContainer"] .streamlit-expanderHeader,
    [data-testid="stAppViewContainer"] .streamlit-expanderHeader p {{
        color: {_theme['text-body']} !important;
    }}
    [data-testid="stAppViewContainer"] [data-testid="stExpanderToggleIcon"] {{
        fill: {_theme['text-body']} !important;
        color: {_theme['text-body']} !important;
    }}
    [data-testid="stAppViewContainer"] [data-testid="stTextInput"] input {{
        color: {_theme['text-body']} !important;
    }}
    [data-testid="stAppViewContainer"] [data-testid="stTextInput"] input::placeholder {{
        color: {_theme['text-faint']} !important;
        opacity: 1;
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
# Directory path input + folder navigator
#
# Streamlit has no native folder picker, and a tkinter dialog would open on the
# *server* (this runs on a headless intranet box), not in the user's browser. So
# the "Browse…" button opens an in-page navigator over the server-visible
# filesystem. Its callbacks (on_click) run *before* the script reruns, which is
# the only point at which a widget's session_state key (the text box) may be
# overwritten — that is how "Select this folder" fills the text box in.
# ---------------------------------------------------------------------------
def _toggle_folder_browser() -> None:
    """Open/close the navigator, starting from the text box's current folder (or its nearest existing parent)."""
    st.session_state[KEY_BROWSE_OPEN] = not st.session_state.get(KEY_BROWSE_OPEN, False)
    start = Path(str(st.session_state.get("source_browser_fits_dir", "")).strip()).expanduser()
    while not start.is_dir() and start != start.parent:
        start = start.parent
    st.session_state[KEY_BROWSE_PATH] = str(start)


def _browse_to(path: str) -> None:
    """Navigate the folder navigator to `path`."""
    st.session_state[KEY_BROWSE_PATH] = path


def _choose_folder(path: str) -> None:
    """Write `path` into the FITS-directory text box and close the navigator."""
    st.session_state["source_browser_fits_dir"] = path
    st.session_state[KEY_BROWSE_OPEN] = False


def _close_folder_browser() -> None:
    st.session_state[KEY_BROWSE_OPEN] = False


def _render_folder_browser() -> None:
    """Fixed-height, scrollable folder list with Up / Select / Cancel controls."""
    current = Path(st.session_state[KEY_BROWSE_PATH])
    parent = parent_directory(current)
    subdirectories, truncated = list_subdirectories(current)

    with st.container(border=True):
        st.markdown('<div class="hs-panel-title">Select FITS folder</div>', unsafe_allow_html=True)
        fits_here = count_fits_files(current)
        st.markdown(
            f'<div class="hs-file-caption">{html.escape(str(current))} · '
            f'{fits_here} FITS file{"s" if fits_here != 1 else ""} directly in this folder</div>',
            unsafe_allow_html=True,
        )
        up_col, select_col, cancel_col, _spacer = st.columns([1, 2, 1, 4])
        with up_col:
            st.button("↑ Up", key="source_browser_up_btn", on_click=_browse_to, args=(str(parent),),
                      disabled=(parent == current), use_container_width=True)
        with select_col:
            st.button("Select this folder", key="source_browser_select_btn", type="primary",
                      on_click=_choose_folder, args=(str(current),), use_container_width=True)
        with cancel_col:
            st.button("Cancel", key="source_browser_cancel_btn", on_click=_close_folder_browser,
                      use_container_width=True)

        with st.container(height=FOLDER_LIST_HEIGHT):
            if not subdirectories:
                st.markdown('<div class="hs-file-caption">No subfolders here.</div>', unsafe_allow_html=True)
            for index, subdirectory in enumerate(subdirectories):
                st.button(f"{subdirectory.name}/", key=f"source_browser_nav_{index}", on_click=_browse_to,
                          args=(str(subdirectory),), use_container_width=True)
            if truncated:
                st.markdown(
                    '<div class="hs-file-caption">Only the first folders are listed — type the path above '
                    'to go deeper.</div>',
                    unsafe_allow_html=True,
                )


st.session_state.setdefault("source_browser_fits_dir", default_fits_directory())

st.markdown('<div class="hs-eyebrow">FITS Directory</div>', unsafe_allow_html=True)
_dir_input_col, _browse_btn_col = st.columns([6, 1])
with _dir_input_col:
    fits_dir_str = st.text_input(
        "FITS directory",
        key="source_browser_fits_dir",
        label_visibility="collapsed",
    )
with _browse_btn_col:
    st.button("Browse…", key="source_browser_browse_btn", on_click=_toggle_folder_browser,
              use_container_width=True)

if st.session_state.get(KEY_BROWSE_OPEN):
    _render_folder_browser()


@st.cache_data(ttl=30, show_spinner="Scanning FITS directory…")
def _cached_scan(directory: str):
    """Cached wrapper around scan_fits_directory_tree().

    Streamlit reruns this whole script on every widget interaction — without
    caching, every dropdown change would re-walk the directory and re-read
    every FITS header from disk again. A 30s TTL keeps browsing snappy while
    still picking up newly-arrived files within half a minute.
    """
    return scan_fits_directory_tree(Path(directory))


tree = _cached_scan(fits_dir_str.strip())

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
    # TODO: confirm against design — build spec §7 shows this dropdown as
    # "1420.405 MHz — HI line" (frequency plus a human-readable line name).
    # No frequency -> line-name mapping is confirmed anywhere in utils/ yet
    # (only 1420.405 MHz = HI is stated in the spec; other maser lines
    # HARTSPEC monitors aren't), so this shows bare MHz values rather than
    # guessing a mapping table.
    selected_frequency = st.selectbox(
        "Frequency",
        options=frequency_options,
        format_func=lambda f: f"{f:.3f} MHz",
        key="source_browser_frequency_mhz",
        label_visibility="collapsed",
    )


# ---------------------------------------------------------------------------
# Filtered file set — computed once, up front, so the browse panel below
# groups/searches the already-narrowed result rather than walking the whole
# scanned tree. Source Name + Frequency still do the heavy narrowing; the
# search box below is a further, optional refinement on top of that.
# ---------------------------------------------------------------------------
source_frequency_matches = matching_files(tree, selected_source, selected_frequency)

st.markdown('<div class="hs-eyebrow">Search filename</div>', unsafe_allow_html=True)
filename_search = st.text_input(
    "Search filename",
    key="source_browser_filename_search",
    label_visibility="collapsed",
    placeholder="e.g. spectrum_002",
)
filtered_files = filter_by_filename(source_frequency_matches, filename_search)


# ---------------------------------------------------------------------------
# Browse panel — grouped by observation month (newest first), not a raw
# directory tree. A real monitoring archive can have hundreds of files under
# one Source Name / Frequency combination; mirroring on-disk folder
# structure (which may not even be date-organized) doesn't scale for
# browsing that, which is what the build spec's original month-grouped
# design was for. Only the newest group starts expanded so the page isn't a
# wall of files by default.
# ---------------------------------------------------------------------------
def _file_rows_html(group_files) -> str:
    """One HTML block for a whole month group (one st.markdown per group, not per file — hundreds of files stay fast).

    Position (HPN/HPS/HPE/HPW/ON/OFF, from HDU 2's POSITION keyword) is shown for the user's own information only —
    this is NOT File_check.py's observation-block sorting, just the raw per-file tag.
    """
    rows = []
    for source_file in group_files:
        badge_html = styles.render_badge(source_file.status, status_css_class(source_file.status))
        position_label = f" · {html.escape(source_file.position)}" if source_file.position else ""
        rows.append(
            f'<div class="hs-file-name">{html.escape(source_file.filename)}</div>'
            f'<div class="hs-file-caption">{source_file.size_mb:.1f}MB{position_label} · {badge_html}</div>'
        )
    return "".join(rows)


with st.container(border=True):
    st.markdown('<div class="hs-panel-title">Source Browser</div>', unsafe_allow_html=True)

    # Fixed height + internal scrolling (UAT feedback): the page itself no longer grows with the archive, so the
    # selection summary and "Load into Pipeline" below stay in reach.
    with st.container(height=BROWSER_PANEL_HEIGHT):
        if not filtered_files:
            st.markdown(
                '<div class="hs-file-caption">No files match the current filters/search.</div>',
                unsafe_allow_html=True,
            )
        else:
            for group_index, (group_label, group_files) in enumerate(group_files_by_month(filtered_files)):
                group_header = f"{group_label} ({len(group_files)} file{'s' if len(group_files) != 1 else ''})"
                with st.expander(group_header, expanded=(group_index == 0)):
                    st.markdown(_file_rows_html(group_files), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Selection summary + "Load into Pipeline"
# ---------------------------------------------------------------------------
earliest_date = earliest_observation_date(filtered_files)
latest_date = latest_observation_date(filtered_files)

with st.container(border=True):
    summary_text = build_summary_text(filtered_files, selected_source, selected_frequency, earliest_date, latest_date)
    st.markdown(f'<div class="hs-summary-text">{summary_text}</div>', unsafe_allow_html=True)

    # Non-blocking: 03_Bandpass_Correction.py's own _detect_bandpass_pair()
    # returns None (not a raise) when fewer than two full-integration spectra
    # were loaded, since freq/pos-switch correction needs a pair. Warning
    # here, where the user can still change filters, is more useful than
    # letting them find out three pages later. (Corrected from an earlier
    # version of this comment, which cited a bandpass_correction_logic.
    # get_raw_pair() function that doesn't actually exist -- page 03 does
    # this detection itself, as a page-local function, not via that module.)
    if len(filtered_files) == 1:
        st.markdown(
            '<div class="hs-file-caption">Bandpass correction (Stage 3) needs at least two '
            'matching FITS files (e.g. a signal/reference pair) — only one currently matches '
            'these filters.</div>',
            unsafe_allow_html=True,
        )

    st.caption(
        "Changed inputs start a new reduction and clear downstream results. "
        "Committed stages are checkpointed automatically. Save Session keeps a manual snapshot. "
        "Unchanged inputs keep existing progress."
    )
    st.write("")

    load_clicked = st.button(
        "Load into Pipeline →",
        type="primary",
        disabled=not filtered_files,
        key="load_into_pipeline_btn",
    )


def _selection_payload(outcome=None, error_message=None) -> dict:
    """Build the same handoff for comparison, sorting success and explicit bypass.

    Absolute paths and the archive root preserve input identity across a later
    environment-path change. File order stays exactly as in the filtered list.
    """
    archive_root = fits_ingest.get_archive_root().expanduser().resolve()
    return {
        "fits_file_paths": [str(f.path.resolve()) for f in filtered_files],
        "selected_files": build_selected_files(filtered_files),
        "archive_root": str(archive_root),
        "browser_directory": fits_dir_str.strip(),
        "filename_search": filename_search,
        "source_name": selected_source,
        "frequency_mhz": selected_frequency,
        "earliest_observation_date": earliest_date,
        "observation_blocks": outcome.blocks if outcome else {},
        "discarded_files": outcome.discarded_files if outcome else [],
        "file_check_workspace": str(outcome.work_dir) if outcome else None,
        "file_check_error": error_message,
    }


def _reserve_selection_session_id() -> str:
    """Reserve a new workspace ID without overwriting a saved reduction.

    The existing File_check wrapper replaces its observation workspace. Sort
    into a newly reserved session directory, not the active reduction's one,
    so even a failed sorting attempt cannot destroy that reduction's block files.
    The directory may remain after a cancelled/failed attempt; no old files are
    deleted here. Exclusive mkdir also prevents two attempts reserving one ID.
    """
    sessions_dir = session_store.SESSIONS_DIR
    sessions_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        candidate = uuid.uuid4().hex[:8]
        if candidate == st.session_state["session_id"]:
            continue
        if (sessions_dir / f"{candidate}.json").exists():
            continue
        if (sessions_dir / f"{candidate}.baseline_editor.json").exists():
            continue
        try:
            (sessions_dir / candidate).mkdir()
        except FileExistsError:
            continue
        return candidate
    raise OSError("Could not reserve a fresh reduction workspace. Please try again.")


def _continue_unchanged() -> None:
    """Reopen File Loader without clearing results or rerunning block sorting."""
    st.session_state.pop(KEY_SORT_ERROR, None)
    session_store.log_event("Source selection unchanged — existing reduction results retained")
    session_store.checkpoint_session("Source selection committed")
    st.switch_page("pages/02_File_Loader.py")


def _commit_and_continue(outcome, error_message, new_session_id: str) -> None:
    """Commit confirmed inputs, isolate their results, log once, then open Page 2.

    A fresh ID prevents even delayed writes by the previous Dash iframe from
    reintroducing that observation's baseline. Saved JSON/bridge files are not
    removed; the audit history is carried into the new reduction in memory.
    """
    previous_id = st.session_state["session_id"]
    payload = _selection_payload(outcome, error_message)
    try:
        changed = stage_invalidation.commit_source_selection(
            st.session_state, payload,
            archive_root=fits_ingest.get_archive_root(), new_session_id=new_session_id,
        )
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        st.error(f"Could not commit the new selection: {exc}. The active reduction was not changed.")
        return
    if not changed:
        _continue_unchanged()
        return
    session_store.log_event(
        f"Source selection committed — reduction {previous_id} → {new_session_id}; "
        "previous loading, bandpass, baseline, calibration, pointing, fitting and export results cleared"
    )
    session_store.log_event(
        f"Loaded {len(filtered_files)} file(s) for {selected_source} at {selected_frequency:.3f} MHz"
    )
    if outcome:
        session_store.log_event(
            f"File_check sorted {len(outcome.blocks)} observation block(s); "
            f"{len(outcome.discarded_files)} file(s) discarded"
        )
    else:
        session_store.log_event(f"File_check did not complete ({error_message}); continuing without block sorting")
    st.session_state.pop(KEY_SORT_ERROR, None)
    session_store.checkpoint_session("Source selection committed")
    st.switch_page("pages/02_File_Loader.py")


selection_signature = stage_invalidation.source_selection_signature(
    _selection_payload(), fits_ingest.get_archive_root(),
) if filtered_files else None

if load_clicked:
    if not stage_invalidation.source_selection_changed(
        st.session_state, _selection_payload(), fits_ingest.get_archive_root(),
    ):
        _continue_unchanged()
    else:
        try:
            candidate_session_id = _reserve_selection_session_id()
        except OSError as exc:
            st.error(f"Could not prepare the new reduction: {exc}. The active selection was not changed.")
        else:
            workspace_dir = session_store.SESSIONS_DIR / candidate_session_id / "workspace"
            try:
                with st.spinner("Sorting observation blocks (File_check)…"):
                    sort_outcome = run_observation_block_sort(
                        filtered_files, workspace_dir, selected_source, selected_frequency
                    )
            except Exception as exc:  # noqa: BLE001 — surface legacy CLC failures without losing active results
                st.session_state[KEY_SORT_ERROR] = {
                    "message": f"{type(exc).__name__}: {exc}",
                    "signature": selection_signature,
                    "candidate_session_id": candidate_session_id,
                }
            else:
                _commit_and_continue(sort_outcome, None, candidate_session_id)

pending_error = st.session_state.get(KEY_SORT_ERROR)
if (
    pending_error and selection_signature is not None
    and pending_error.get("signature") == selection_signature
    and pending_error.get("candidate_session_id")
):
    with st.container(border=True):
        st.markdown(
            styles.render_badge("Block sorting failed", "error")
            + f'<div class="hs-summary-text">File_check could not sort the selected files into observation blocks: '
            f'{html.escape(pending_error["message"])}</div>'
            '<div class="hs-file-caption">The active reduction has not changed. Page 02 validates the files '
            'themselves; continue without block sorting, or change the selection and try again.</div>',
            unsafe_allow_html=True,
        )
        if st.button("Continue without block sorting →", key="continue_without_sort_btn"):
            _commit_and_continue(None, pending_error["message"], pending_error["candidate_session_id"])
