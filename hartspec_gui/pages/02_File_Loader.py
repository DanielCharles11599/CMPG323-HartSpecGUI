"""Page 02 — File Loader (FR-02 FITS load, FR-03 validation / quarantine).

Layout reference: HARTSPEC-Page_Build_Spec.md §7, page 02. Column/row widths
below are expressed as flex proportions derived from that spec's pixel
values, not literal pixels -- see utils/styles.py module docstring for why.

`utils/styles.py` on main dropped `render_table_header` / `render_table_row`
(the team is moving tables toward `st.dataframe`/`pandas.Styler`, matching
the FR-02 spec's "clean Pandas DataFrame ... st.dataframe()" requirement).
The previous revision recreated those two helpers as page-local private
functions so the tables kept working -- untouched by this revision.

This revision wires the Load panel to the real `utils/fits_ingest.py`
(FR-02) instead of the old animated simulation. Two deliberate design
choices, flagged rather than silently picked:

1. No animated progress bar anymore. `load_file`/`load_file2` don't expose
   a progress callback -- there's no real "64% loaded" signal to animate
   against, and faking one against a real (now near-instant) call would be
   actively misleading, not just a placeholder. The load runs inside
   `st.spinner`, and the bar is drawn at 0% or 100% only -- reflecting
   what we can actually measure.
2. The target filename is read from
   `st.session_state["file_loader_target_filename"]` (falling back to
   `LOAD_FILENAME` if unset) rather than hardcoded, so this page is ready
   to receive a real selection from page 01 (Source Browser) once that's
   wired, and so tests can point it at a fixture file via session_state
   without touching this module. The archive root itself is resolved by
   `fits_ingest.get_archive_root()`, which honors the
   `HARTSPEC_FITS_ARCHIVE_ROOT` env var for the same reason.

FR-03 corruption detection (fits.verify) and quarantine (shutil.move to
Flagged/) are still NOT wired in -- the Quarantine button below still only
touches session state. That's the next step, not this one.
"""

from __future__ import annotations

import time

import streamlit as st

from utils import fits_ingest, session_store, sidebar, styles
from utils.source_browser_logic import THIS_STAGE_KEY as SOURCE_BROWSER_STAGE_KEY

STAGE_NUMBER = 2
STAGE_KEY = "file_loader"
LOAD_FILENAME = "faulty.fits"  # fallback target until page 01 selection is wired

# --------------------------------------------------------------------------
# Sample data -- reproduces the build spec's exact sample rows (§7, page 02).
# The header-fields table previews a 30+ field dataset but only the 9
# priority fields below are specified; the search box only searches these
# until the rest of the field list is confirmed (see module docstring).
# --------------------------------------------------------------------------
VALIDATION_ROWS = [
    {"file": "spectrum_002.fits", "issue": "\u2014", "status": "ok"},
    {"file": "spectrum_003.fits", "issue": "Header checksum mismatch", "status": "error"},
    {"file": "pss_survey_015.txt", "issue": "\u2014", "status": "ok"},
]

HEADER_FIELDS_COLUMNS = [
    "Vlsr", "LCP/RCP", "HPBW", "Tsys", "Date", "Object", "RA/Dec", "Focus", "Humidity",
]

HEADER_FIELDS_ROWS = [
    ["-4.2 km/s", "12.3/11.8K", "0.23\u00b0", "48.1K", "08-12", "W3(OH)", "02:27+61\u00b0", "3.1mm", "38%"],
    ["-3.8 km/s", "11.9/11.5K", "0.23\u00b0", "47.6K", "08-12", "W49N", "19:10+09\u00b0", "3.0mm", "37%"],
    ["-5.1 km/s", "13.0/12.4K", "0.23\u00b0", "48.9K", "08-11", "G34.3", "18:53+01\u00b0", "3.2mm", "41%"],
]


# --------------------------------------------------------------------------
# Page-local replacements for the two table helpers that were removed from
# utils/styles.py. Same visual output as before (flex-row divs against the
# theme's table-header-bg/table-header-text/bg-panel-alt tokens). Kept
# private (leading underscore) and page-local on purpose -- if page 04/06/
# 07/08 need the same thing, promote this back to utils/styles.py as a
# shared helper instead of copy-pasting it per page; not done here without
# confirmation since styles.py is actively being edited by the team.
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


