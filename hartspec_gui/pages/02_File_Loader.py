"""Page 02 — File Loader (FR-02 FITS load, FR-03 validation / quarantine).

Layout reference: HARTSPEC-Page_Build_Spec.md §7, page 02. Column/row widths
below are expressed as flex proportions derived from that spec's pixel
values, not literal pixels -- see utils/styles.py module docstring for why.

`utils/styles.py` on main dropped `render_table_header` / `render_table_row`
(the team is moving tables toward `st.dataframe`/`pandas.Styler`, matching
the FR-02 spec's "clean Pandas DataFrame ... st.dataframe()" requirement).
An earlier revision recreated those two helpers as page-local private
functions so the tables kept working -- untouched by this revision.

--------------------------------------------------------------------------
FR-03 MULTI-FILE REVISION (this revision)
--------------------------------------------------------------------------
Per the FR-03 handoff's CORE DESIGN CONSTRAINT: page 01 lets the user
select MULTIPLE files, and page 02 must load + validate ALL of them, not
just the first. This revision replaces the earlier single-file
`_get_target_filename()` with `_get_target_filenames()` (plural), and the
static `VALIDATION_ROWS` sample data with real per-file
ingest + verify results, looped over every selected file.

Three design questions from the handoff were explicitly answered before
this was built (not guessed):

1. Load/validate ordering -> **load all files first, then validate all**
   (not interleaved). `_render_load_progress()` runs the full ingest loop;
   `_render_validation_table()` then runs verification per file afterward.
2. Multi-file progress UI -> **"Loading file X of N" text + a single
   aggregate bar** (not per-file spinners, not a bare aggregate-only bar).
3. Header-fields table -> **confirmed it will be one row per file** once
   built -- but that build is explicitly deferred to a later step in the
   handoff's own sequencing (step 6, after quarantine is wired in step 5).
   `_render_header_fields_table()` below is UNCHANGED / still static
   sample data in this revision -- don't mistake that for an oversight.

FR-03 corruption detection now runs for real (`fits_ingest.verify_fits_file`,
built in the prior step and confirmed against real good.fits/faulty.fits).

FR-03 handoff step 4 (this revision): quarantine now requires explicit
confirmation before it takes effect -- clicking a row's Quarantine button
stages ONE pending file (`st.session_state["file_loader_pending_quarantine"]`)
rather than quarantining immediately, and an inline confirm/cancel banner
above the table is what actually calls `_quarantine_file()`. This project's
pinned `streamlit==1.32.0` predates `st.dialog` (added 1.37+), so this is a
plain inline banner, not a real modal -- flagged rather than silently
worked around. Quarantine is STILL NOT wired to a real `shutil.move()` --
confirming still only touches session state + the audit log, same as the
old immediate-quarantine button did. That's step 5, not this one.
--------------------------------------------------------------------------

Two design choices carried over from the original single-file revision,
still true here:

1. No animated progress bar. `load_file`/`load_file2` don't expose a
   progress callback -- there's no real "64% loaded" signal to animate
   against. The per-file loop below only ever reflects what's actually
   measured: which file (of N) is currently being loaded, and the real
   elapsed time once the loop finishes.
2. The target filenames are read from Page 01's handoff
   (`pipeline_data["01_source_browser"]["selected_files"]`) when present,
   falling back to `st.session_state["file_loader_target_filenames"]` (a
   list) / `[LOAD_FILENAME]` so this page can still be run/tested
   standalone, and so tests can point it at fixture files via
   session_state without touching this module.
"""

from __future__ import annotations

import time

import streamlit as st

from utils import fits_ingest, session_store, sidebar, styles
from utils.source_browser_logic import THIS_STAGE_KEY as SOURCE_BROWSER_STAGE_KEY

STAGE_NUMBER = 2
STAGE_KEY = "file_loader"
LOAD_FILENAME = "good.fits"  # fallback target until page 01 selection is wired

# --------------------------------------------------------------------------
# Sample data -- header-fields table only. Reproduces the build spec's
# exact sample rows (§7, page 02). Still static/single-purpose in this
# revision -- see module docstring, this is deliberately deferred to a
# later step, not an oversight. The validation table below no longer uses
# static sample data; see _build_validation_rows().
# --------------------------------------------------------------------------
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
    """Manual filename override -- lets you pick which file(s) this page
    loads directly in the browser, without going through Page 01 first.

    Now a multi-line text area (one filename per line) instead of a
    single text input, matching the FR-03 multi-file requirement. Stores
    a list in `st.session_state["file_loader_target_filenames"]`.

    TEMPORARY, until Page 01 does a real scan of the FITS archive instead
    of its current hardcoded sample list -- right now Page 01 has no way
    to select good.fits/faulty.fits even if you go through it, since it
    doesn't know they exist. Remove this once Page 01's file list is real
    and always populates `selected_files`. Only shown when there's no
    Page 01 selection yet, so it gets out of the way once the real
    handoff is wired end-to-end.
    """
    pipeline_selection = st.session_state.get("pipeline_data", {}).get(SOURCE_BROWSER_STAGE_KEY, {})
    if pipeline_selection.get("selected_files"):
        return  # a real page 01 selection exists -- don't show the manual override

    with st.expander("Dev override: choose files manually", expanded=False):
        current = st.session_state.get("file_loader_target_filenames", [LOAD_FILENAME])
        typed = st.text_area(
            "Filenames, one per line (relative to FITS_ARCHIVE_PATH)",
            value="\n".join(current),
            key="file_loader_manual_filenames_input",
            height=100,
        )
        if st.button("Load these files", key="file_loader_manual_load_btn"):
            filenames = [line.strip() for line in typed.splitlines() if line.strip()]
            st.session_state["file_loader_target_filenames"] = filenames or [LOAD_FILENAME]
            # No explicit st.rerun() needed -- Streamlit already reruns the
            # script automatically after this button click, so the new
            # target filenames are already in session_state by the time
            # _get_target_filenames() runs on that natural rerun.


def _get_target_filenames() -> list[str]:
    """Which files this page loads and validates.

    Prefers the real Page 01 handoff: st.session_state["pipeline_data"]
    [SOURCE_BROWSER_STAGE_KEY]["selected_files"] -- ALL selected files,
    set by 01_Source_Browser.py when the user clicks "Load into Pipeline".
    Falls back to st.session_state["file_loader_target_filenames"] (a
    list) / [LOAD_FILENAME] so this page can still be run/tested
    standalone, without going through page 01 first.

    Supersedes the earlier single-file `_get_target_filename()` (which
    deliberately only read `selected_files[0]`) -- per the FR-03 handoff's
    CORE DESIGN CONSTRAINT, this was always meant to be a loop over every
    selected file, not a later nice-to-have.
    """
    pipeline_selection = st.session_state.get("pipeline_data", {}).get(SOURCE_BROWSER_STAGE_KEY, {})
    selected = pipeline_selection.get("selected_files") or []
    if selected:
        return list(selected)
    return st.session_state.setdefault("file_loader_target_filenames", [LOAD_FILENAME])


def _run_real_load(filename: str) -> fits_ingest.IngestResult:
    """Call the real FR-02 ingestion wrapper once per filename, then cache.

    Cached in session_state so reruns (e.g. clicking Quarantine, which
    triggers st.rerun()) don't silently re-open the FITS file every time
    -- and so the FR-20 audit log entry below is written exactly once per
    real load, not once per rerun. Already per-file and loop-safe as-is
    (per the FR-03 handoff note) -- unchanged from the single-file
    revision, just now called once per filename instead of once total.
    """
    cache_key = f"file_loader_ingest_result::{filename}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    path = fits_ingest.get_archive_root() / filename
    start = time.perf_counter()
    result = fits_ingest.ingest_fits_file(path)
    elapsed = time.perf_counter() - start

    st.session_state[cache_key] = result
    st.session_state[f"file_loader_load_elapsed_s::{filename}"] = elapsed

    if result.ok:
        session_store.log_event(
            f"{filename} loaded in {elapsed:.2f}s (convention: {result.convention})"
        )
    else:
        session_store.log_event(
            f"{filename} FAILED to load in {elapsed:.2f}s -- {result.load_errors}"
        )
    return result