def _render_target_file_override() -> None:
    """Manual filename override -- lets you pick which file this page loads
    directly in the browser, without going through Page 01 first.

    TEMPORARY, until Page 01 does a real scan of the FITS archive instead
    of its current hardcoded sample list (spectrum_001/002/003.fits,
    pss_survey_*.txt) -- right now Page 01 has no way to select good.fits
    or faulty.fits even if you go through it, since it doesn't know they
    exist. Remove this once Page 01's file list is real. Only shown when
    there's no Page 01 selection yet, so it gets out of the way once the
    real handoff is wired end-to-end.
    """
    pipeline_selection = st.session_state.get("pipeline_data", {}).get(SOURCE_BROWSER_STAGE_KEY, {})
    if pipeline_selection.get("selected_files"):
        return  # a real page 01 selection exists -- don't show the manual override

    with st.expander("Dev override: choose a file manually", expanded=False):
        current = st.session_state.get("file_loader_target_filename", LOAD_FILENAME)
        typed = st.text_input(
            "Filename (relative to HARTSPEC_FITS_ARCHIVE_ROOT)",
            value=current,
            key="file_loader_manual_filename_input",
        )
        if st.button("Load this file", key="file_loader_manual_load_btn"):
            st.session_state["file_loader_target_filename"] = typed
            # No explicit st.rerun() needed here -- Streamlit already
            # reruns the script automatically after any widget interaction
            # (including this button click), so the new target filename is
            # already in session_state by the time _get_target_filename()
            # runs on that natural rerun.


def _get_target_filename() -> str:
    """Which file this page loads.

    Prefers the real Page 01 handoff: st.session_state["pipeline_data"]
    [SOURCE_BROWSER_STAGE_KEY]["selected_files"][0], set by
    01_Source_Browser.py when the user clicks "Load into Pipeline". Falls
    back to st.session_state["file_loader_target_filename"] /
    LOAD_FILENAME so this page can still be run/tested standalone, without
    going through page 01 first.

    TODO: page 01 supports selecting multiple files at once
    (selected_files is a list) -- per explicit confirmation, this
    deliberately loads only the FIRST selected file for now. Full
    multi-file handling is deferred to the FR-03 validation-table redesign,
    where the build spec's own sample data already shows multiple files
    (a spectrum + a PSS file) validated together.
    """
    pipeline_selection = st.session_state.get("pipeline_data", {}).get(SOURCE_BROWSER_STAGE_KEY, {})
    selected = pipeline_selection.get("selected_files") or []
    if selected:
        return selected[0]
    return st.session_state.setdefault("file_loader_target_filename", LOAD_FILENAME)


def _run_real_load(filename: str) -> fits_ingest.IngestResult:
    """Call the real FR-02 ingestion wrapper once per filename, then cache.

    Cached in session_state so clicking Quarantine (which triggers a
    st.rerun()) doesn't silently re-open the FITS file on every rerun --
    and so the FR-20 audit log entry below is written exactly once per
    real load, not once per rerun.
    """
    cache_key = f"file_loader_ingest_result::{filename}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    path = fits_ingest.get_archive_root() / filename
    start = time.perf_counter()
    result = fits_ingest.ingest_fits_file(path)
    elapsed = time.perf_counter() - start

    st.session_state[cache_key] = result
    st.session_state["file_loader_load_elapsed_s"] = elapsed

    if result.ok:
        session_store.log_event(
            f"{filename} loaded in {elapsed:.2f}s (convention: {result.convention})"
        )
    else:
        session_store.log_event(
            f"{filename} FAILED to load in {elapsed:.2f}s -- {result.load_errors}"
        )
    return result


def _render_load_progress() -> None:
    theme = styles.get_theme()
    filename = _get_target_filename()
    cache_key = f"file_loader_ingest_result::{filename}"

    styles.render_panel_open("")
    if cache_key in st.session_state:
        result = _run_real_load(filename)  # cache hit, no spinner needed
    else:
        with st.spinner(f"Loading {filename}\u2026"):
            result = _run_real_load(filename)
    elapsed = st.session_state.get("file_loader_load_elapsed_s", 0.0)

    if result.ok:
        st.session_state["file_loader_load_done"] = True
        convention_label = {"date": "DATE", "date-obs": "DATE-OBS"}.get(result.convention, "unknown")
        badge = styles.render_badge(convention_label, "info")
        st.markdown(
            f"""
            <div>
              <div style="font-size:14px; color:{theme['text-body']};">
                  Loaded {filename} <span style="margin-left:8px;">{badge}</span>
              </div>
              <div style="width:100%; height:10px; border-radius:5px;
                          background-color:{theme['border-subtle']}; margin:14px 0 8px;">
                <div style="width:100%; height:100%; border-radius:5px;
                            background-color:{theme['accent']};"></div>
              </div>
              <div style="font-size:11px; color:{theme['text-muted']};">
                  {elapsed:.2f}s elapsed \u00b7 100%
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        spectrum = result.spectrum or {}
        st.caption(
            f"Object: {spectrum.get('object', '?')} \u00b7 Date: {spectrum.get('date', '?')} \u00b7 "
            "No RA/Dec in header -- only telescope LONGITUD/LATITUDE (pointing, not source coords)."
        )
    else:
        st.session_state["file_loader_load_done"] = False
        st.error(
            f"Could not load {filename} -- neither the DATE nor DATE-OBS convention loader "
            "could read this file. See details below."
        )
        with st.expander("Load attempt details"):
            for attempt in result.attempts:
                st.caption(attempt)
    styles.render_panel_close()


def _quarantine_file(filename: str) -> None:
    """Mark a file quarantined in session state and log the action.

    TODO: confirm against design -- should call a real quarantine function
    (moving the file out of the read-only /data/fits/ archive into
    Flagged/) once that's built into utils/fits_ingest.py and confirmed;
    right now this only updates UI-facing session state.
    """
    st.session_state.setdefault("file_loader_quarantined", set())
    st.session_state["file_loader_quarantined"].add(filename)
    session_store.log_event(f"{filename} quarantined (header checksum mismatch)")


def _render_validation_table() -> None:
    quarantined = st.session_state.get("file_loader_quarantined", set())

    styles.render_panel_open("")
    _render_table_header([("File", "45.5%"), ("Issue", "35.1%"), ("Status", "19.4%")])

    for idx, row in enumerate(VALIDATION_ROWS):
        striped = idx % 2 == 1
        theme = styles.get_theme()
        bg = theme["bg-panel-alt"] if striped else theme["bg-panel"]

        if row["file"] in {r["file"] for r in VALIDATION_ROWS if r["status"] == "error"}:
            # The flagged row gets a real inline Quarantine button, so it's
            # laid out with st.columns (matching the header's proportions)
            # instead of the static _render_table_row helper.
            is_quarantined = row["file"] in quarantined
            status_label = "QUARANTINED" if is_quarantined else "FLAGGED"

            st.markdown(
                f'<div style="background-color:{bg}; border-bottom:1px solid '
                f'{theme["border-subtle"]}; padding:2px 0;">',
                unsafe_allow_html=True,
            )
            col_file, col_issue, col_status, col_action = st.columns([455, 300, 140, 106])
            with col_file:
                st.markdown(
                    f'<div style="padding-left:10px; font-size:10.5px; color:{theme["text-body"]}; '
                    f'line-height:28px;">{row["file"]}</div>',
                    unsafe_allow_html=True,
                )
            with col_issue:
                st.markdown(
                    f'<div style="font-size:10.5px; color:{theme["text-body"]}; '
                    f'line-height:28px;">{row["issue"]}</div>',
                    unsafe_allow_html=True,
                )
            with col_status:
                st.markdown(
                    f'<div style="line-height:28px;">{styles.render_badge(status_label, "error")}</div>',
                    unsafe_allow_html=True,
                )
            with col_action:
                if not is_quarantined:
                    if st.button("Quarantine", key=f"quarantine_{row['file']}", use_container_width=True):
                        _quarantine_file(row["file"])
                        st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            badge = styles.render_badge("OK", "ok")
            _render_table_row(
                [(row["file"], "45.5%"), (row["issue"], "35.1%"), (badge, "19.4%")],
                striped=striped,
            )

    styles.render_panel_close()


def _render_header_fields_table() -> None:
    search = st.text_input(
        "Search fields",
        placeholder="Search 30+ fields\u2026",
        key="file_loader_field_search",
        label_visibility="collapsed",
    )

    if search:
        visible_columns = [c for c in HEADER_FIELDS_COLUMNS if search.lower() in c.lower()]
    else:
        visible_columns = HEADER_FIELDS_COLUMNS

    styles.render_panel_open("")
    if not visible_columns:
        st.caption(
            "No matching fields among the 9 priority columns shown here. "
            "The full 30+ field list isn't specified yet in the build spec -- "
            "ask before adding more columns rather than inventing field names."
        )
    else:
        col_width = f"{100 / len(visible_columns):.4f}%"
        _render_table_header([(c, col_width) for c in visible_columns])
        for idx, row in enumerate(HEADER_FIELDS_ROWS):
            values = [row[HEADER_FIELDS_COLUMNS.index(c)] for c in visible_columns]
            _render_table_row([(v, col_width) for v in values], striped=(idx % 2 == 1))
    styles.render_panel_close()


def main() -> None:
    st.set_page_config(page_title="HARTSPEC \u2014 File Loader", layout="wide", initial_sidebar_state="expanded")

    session_store.init_session_state()
    sidebar.render_sidebar(current_stage=STAGE_NUMBER)
    styles.inject_base_css()

    styles.render_page_header(
        title="File Loader",
        subtitle="FR-02 FITS load & FR-03 validation / quarantine",
        current_stage=STAGE_NUMBER,
        completed_stages=session_store.completed_count(),
    )

    _render_target_file_override()
    _render_load_progress()
    _render_validation_table()

    st.markdown(f"<div style='height:{styles.SECTION_GAP}px'></div>", unsafe_allow_html=True)
    _render_header_fields_table()

    if st.session_state.get("file_loader_load_done"):
        session_store.mark_stage_complete(STAGE_KEY)


if __name__ == "__main__":
    main()