def _run_real_verify(filename: str) -> fits_ingest.VerificationResult:
    """Call the real FR-03 structural-verification wrapper once per
    filename, then cache -- same pattern as `_run_real_load` above, kept
    as a separate cache key since ingest and verify are independent
    checks (see fits_ingest.verify_fits_file's docstring).
    """
    cache_key = f"file_loader_verify_result::{filename}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    path = fits_ingest.get_archive_root() / filename
    result = fits_ingest.verify_fits_file(path)
    st.session_state[cache_key] = result

    if result.ok:
        session_store.log_event(f"{filename} passed structural verification (FR-03)")
    else:
        session_store.log_event(
            f"{filename} FAILED structural verification (FR-03) -- {result.issues}"
        )
    return result


def _render_load_progress() -> None:
    """Load every target file, showing 'Loading file X of N' + one
    aggregate progress bar -- per the confirmed answer to the FR-03
    multi-file UI question. Ordering is also confirmed: load ALL files
    first here; validation (including FR-03 verify) happens afterward in
    `_render_validation_table()`, not interleaved into this loop.
    """
    theme = styles.get_theme()
    filenames = _get_target_filenames()
    quarantined = st.session_state.get("file_loader_quarantined", set())
    # Quarantined files no longer exist at their original path (the whole
    # point of moving them to Flagged/) -- reloading them here would just
    # produce a confusing "file not found" failure that looks like a new
    # bug rather than the intended result of a deliberate user action.
    # They're excluded from the active load loop and its counts entirely;
    # the validation table below still shows them, with a QUARANTINED
    # badge and no reload attempt (see _build_validation_rows).
    active_filenames = [f for f in filenames if f not in quarantined]
    n = len(active_filenames)

    styles.render_panel_open("")

    label_slot = st.empty()
    bar_slot = st.empty()
    caption_slot = st.empty()

    def _draw(label: str, frac: float, caption: str) -> None:
        frac = max(0.0, min(1.0, frac))
        fill_width = round(1140 * frac)
        label_slot.markdown(
            f'<div style="font-size:14px; color:{theme["text-body"]};">{label}</div>',
            unsafe_allow_html=True,
        )
        bar_slot.markdown(
            f"""
            <div style="width:100%; height:10px; border-radius:5px;
                        background-color:{theme['border-subtle']}; margin:14px 0 8px;">
              <div style="width:{fill_width}px; height:100%; border-radius:5px;
                          background-color:{theme['accent']};"></div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        caption_slot.markdown(
            f'<div style="font-size:11px; color:{theme["text-muted"]};">{caption}</div>',
            unsafe_allow_html=True,
        )

    if n == 0:
        _draw("No active files to load", 1.0, "All selected files have been quarantined.")
        styles.render_panel_close()
        st.session_state["file_loader_load_done"] = False
        st.session_state["loaded_spectra"] = []
        st.session_state.pop("loaded_spectrum", None)
        return

    results: dict[str, fits_ingest.IngestResult] = {}
    start_all = time.perf_counter()
    for idx, filename in enumerate(active_filenames, start=1):
        _draw(f"Loading file {idx} of {n}: {filename}", (idx - 1) / n, "")
        results[filename] = _run_real_load(filename)

    loaded_spectra = [
        result.spectrum
        for result in results.values()
        if result.ok and result.spectrum is not None
    ]
    st.session_state["loaded_spectra"] = loaded_spectra
    if loaded_spectra:
        st.session_state["loaded_spectrum"] = loaded_spectra[0]
    else:
        st.session_state.pop("loaded_spectrum", None)

    elapsed_total = time.perf_counter() - start_all

    ok_count = sum(1 for r in results.values() if r.ok)
    plural = "s" if n != 1 else ""
    _draw(
        f"Loaded {ok_count} of {n} file{plural}",
        1.0,
        f"{elapsed_total:.2f}s elapsed \u00b7 {n} file{plural} \u00b7 100%",
    )

    with st.expander("Load details", expanded=False):
        for filename, result in results.items():
            if result.ok:
                convention_label = {"date": "DATE", "date-obs": "DATE-OBS"}.get(
                    result.convention, "unknown"
                )
                badge = styles.render_badge(convention_label, "info")
                spectrum = result.spectrum or {}
                st.markdown(
                    f'{filename} {badge} \u2014 Object: {spectrum.get("object", "?")} '
                    f'\u00b7 Date: {spectrum.get("date", "?")}',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(f"**{filename}** \u2014 failed to load:")
                for attempt in result.attempts:
                    st.caption(attempt)

    if ok_count < n:
        failed = [f for f, r in results.items() if not r.ok]
        st.error(
            f"Could not load {n - ok_count} of {n} file(s) -- neither the DATE nor "
            f"DATE-OBS convention loader could read: {', '.join(failed)}. "
            "See the validation table below."
        )

    styles.render_panel_close()
    st.session_state["file_loader_load_done"] = ok_count > 0


def _request_quarantine(filename: str) -> None:
    """Clicking a row's Quarantine button no longer quarantines
    immediately -- it stages ONE file for confirmation (FR-03 handoff
    step 4). Re-targets the pending confirmation if a different row's
    button is clicked while one is already pending, rather than stacking
    multiple pending requests -- matches the handoff's explicit "scoped to
    quarantining one flagged file at a time even if several are flagged".
    """
    st.session_state["file_loader_pending_quarantine"] = filename


def _quarantine_file(filename: str) -> None:
    """Mark a file quarantined in session state and log the action.

    Only ever called after explicit confirmation now (see
    `_render_validation_table`'s confirm/cancel banner) -- this function
    itself still doesn't know or care about that; it just performs the
    actual quarantine once called, same as before.

    TODO: confirm against design -- should call a real quarantine function
    (moving the file out of the read-only /data/fits/ archive into
    Flagged/) once that's built into utils/fits_ingest.py and confirmed;
    right now this only updates UI-facing session state. That's the next
    step after this one, per the FR-03 handoff's step ordering (step 5).
    """
    st.session_state.setdefault("file_loader_quarantined", set())
    st.session_state["file_loader_quarantined"].add(filename)
    session_store.log_event(f"{filename} quarantined")


def _build_validation_rows(filenames: list[str]) -> list[dict]:
    """Real per-file validation rows, replacing the old static
    VALIDATION_ROWS sample data (FR-03 handoff step 3).

    Combines two independent checks per file, in priority order:
    1. Is the file already quarantined? If so, show it as such WITHOUT
       calling `_run_real_load`/`_run_real_verify` -- per
       `_render_load_progress`'s own comment, a quarantined file is
       deliberately excluded from the active load loop (it no longer
       exists at its original path once step 5 wires a real
       `shutil.move()`), so attempting to load/verify it here would be
       either wasted work (pre-move) or a spurious "file not found"
       failure that looks like a new bug (post-move). This branch is
       what actually keeps that promise -- it wasn't honored before.
    2. Did FR-02 ingestion succeed at all? (wrong/unrecognized convention,
       or missing science keys the CLC loaders require)
    3. If ingestion succeeded, does the file pass FR-03 structural
       verification? (fits.verify / checksum / truncation -- see
       fits_ingest.verify_fits_file's docstring for exactly what this
       does and doesn't catch)

    Assumes `_run_real_load` has already been called for every
    NOT-YET-quarantined filename (by `_render_load_progress`, which runs
    first) -- reads from that cache rather than re-loading, per the
    confirmed "load all, then validate all" ordering.
    """
    quarantined = st.session_state.get("file_loader_quarantined", set())
    rows = []
    for filename in filenames:
        if filename in quarantined:
            rows.append({"file": filename, "issue": "Quarantined by user action", "status": "error"})
            continue

        ingest_result = _run_real_load(filename)  # cache hit by this point

        if not ingest_result.ok:
            detail = "; ".join(f"{k}: {v}" for k, v in ingest_result.load_errors.items())
            rows.append({"file": filename, "issue": detail or "Failed to load", "status": "error"})
            continue

        verify_result = _run_real_verify(filename)
        if not verify_result.ok:
            rows.append({"file": filename, "issue": "; ".join(verify_result.issues), "status": "error"})
        else:
            rows.append({"file": filename, "issue": "\u2014", "status": "ok"})
    return rows


def _render_validation_table() -> None:
    filenames = _get_target_filenames()
    rows = _build_validation_rows(filenames)
    quarantined = st.session_state.get("file_loader_quarantined", set())
    pending = st.session_state.get("file_loader_pending_quarantine")

    styles.render_panel_open("")
    _render_table_header([("File", "45.5%"), ("Issue", "35.1%"), ("Status", "19.4%")])

    for idx, row in enumerate(rows):
        striped = idx % 2 == 1
        theme = styles.get_theme()
        bg = theme["bg-panel-alt"] if striped else theme["bg-panel"]

        if row["status"] == "error":
            # Flagged rows get a real inline Quarantine button, so they're
            # laid out with st.columns (matching the header's proportions)
            # instead of the static _render_table_row helper. Now scoped
            # per-row across however many files are actually flagged, not
            # hardcoded to a single known-bad sample row.
            is_quarantined = row["file"] in quarantined
            is_pending = row["file"] == pending
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
                    if is_pending:
                        # FR-03 handoff step 4: confirmation before
                        # quarantine, inline where the Quarantine button
                        # was rather than a page-top banner -- keeps the
                        # confirmation visually attached to the specific
                        # row it applies to, especially once several rows
                        # can be flagged at once. "Continue" / "Cancel"
                        # per explicit naming request (not "Confirm").
                        if st.button(
                            "Continue", key=f"confirm_quarantine_{row['file']}",
                            type="primary", use_container_width=True,
                        ):
                            _quarantine_file(row["file"])
                            st.session_state["file_loader_pending_quarantine"] = None
                            st.rerun()
                        if st.button(
                            "Cancel", key=f"cancel_quarantine_{row['file']}",
                            use_container_width=True,
                        ):
                            st.session_state["file_loader_pending_quarantine"] = None
                            st.rerun()
                    else:
                        if st.button("Quarantine", key=f"quarantine_{row['file']}", use_container_width=True):
                            _request_quarantine(row["file"])
                            st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

            if is_pending:
                # DEV NOTE, temporary -- streamlit==1.32.0 (this project's
                # pin) predates st.dialog (1.37+), so there's no real modal
                # to put this in; and step 5 (real shutil.move()) isn't
                # wired yet, so this line exists specifically to keep that
                # visible to other devs reading the running app, not just
                # the code -- remove once step 5 lands and this button
                # actually moves the file.
                st.markdown(
                    f'<div style="background-color:{bg}; padding:4px 10px 10px 20px; '
                    f'font-size:9.5px; color:{theme["text-muted"]}; border-bottom:1px solid '
                    f'{theme["border-subtle"]};">Quarantine {row["file"]}? This currently only '
                    f"updates session state and the audit log \u2014 it does NOT yet move the "
                    f"file out of the archive (that's step 5, not built yet).</div>",
                    unsafe_allow_html=True,
                )
        else:
            badge = styles.render_badge("OK", "ok")
            _render_table_row(
                [(row["file"], "45.5%"), (row["issue"], "35.1%"), (badge, "19.4%")],
                striped=striped,
            )

    styles.render_panel_close()


def _render_header_fields_table() -> None:
    """UNCHANGED in this revision -- still static single-set sample data.

    The confirmed answer to the open design question ("one row per file")
    applies here, but building that is explicitly FR-03 handoff step 6
    (after quarantine's real shutil.move() wiring in steps 4-5) -- not
    this step. Don't mistake this function's static content for an
    oversight; it's deliberately deferred.
    """
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

    # Streamlit's own st.expander header ("Dev override: choose files
    # manually" / "Load details") and widget labels (e.g. the "Dev
    # override" text area's own label) are rendered as native chrome, not
    # through unsafe_allow_html markdown -- there's no HTML string here we
    # can wrap in a themed <div>, unlike the custom "Load details" content
    # rows below. That native text falls back to Streamlit's own base theme
    # from .streamlit/config.toml, which is static per server instance and
    # doesn't react to st.session_state["theme"] (see the Style Guide's
    # §5 note). inject_base_css() apparently doesn't already override this
    # -- unlike .stButton, which does work correctly (see
    # 03_Bandpass_Correction.py's own comment on that) -- so it's forced
    # here instead. !important is needed because Streamlit's own expander
    # CSS carries its own specificity that a plain `color:` rule isn't
    # reliably guaranteed to beat.
    _theme = styles.get_theme()
    st.markdown(
        f"""
        <style>
        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] summary p,
        [data-testid="stExpander"] summary span,
        .streamlit-expanderHeader,
        .streamlit-expanderHeader p {{
            color: {_theme['text-body']} !important;
        }}
        [data-testid="stWidgetLabel"] p,
        [data-testid="stTextArea"] textarea,
        [data-testid="stTextInput"] input {{
            color: {_theme['text-body']} !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

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