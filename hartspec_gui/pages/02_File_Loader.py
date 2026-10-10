# 02_File_Loader.py — FR-02/03: loading, validated handoff and confirmed quarantine.
"""Page 02 — File Loader (FR-02 FITS load, FR-03 validation / quarantine).

Step 3: a loaded spectrum is only eligible after structural verification also
passes. The progress badges, processing handoff and Page 3 share that rule.
Changing the eligible input set invalidates dependent results and isolates
old Dash state. Quarantine remains an explicitly confirmed filesystem move.

Layout reference: HARTSPEC-Page_Build_Spec.md §7, page 02. Column/row widths
below are expressed as flex proportions derived from that spec's pixel
values, not literal pixels -- see utils/styles.py module docstring for why.

`utils/styles.py` on main dropped `render_table_header` / `render_table_row`
(the team is moving tables toward `st.dataframe`/`pandas.Styler`, matching
the FR-02 spec's "clean Pandas DataFrame ... st.dataframe()" requirement).
An earlier revision recreated those two helpers as page-local private
functions so the tables kept working -- untouched by this revision.

--------------------------------------------------------------------------
LOAD-PROGRESS UI PATTERN CHANGE (this revision)
--------------------------------------------------------------------------
Real UX problem reported: with (say) 30 files selected and 10 of them
FLAGGED (not yet quarantined -- see FR-03's confirm step below), the old
final state read "Loaded 20 of 30 files". That reads as an INCOMPLETE
scan -- like 10 files are still pending -- when the true state is that
all 30 were fully scanned and accounted for; 10 of them just failed
validation. "Loaded X of Y" conflates "how many files exist" with "how
many passed", and shouldn't.

Fixed with a two-part display, per the agreed UI pattern:
1. The progress bar/label always reaches 100% once scanning finishes --
   "N of N files processed" -- confirming every candidate file was
   scanned and accounted for, not that every file succeeded.
2. An explicit status breakdown renders directly below it:
   "{ok_count} Valid (Loaded)" as an OK/green badge,
   "{flagged_count} Flagged" as an error/red badge (`styles.render_badge`,
   same `#FEE2E2`/`#991B1B` light-mode pair as the validation table below
   it -- one badge vocabulary, not a second ad-hoc color).
   Deliberately labeled "Flagged", not "Flagged (Quarantined)": at this
   point in the flow nothing has actually been moved to Flagged/ yet --
   that only happens after the explicit per-row Quarantine confirm in
   `_render_validation_table()` below -- so calling it "Quarantined" here
   would misstate the file's real status ahead of that action.

See `_render_status_breakdown()` (new) and the tail of
`_render_load_progress()` (changed) below.
--------------------------------------------------------------------------

--------------------------------------------------------------------------
LOAD-PROGRESS UI CLEANUP (earlier revision)
--------------------------------------------------------------------------
Two things removed from `_render_load_progress()` after real browser
feedback:

1. The "Load details" expander -- redundant once the validation table
   below already shows, per file, an OK/FLAGGED badge plus (for FLAGGED
   rows) the specific issue in its own "Issue" column
   (`_build_validation_rows()`). The expander was duplicating that same
   information in a second place with a different presentation, adding UI
   clutter without adding new information for the person using the page.
2. The aggregate `st.error("Could not load N of M file(s) ...")` banner --
   replaced with a server-side `logging.warning()` call instead of a
   browser-facing red block. The per-file failure reason is still fully
   visible to the end user (in the validation table's Issue column); the
   full per-attempt trace (which convention was tried, in what order, and
   why each attempt failed) that used to live inside the removed "Load
   details" expander is now written to the server's own log output
   instead, which is the more appropriate audience for that level of
   diagnostic detail. No `logging.basicConfig()` call is added here on
   purpose -- Python's logging module prints WARNING-and-above to stderr
   via its own "handler of last resort" with zero configuration, and a
   page module forcing global logging config would risk clobbering
   whatever the actual deployment's logging setup does elsewhere.
--------------------------------------------------------------------------

--------------------------------------------------------------------------
FR-03 MULTI-FILE REVISION (earlier revision, unchanged by the above)
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
   (not interleaved). `_render_load_progress()` runs the full ingest loop,
   then validates every loaded file before publishing the processing handoff.
   `_render_validation_table()` displays those cached results.
2. Multi-file progress UI -> **"Loading file X of N" text + a single
   aggregate bar** (not per-file spinners, not a bare aggregate-only bar).
3. Header-fields table -> **confirmed one row per file**, now built (FR-03
   handoff step 6) -- see `_read_display_header_fields`'s docstring for
   which of the 9 columns are confirmed-real vs. best-effort/flagged
   (Tsys, Focus units) vs. genuinely unavailable (RA/Dec).

FR-03 corruption detection now runs for real (`fits_ingest.verify_fits_file`,
built in the prior step and confirmed against real good.fits/faulty.fits).

FR-03 handoff step 4: quarantine requires explicit confirmation before it
takes effect -- clicking a row's Quarantine button stages ONE pending file
(`st.session_state["file_loader_pending_quarantine"]`) rather than
quarantining immediately. Confirm/Cancel render inline in that row's own
action column (not a page-top banner -- keeps the confirmation visually
attached to the specific row, especially with several flagged rows at
once). This project's pinned `streamlit==1.32.0` predates `st.dialog`
(added 1.37+), so this is a plain inline element, not a real modal --
flagged rather than silently worked around.

FR-03 handoff step 5 (this revision): confirming now calls
`fits_ingest.move_to_quarantine()`, a REAL `shutil.move()` into
`<archive_root>/Flagged/` -- no longer session-state-only. A failed move
(missing file, permissions, Flagged/ uncreatable) surfaces as
`st.error()` via `st.session_state["file_loader_quarantine_error"]` and
leaves the row FLAGGED rather than silently marking it QUARANTINED when
nothing actually moved. This is a genuinely destructive, irreversible-
from-the-UI action now -- test coverage for it uses a dedicated
function-scoped fixture (`isolated_fits_archive`, see conftest.py) rather
than the shared session-scoped `fits_archive` fixture, specifically so a
test confirming quarantine doesn't delete fixture files out from under
every other test in the same pytest run.
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

import html
import logging
import time
from pathlib import Path
from typing import Mapping

import pandas as pd
import streamlit as st
from astropy.io import fits

from utils import fits_ingest, session_store, sidebar, styles
from utils.file_loader_logic import publish_validated_handoff, restore_saved_quarantine
from utils.source_browser_logic import THIS_STAGE_KEY as SOURCE_BROWSER_STAGE_KEY

logger = logging.getLogger(__name__)

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

# Used to stop a raw header field from silently overwriting a curated
# column of the same literal (case-sensitive) name when the two dicts are
# merged into one row below -- see the merge site's own comment for the
# real bug this caused ("HPBW" specifically, since it's the one curated
# name that happens to be case-identical to its actual FITS keyword).
_CURATED_COLUMN_NAMES = set(HEADER_FIELDS_COLUMNS)

# Fixed, scrollable body height for the validation table (TODO: confirm
# against design -- the build spec's 116px panel height was sized for the
# 3-row sample only, not a batch that can run to 30+ files). Keeps the
# panel itself a bounded size instead of pushing the header-fields table
# and "Continue" button further down the page on every large load.
VALIDATION_TABLE_HEIGHT = 260

# Every validation-table row (plain-HTML OK rows AND st.columns() flagged rows) is at least this tall, so the two
# kinds of row line up. min-height (not height) so content is never clipped.
# TODO: confirm against design -- build spec / style guide give 28px body rows, but flagged rows hold buttons.
VALIDATION_ROW_HEIGHT = 46
# Taller minimum for the one row currently asking "Quarantine this file?" (wrapped text + stacked buttons).
VALIDATION_PENDING_ROW_HEIGHT = 96
# Validation-table column widths (% of the table). File | Issue | Status. In a flagged row the Status share is split
# between the badge and the Quarantine / Continue / Cancel buttons, so badges line up with the OK rows' badges.
VALIDATION_COL_FILE, VALIDATION_COL_ISSUE, VALIDATION_COL_STATUS = 36, 34, 30
VALIDATION_FLAGGED_WEIGHTS = [36, 34, 16, 14]
# Shared inline style for a flagged-row cell: same left padding as the OK rows' cells, content centred vertically.
FLAGGED_CELL_STYLE = "display:flex; align-items:center; min-height:20px; padding-left:10px; line-height:1.2;"


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


def _render_table_rows(rows: list[tuple[list[tuple[str, str]], bool]]) -> None:
    """Render a run of consecutive plain-HTML table rows as ONE markdown element.

    One element per run (not per row) keeps hundreds of OK rows fast and removes the per-element wrapper spacing that
    Streamlit adds around each st.markdown() call. Every row has the same fixed height and every cell is a flex
    container, so content is vertically centred regardless of what the cell holds (text or a badge).
    """
    if not rows:
        return
    theme = styles.get_theme()
    html_rows = []
    for cells_html, striped in rows:
        bg = theme["bg-panel-alt"] if striped else theme["bg-panel"]
        cells = "".join(
            f'<div style="flex:0 0 {width}; padding-left:10px; font-size:10.5px; display:flex; '
            f'align-items:center; margin:0; line-height:1.2; color:{theme["text-body"]};">{content}</div>'
            for content, width in cells_html
        )
        html_rows.append(
            f'<div style="display:flex; align-items:center; height:{VALIDATION_ROW_HEIGHT}px; '
            f'box-sizing:border-box; margin:0; padding:0; background-color:{bg}; '
            f'border-bottom:1px solid {theme["border-subtle"]};">{cells}</div>'
        )
    st.markdown("".join(html_rows), unsafe_allow_html=True)


def _render_table_row(cells_html: list[tuple[str, str]], striped: bool) -> None:
    """Single-row convenience wrapper around `_render_table_rows`."""
    _render_table_rows([(cells_html, striped)])


def _render_status_breakdown(ok_count: int, flagged_count: int) -> None:
    """Explicit Valid/Flagged badge row shown directly under the now-always-
    100% load-progress bar. See this module's "LOAD-PROGRESS UI PATTERN
    CHANGE" docstring above for why this replaced the old "Loaded X of Y"
    single-number readout, and why it says "Flagged" rather than
    "Flagged (Quarantined)".

    Reuses `styles.render_badge()` -- the same OK/error badge pair the
    validation table below already renders -- rather than inventing a
    second color scheme for the same two states.
    """
    badges = [styles.render_badge(f"{ok_count} Valid (Loaded)", "ok")]
    if flagged_count:
        badges.append(styles.render_badge(f"{flagged_count} Flagged", "error"))
    st.markdown(
        f'<div style="display:flex; gap:8px; margin-top:10px;">{"".join(badges)}</div>',
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
        # Load/Reset may explicitly clear this control. Initialise only when
        # absent; a competing value= argument would conflict with restored state.
        st.session_state.setdefault("file_loader_manual_filenames_input", "\n".join(current))
        typed = st.text_area(
            "Filenames, one per line (relative to FITS_ARCHIVE_PATH)",
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


def _sync_validated_handoff(filenames: list[str]) -> None:
    """Publish only eligible spectra and record a changed-input invalidation.

    Runs after verification and immediately after a successful quarantine,
    before rerun/navigation. Existing saved bridges are isolated by a fresh
    reduction ID, not deleted; a delayed old Dash write cannot restore them.
    """
    outcome = publish_validated_handoff(st.session_state, filenames, fits_ingest.get_archive_root())
    if outcome.invalidated:
        session_store.log_event(
            "Validated input files changed — bandpass, baseline, calibration, pointing, fit and export "
            f"results invalidated (reduction {outcome.previous_session_id} → {st.session_state['session_id']})"
        )
        st.session_state["file_loader_validation_notice"] = (
            "The usable input files changed. Previous correction, calibration, pointing, fit and export "
            "results were cleared; run the following stages again. Saved sessions and old baseline files "
            "were not deleted."
        )


def _render_load_progress() -> None:
    """Load every target file, showing 'Loading file X of N' + one
    aggregate progress bar -- per the confirmed answer to the FR-03
    multi-file UI question. Ordering is also confirmed: load ALL files
    first here; structural verification runs in a second loop. Nothing
    enters the processing handoff until both checks have finished.

    Final state (this revision): the bar/label always reach 100% --
    "N of N files processed" -- once scanning finishes, with an explicit
    Valid/Flagged badge breakdown rendered underneath via
    `_render_status_breakdown()`. See the "LOAD-PROGRESS UI PATTERN
    CHANGE" note at the top of this module for why "Loaded X of Y" was
    replaced.
    """
    restore_saved_quarantine(st.session_state)
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

    with st.container(border=False):
        # A single placeholder for the whole label+bar+caption block -- see
        # this function's earlier revision note; this used to be three
        # separate st.empty() placeholders. Writing the full block as one
        # HTML string per _draw() call keeps it as one element with no
        # inter-element gap. The live "Loading file X of N" animation is
        # unchanged -- Streamlit still streams st.empty() updates to the
        # browser mid-script.
        progress_slot = st.empty()

        def _draw(label: str, frac: float, caption: str) -> None:
            frac = max(0.0, min(1.0, frac))
            fill_width = round(1140 * frac)
            progress_slot.markdown(
                f"""
                <div style="font-size:14px; color:{theme['text-body']};">{label}</div>
                <div style="width:100%; height:10px; border-radius:5px;
                            background-color:{theme['border-subtle']}; margin:14px 0 8px;">
                  <div style="width:{fill_width}px; height:100%; border-radius:5px;
                              background-color:{theme['accent']};"></div>
                </div>
                <div style="font-size:11px; color:{theme['text-muted']};">{caption}</div>
                """,
                unsafe_allow_html=True,
            )

        if n == 0:
            _draw("No active files to load", 1.0, "All selected files have been quarantined.")
            _sync_validated_handoff(filenames)
            return

        results: dict[str, fits_ingest.IngestResult] = {}
        start_all = time.perf_counter()
        for idx, filename in enumerate(active_filenames, start=1):
            _draw(f"Loading file {idx} of {n}: {filename}", (idx - 1) / n, "")
            results[filename] = _run_real_load(filename)

        # Preserve the agreed load-all/validate-all ordering. A successful
        # CLC load alone is not permission to use a structurally flagged file.
        with st.spinner("Validating FITS files…"):
            for filename, result in results.items():
                if result.ok and result.spectrum is not None:
                    _run_real_verify(filename)
        _sync_validated_handoff(filenames)

        elapsed_total = time.perf_counter() - start_all

        ok_count = len(st.session_state["loaded_spectra"])
        flagged_count = n - ok_count
        plural = "s" if n != 1 else ""
        # Always 100% here: every candidate file was scanned and accounted
        # for. "Loaded {ok_count} of {n}" (the old label) is exactly the
        # confusing "looks unfinished" reading this revision fixes -- see
        # the module-level docstring note. The split between valid and
        # flagged renders separately, right below, via
        # _render_status_breakdown().
        _draw(
            f"{n} of {n} file{plural} processed",
            1.0,
            f"{elapsed_total:.2f}s elapsed \u00b7 {n} file{plural} \u00b7 100%",
        )
        _render_status_breakdown(ok_count, flagged_count)

        # Aggregate failure reporting is server-side only -- the end user
        # still sees exactly which files failed and why in the validation
        # table's Issue column, and the full per-attempt trace is in the
        # FR-20 audit log via _run_real_load's own log_event call. Phrased
        # as "flagged" rather than "could not load" -- these files were
        # correctly identified as unreadable by FR-03's own logic doing
        # its job, not an application malfunction, and "flagged" matches
        # the badge terminology already shown in the validation table
        # right below this panel.
        if ok_count < n:
            failed_filenames = st.session_state["pipeline_data"][STAGE_KEY]["flagged_files"]
            logger.warning(
                "%d of %d file(s) flagged during load/validation: %s", n - ok_count, n, ", ".join(failed_filenames)
            )

        st.caption("Only files that pass both loading and structural validation continue to Bandpass Correction.")


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
    """Move the file to Flagged/ for real (FR-03 handoff step 5), via
    `fits_ingest.move_to_quarantine()`, then record it in session state
    and the audit log. Only ever called after explicit confirmation (see
    `_render_validation_table`'s inline Continue/Cancel).

    `move_to_quarantine` raises `QuarantineError` (never a raw
    OSError/shutil.Error) for anything that goes wrong -- missing file,
    permissions, a Flagged/ dir that can't be created, etc. Caught here
    so a failed quarantine attempt shows an error and leaves the file
    FLAGGED (not silently marked QUARANTINED when it never actually
    moved) rather than crashing the page.
    """
    try:
        dest_path = fits_ingest.move_to_quarantine(filename)
    except fits_ingest.QuarantineError as exc:
        st.session_state["file_loader_quarantine_error"] = str(exc)
        session_store.log_event(f"{filename} quarantine FAILED -- {exc}")
        return

    st.session_state.setdefault("file_loader_quarantined", set())
    st.session_state["file_loader_quarantined"].add(filename)
    st.session_state.pop("file_loader_quarantine_error", None)

    # A file quarantined AFTER already loading successfully would otherwise
    # leave a stale ok=True IngestResult cached under this filename's key --
    # _render_load_progress()/_render_header_fields_table() already exclude
    # quarantined files going forward, but downstream pages (e.g.
    # 03_Bandpass_Correction.py's _successful_loaded_entries()) read the RAW
    # Page 01 selected_files list and key off exactly this cache to decide
    # whether a file is usable. Without clearing it here, a file quarantined
    # mid-session could still flow into bandpass pairing/fitting even though
    # it's been physically moved out of the active archive. Clearing all
    # three per-file caches forces any later lookup to treat it as "not
    # loaded" -- which is now true, since it no longer exists at its
    # original path.
    st.session_state.pop(f"file_loader_ingest_result::{filename}", None)
    st.session_state.pop(f"file_loader_verify_result::{filename}", None)
    st.session_state.pop(f"file_loader_load_elapsed_s::{filename}", None)

    session_store.log_event(f"{filename} quarantined -- moved to {dest_path}")

    # Do not wait for the next page rerun: later stages may be opened directly.
    # Already-excluded flagged files leave the existing usable inputs intact.
    _sync_validated_handoff(_get_target_filenames())
    session_store.checkpoint_session("Confirmed quarantine recorded")


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

        if not isinstance(ingest_result.spectrum, Mapping) or not all(
            key in ingest_result.spectrum for key in ("Vlsr", "LCP", "RCP")
        ):
            rows.append({"file": filename, "issue": "Loader returned no usable spectrum", "status": "error"})
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

    quarantine_error = st.session_state.pop("file_loader_quarantine_error", None)
    if quarantine_error:
        # Shown once, immediately after a failed real move (e.g. the file
        # vanished from the archive between page load and confirming, or
        # Flagged/ couldn't be created/written to) -- popped rather than
        # left in session_state, so it doesn't keep reappearing on every
        # unrelated rerun after the one that actually failed.
        st.error(f"Could not quarantine: {quarantine_error}")

    # Real problem with large batches (e.g. the 230-file case that also
    # motivated the global manual-mapping redesign): with mostly-OK rows,
    # finding the handful that are FLAGGED/QUARANTINED meant scrolling
    # through everything. This checkbox hides OK rows entirely rather than
    # adding a second search box -- the validation table only has three
    # possible statuses, so a binary toggle is simpler than a text filter.
    # Flagged files that haven't been quarantined yet -- what "Quarantine
    # all" would act on. Already-quarantined rows also have status "error"
    # (see _build_validation_rows) but are excluded here since they've
    # already been moved.
    flagged_pending_files = [
        row["file"] for row in rows if row["status"] == "error" and row["file"] not in quarantined
    ]
    pending_all = st.session_state.get("file_loader_pending_quarantine_all", False)
    if pending_all and not flagged_pending_files:
        # Nothing left to quarantine (e.g. all handled individually since
        # "Quarantine all" was clicked) -- drop the stale confirmation.
        pending_all = False
        st.session_state["file_loader_pending_quarantine_all"] = False

    filter_col, quarantine_all_col, _spacer = st.columns([2, 2, 6])
    with filter_col:
        show_only_flagged = st.checkbox(
            "Show only flagged files",
            key="file_loader_show_only_flagged",
            help="Hide OK rows so flagged/quarantined files are easy to find without scrolling.",
        )
    with quarantine_all_col:
        # Only offered when there is actually something to quarantine.
        if flagged_pending_files and not pending_all:
            st.markdown('<span class="hs-compact-btn-marker"></span>', unsafe_allow_html=True)
            if st.button(
                f"Quarantine all ({len(flagged_pending_files)})",
                key="quarantine_all_btn",
                help="Move every flagged file into Flagged/ at once (asks for confirmation first).",
            ):
                st.session_state["file_loader_pending_quarantine_all"] = True
                st.session_state["file_loader_pending_quarantine"] = None
                st.rerun()

    if pending_all:
        # Same inline confirm pattern as the per-row Quarantine button (no
        # browser-native dialog) -- this is a bulk, irreversible-from-the-UI
        # move of every flagged file.
        st.caption(
            f"Quarantine all {len(flagged_pending_files)} flagged file(s)? This moves them out of the active "
            "archive into Flagged/ immediately — undoing it means manually moving the files back on disk."
        )
        confirm_col, cancel_col, _confirm_spacer = st.columns([1, 1, 6])
        with confirm_col:
            st.markdown('<span class="hs-compact-btn-marker"></span>', unsafe_allow_html=True)
            if st.button("Continue", key="confirm_quarantine_all", type="primary", use_container_width=True):
                with st.spinner(f"Quarantining {len(flagged_pending_files)} file(s)…"):
                    for target in flagged_pending_files:
                        _quarantine_file(target)
                quarantined_now = st.session_state.get("file_loader_quarantined", set())
                failed = [f for f in flagged_pending_files if f not in quarantined_now]
                if failed:
                    # Individual reasons are in the audit log; this surfaces the aggregate.
                    st.session_state["file_loader_quarantine_error"] = (
                        f"{len(failed)} of {len(flagged_pending_files)} file(s) could not be moved: "
                        + ", ".join(failed)
                    )
                st.session_state["file_loader_pending_quarantine_all"] = False
                st.rerun()
        with cancel_col:
            st.markdown('<span class="hs-compact-btn-marker"></span>', unsafe_allow_html=True)
            if st.button("Cancel", key="cancel_quarantine_all", use_container_width=True):
                st.session_state["file_loader_pending_quarantine_all"] = False
                st.rerun()

    display_rows = [row for row in rows if row["status"] == "error"] if show_only_flagged else rows
    if show_only_flagged:
        st.caption(f"Showing {len(display_rows)} of {len(rows)} file(s).")

    _render_table_header([
        ("File", f"{VALIDATION_COL_FILE}%"), ("Issue", f"{VALIDATION_COL_ISSUE}%"),
        ("Status", f"{VALIDATION_COL_STATUS}%"),
    ])

    # Fixed-height, scrollable body -- previously an unbounded st.container,
    # so a large batch (30+ files) pushed the header-fields table and the
    # "Continue" button far down the page and the whole page had to be
    # scrolled past it. Same pattern as 01_Source_Browser.py's own
    # fixed-height, internally-scrolling file list.
    with st.container(height=VALIDATION_TABLE_HEIGHT, border=False):
        # Marker so page CSS can zero the row gap for this table only (see hs-validation-table-marker).
        st.markdown('<span class="hs-validation-table-marker"></span>', unsafe_allow_html=True)
        ok_buffer: list[tuple[list[tuple[str, str]], bool]] = []
        for idx, row in enumerate(display_rows):
            striped = idx % 2 == 1
            theme = styles.get_theme()

            if row["status"] == "error":
                _render_table_rows(ok_buffer)  # flush the run of OK rows above this flagged row
                ok_buffer = []
                # Flagged rows need real Streamlit widgets (the Quarantine
                # buttons), so they can't be the static HTML row OK rows are.
                # They used to be wrapped in st.container(border=True), but
                # that renders Streamlit's own native bordered box, whose
                # background comes from Streamlit's static base theme -- in
                # dark mode it was a visibly different color from the themed
                # OK rows, so flagged files looked like separate objects.
                # Now the row is just st.columns(), and the row's
                # background / stripe / bottom border are applied to that
                # column block itself via the page-local
                # `.hs-flagged-row-{0,1}` marker CSS in main() (0 = panel
                # color, 1 = alternate stripe, same parity rule as
                # _render_table_row), using the same theme tokens as OK rows.
                is_quarantined = row["file"] in quarantined
                is_pending = row["file"] == pending
                status_label = "QUARANTINED" if is_quarantined else "FLAGGED"
                stripe_class = f"hs-flagged-row-{1 if striped else 0}"

                col_file, col_issue, col_status, col_action = st.columns(VALIDATION_FLAGGED_WEIGHTS)
                with col_file:
                    st.markdown(
                        f'<div style="{FLAGGED_CELL_STYLE} font-size:10.5px; color:{theme["text-body"]};">'
                        f'{row["file"]}</div>',
                        unsafe_allow_html=True,
                    )
                with col_issue:
                    # Same 10.5px size as the File column, single line with
                    # an ellipsis. The full text is reachable via the native
                    # hover tooltip (title attribute), one part per line:
                    # "&#10;" is an HTML newline entity inserted between
                    # ";"-separated parts, each escaped so a quote in an
                    # error message can't break the attribute.
                    issue_parts = [part.strip() for part in row["issue"].split(";") if part.strip()]
                    tooltip = "&#10;".join(html.escape(part, quote=True) for part in issue_parts)
                    if not is_pending:  # while confirming, only the confirmation message is shown
                        st.markdown(
                            f'<div style="{FLAGGED_CELL_STYLE} font-size:10.5px; color:{theme["text-body"]}; '
                            f'white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="{tooltip}">'
                            f'{row["issue"]}</div>',
                            unsafe_allow_html=True,
                        )
                    if is_pending:
                        # Confirmation copy updated for step 5: this now
                        # describes a real, irreversible-from-the-UI action
                        # (a real shutil.move(), not just session state) --
                        # the earlier "this doesn't do anything yet" dev note
                        # is gone now that it's no longer true; don't
                        # reintroduce it without also reverting the
                        # move_to_quarantine() call above. Rendered inside
                        # the Issue column so it stays within this row's
                        # striped background.
                        st.markdown(
                            f'<div style="padding-left:10px; font-size:11px; line-height:1.4; '
                            f'color:{theme["text-muted"]};">Quarantine {html.escape(row["file"])}? This moves the '
                            "file out of the active archive into Flagged/ immediately — undoing it means manually "
                            "moving the file back on disk.</div>",
                            unsafe_allow_html=True,
                        )
                with col_status:
                    # The row marker rides in the same markdown call as the
                    # badge so it adds no extra element (and no extra gap).
                    st.markdown(
                        f'<div style="{FLAGGED_CELL_STYLE}"><span class="{stripe_class}"></span>'
                        + ('<span class="hs-flagged-pending"></span>' if is_pending else "")
                        + styles.render_badge(status_label, "error")
                        + "</div>",
                        unsafe_allow_html=True,
                    )
                with col_action:
                    if not is_quarantined:
                        st.markdown('<span class="hs-compact-btn-marker"></span>', unsafe_allow_html=True)
                        if is_pending:
                            # FR-03 handoff step 4: confirmation before
                            # quarantine, inline where the Quarantine
                            # button was rather than a page-top banner --
                            # keeps the confirmation visually attached to
                            # the specific row it applies to, especially
                            # once several rows can be flagged at once.
                            # "Continue" / "Cancel" per explicit naming
                            # request (not "Confirm").
                            if st.button(
                                "Continue", key=f"confirm_quarantine_{row['file']}",
                                type="primary", use_container_width=True,
                            ):
                                with st.spinner(f"Quarantining {row['file']}…"):
                                    _quarantine_file(row["file"])
                                st.session_state["file_loader_pending_quarantine"] = None
                                st.rerun()
                            st.markdown('<span class="hs-compact-btn-marker"></span>', unsafe_allow_html=True)
                            if st.button(
                                "Cancel", key=f"cancel_quarantine_{row['file']}",
                                use_container_width=True,
                            ):
                                st.session_state["file_loader_pending_quarantine"] = None
                                st.rerun()
                        else:
                            if st.button(
                                "Quarantine", key=f"quarantine_{row['file']}", use_container_width=True
                            ):
                                _request_quarantine(row["file"])
                                st.rerun()
            else:
                badge = styles.render_badge("OK", "ok")
                ok_buffer.append((
                    [(row["file"], f"{VALIDATION_COL_FILE}%"), (row["issue"], f"{VALIDATION_COL_ISSUE}%"),
                     (badge, f"{VALIDATION_COL_STATUS}%")],
                    striped,
                ))
        _render_table_rows(ok_buffer)


def _read_display_header_fields_uncached(path) -> dict[str, str]:
    """Best-effort, direct-from-FITS-header values for the header-fields
    table's 9 priority columns (build spec §7, page 02).

    Deliberately reads the file's own HDU headers via astropy directly,
    INDEPENDENT of fits_ingest.ingest_fits_file()'s clc/load_file.py
    wrapper. Why bypass the loader: this project doesn't have
    clc/load_file.py's real source -- utils/fits_ingest.py's own
    docstring documents that loader's *behavior* (which KeyError fires
    when), not its *output* dict's actual field names. Building this
    display table on top of the loader's dict would mean building on a
    guess layered on a guess. Reading headers directly and verifying the
    mapping below against real good.fits/faulty.fits (done directly, not
    assumed) is the more defensible source for a display-only table --
    matches the same independent-header-read pattern
    utils/source_browser_logic.py already uses for its own
    OBJECT/RESTFREQ/DATE-OBS reads.

    Field mapping, CONFIRMED against real good.fits/faulty.fits headers
    (both files inspected directly, not just one):
      Vlsr      <- HDU0 SPVLSR
      LCP/RCP   <- HDU3 ("Chart") TSYS1 / TSYS2 -- varies per scan/weather
                   in both real files (e.g. 62.2/84.4K vs 157.0/107.1K),
                   matching the spec sample's paired, varying "X.X/Y.YK"
                   format
      HPBW      <- HDU1 (feed HDU, named e.g. "04.5S") HPBW
      Date      <- HDU0 DATE-OBS, falling back to DATE
      Object    <- HDU0 OBJECT
      Focus     <- HDU0 FOCUS
      Humidity  <- HDU0 HUMIDITY

    Two fields are BEST-EFFORT, NOT fully confirmed -- flagged here and
    to the team rather than silently picked:
      Tsys    <- HDU1 NOMTSYS ("nominal Tsys"). Real good.fits/faulty.fits
                 both have NOMTSYS=45.0 (IDENTICAL across both files) --
                 plausible as a fixed per-receiver-config nominal value,
                 but the build spec's own sample rows show Tsys VARYING
                 per row (47.6K/48.1K/48.9K), which a constant wouldn't
                 reproduce. TODO: confirm against design -- is "Tsys"
                 really NOMTSYS, or some other per-scan-varying value?
      Focus units <- displayed with "mm" per the spec sample's format,
                 but no TUNIT-style keyword confirms FOCUS is actually in
                 mm in the real header (it's a bare HDU0 keyword, not a
                 table column with an associated unit field). Real
                 observed values (~4.6) are plausible in mm but unverified.
      RA/Dec  <- NOT AVAILABLE. Neither loader nor any header here exposes
                 source RA/Dec, only telescope LONGITUD/LATITUDE (pointing,
                 not source coordinates) -- fits_ingest.py's own docstring
                 is explicit about this gap. Shown as "pending" rather
                 than silently substituting telescope pointing.

    Never raises -- a file whose header can't be read at all, or is
    missing a given keyword, gets "pending" for the fields it's missing
    rather than crashing the page.
    """
    fields = {col: "pending" for col in HEADER_FIELDS_COLUMNS}
    try:
        with fits.open(path) as hdul:
            h0 = hdul[0].header
            h1 = hdul[1].header if len(hdul) > 1 else {}
            h3 = hdul[3].header if len(hdul) > 3 else {}

            if "SPVLSR" in h0:
                fields["Vlsr"] = f"{h0['SPVLSR']:.1f} km/s"
            if "TSYS1" in h3 and "TSYS2" in h3:
                fields["LCP/RCP"] = f"{h3['TSYS1']:.1f}/{h3['TSYS2']:.1f}K"
            if "HPBW" in h1:
                fields["HPBW"] = f"{h1['HPBW']:.3f}\u00b0"
            if "NOMTSYS" in h1:  # best-effort -- see docstring
                fields["Tsys"] = f"{h1['NOMTSYS']:.1f}K"
            date_val = h0.get("DATE-OBS") or h0.get("DATE")
            if date_val:
                date_str = str(date_val)
                fields["Date"] = date_str[5:10] if len(date_str) >= 10 else date_str
            if "OBJECT" in h0:
                fields["Object"] = str(h0["OBJECT"])
            if "FOCUS" in h0:  # units best-effort -- see docstring
                fields["Focus"] = f"{h0['FOCUS']:.1f}mm"
            if "HUMIDITY" in h0:
                fields["Humidity"] = f"{h0['HUMIDITY']:.0f}%"
    except Exception:
        pass  # every field stays "pending" -- never crash the page over a display table
    return fields


@st.cache_data(show_spinner=False)
def _read_display_header_fields_cached(path_str: str, mtime: float) -> dict[str, str]:
    return _read_display_header_fields_uncached(path_str)


def _read_display_header_fields(path) -> dict[str, str]:
    """Cached wrapper around `_read_display_header_fields_uncached` (same path + mtime key as above)."""
    mtime = _file_mtime(path)
    if mtime is None:
        return _read_display_header_fields_uncached(path)
    return _read_display_header_fields_cached(str(path), mtime)


# --------------------------------------------------------------------------
# Auto/Manual column-mapping (FR-02, confirmed 2026-08-30). "Auto" is the
# best-effort fixed mapping above (_read_display_header_fields). "Manual"
# lets the user override which raw header keyword feeds each column, for
# receiver configs / non-standard headers Auto's fixed mapping doesn't
# handle -- confirmed scope, from the actual answer this was built against:
#   - Manual mapping only affects THIS display table, not clc's real
#     ingestion (clc/load_file.py and load_file2.py are off-limits to
#     modify, and there's nowhere else for an override to plug into).
#   - Limited to the same 9 confirmed priority columns, not the full 30+
#     field set -- that list still isn't documented anywhere, so manual
#     mapping can't be built for fields whose names aren't known yet.
#   - "LCP/RCP" gets TWO source-field pickers, not one, since it's an
#     explicitly combined column (build spec §7: "LCP and RCP are
#     combined into one ... column -- reproduce this ... exactly").
#   - RA/Dec: Auto mode still never auto-substitutes telescope pointing
#     for source coordinates (that rule is unchanged). Manual mode lets a
#     user deliberately point RA/Dec at LONGITUD/LATITUDE (or anything
#     else) if they choose to -- a conscious human choice via the picker,
#     not a silent substitution by the code, which is a different thing.
# --------------------------------------------------------------------------

# Pure FITS-standard structural bookkeeping (binary layout, not
# observation metadata) -- excluded from the Manual-mode header preview
# and field picker so that UI is actually "browse the meaningful header
# fields and pick one" rather than mostly TTYPE/TFORM/NAXIS noise.
_STRUCTURAL_HEADER_KEYS = {
    "SIMPLE", "BITPIX", "NAXIS", "EXTEND", "XTENSION", "PCOUNT", "GCOUNT",
    "TFIELDS", "EXTNAME", "COMMENT", "HISTORY", "",
}
_STRUCTURAL_KEY_PREFIXES = ("NAXIS", "TTYPE", "TFORM", "TDISP", "TUNIT")


def _is_structural_key(key: str) -> bool:
    if key in _STRUCTURAL_HEADER_KEYS:
        return True
    return any(key.startswith(prefix) and key[len(prefix):].isdigit() for prefix in _STRUCTURAL_KEY_PREFIXES)


def _flatten_header_preview_uncached(path) -> list[tuple[str, str, str]]:
    """Every non-plumbing header keyword across every HDU in a file, as
    (qualified_key, hdu_label, formatted_value) tuples.

    This IS the "header preview" Manual mode shows (per the confirmed
    FR-02 answer), and also the pool of choices its per-column
    selectboxes are populated from -- so what a user sees and what they
    can pick from are the same list, not two things that could drift
    apart. qualified_key (e.g. "HDU3:TSYS1") is the stable identifier
    stored in session_state and resolved back to a value at display time.

    Never raises -- an unreadable file returns an empty list rather than
    crashing the Manual-mapping expander.
    """
    items: list[tuple[str, str, str]] = []
    try:
        with fits.open(path) as hdul:
            for idx, hdu in enumerate(hdul):
                hdu_label = hdu.name or f"HDU{idx}"
                seen: set[str] = set()
                for key in hdu.header.keys():
                    if not key or key in seen or _is_structural_key(key):
                        continue
                    seen.add(key)
                    value = hdu.header.get(key)
                    items.append((f"HDU{idx}:{key}", hdu_label, str(value)))
    except Exception:
        pass
    return items


def _file_mtime(path) -> float | None:
    """Modification time used as part of the header-cache key (None if the file is missing/unreadable)."""
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


@st.cache_data(show_spinner=False)
def _flatten_header_cached(path_str: str, mtime: float) -> list[tuple[str, str, str]]:
    return _flatten_header_preview_uncached(path_str)


def _flatten_header_preview(path) -> list[tuple[str, str, str]]:
    """Cached wrapper around `_flatten_header_preview_uncached`.

    Every Streamlit rerun (including the one right after a quarantine
    click) used to re-open every loaded FITS file from disk several times
    just to rebuild the header-fields table. Keyed by path + modification
    time, so a changed file is re-read but an unchanged one is not.
    A missing file is never cached (a file that later reappears must not
    be served a stale empty result).
    """
    mtime = _file_mtime(path)
    if mtime is None:
        return _flatten_header_preview_uncached(path)
    return _flatten_header_cached(str(path), mtime)


def _read_all_raw_fields(path) -> dict[str, str]:
    """Every non-plumbing header keyword found in this file, as a flat
    {display_name: value} dict -- included as extra columns in the
    header-fields table, in BOTH Auto and Manual mode.

    This is what the build spec's own "Search 30+ fields..." placeholder
    text actually refers to: the 9 curated columns
    (HEADER_FIELDS_COLUMNS) were a hand-picked PREVIEW subset, not the
    full dataset -- real files inspected during this session have ~70
    meaningful fields once FITS-standard plumbing (SIMPLE/BITPIX/TTYPEn/
    etc.) is excluded, comfortably past "30+". Originally this only
    surfaced inside Manual mode's header-preview expander; moved into the
    main table directly (both modes) since hiding it there made it hard
    to find and meant Auto mode couldn't be searched against it at all.

    Disambiguates keys that repeat across multiple HDUs (e.g. TCAL1
    appears in both the Spectra and Chart HDUs, sometimes with different
    values) by appending the HDU label in brackets ONLY for those
    specific repeated keys -- an unambiguous key keeps its plain name,
    so most columns aren't cluttered with a qualifier they don't need.
    """
    items = _flatten_header_preview(path)  # (qualified_key, hdu_label, value)
    bare_key_counts: dict[str, int] = {}
    for qualified_key, _, _ in items:
        bare_key = qualified_key.split(":", 1)[1]
        bare_key_counts[bare_key] = bare_key_counts.get(bare_key, 0) + 1

    fields: dict[str, str] = {}
    for qualified_key, hdu_label, value in items:
        bare_key = qualified_key.split(":", 1)[1]
        display_name = bare_key if bare_key_counts[bare_key] == 1 else f"{bare_key} [{hdu_label}]"
        fields[display_name] = value
    return fields


def _resolve_qualified_key(path, qualified_key: str | None) -> str | None:
    """Look up one "HDU{n}:{key}" identifier's current value in a file.

    Reads from the cached header listing (`_flatten_header_preview`)
    instead of re-opening the FITS file for every single column of every
    file -- Manual mode previously did ~10 file opens per file per rerun.
    The picker options are built from that same listing, so every key a
    user can choose is resolvable here.

    Returns None (never raises) if the key is unset, absent from this
    particular file, or the file can't be read at all -- callers treat
    None as "pending", the same convention used everywhere else in this
    module for a value that couldn't be sourced.
    """
    if not qualified_key or ":" not in qualified_key:
        return None
    for candidate_key, _hdu_label, value in _flatten_header_preview(path):
        if candidate_key == qualified_key:
            return value
    return None


def _default_manual_mapping() -> dict:
    """Seed the Manual mapping UI with the same fixed choices Auto mode
    resolves, so a user only has to change what's actually wrong for
    their receiver config rather than start from a blank slate. Mirrors
    `_read_display_header_fields`'s own hardcoded choices -- if that
    function's mapping ever changes, this needs to change with it.

    No longer takes a `path` argument (this revision) -- see this
    module's "GLOBAL MANUAL MAPPING" comment above `_render_manual_
    mapping_card`. The defaults below were never actually file-specific
    to begin with (they're fixed HDU/keyword names, not read from any
    particular file), so the parameter was unused dead weight.

    RA/Dec is deliberately None here, not guessed -- Auto mode never
    picks a value for it either (see that function's docstring), and
    seeding a default here would be exactly the silent substitution the
    project has repeatedly ruled out elsewhere.
    """
    return {
        "Vlsr": "HDU0:SPVLSR",
        "LCP/RCP": ("HDU3:TSYS1", "HDU3:TSYS2"),
        "HPBW": "HDU1:HPBW",
        "Tsys": "HDU1:NOMTSYS",
        "Date": "HDU0:DATE-OBS",
        "Object": "HDU0:OBJECT",
        "RA/Dec": None,
        "Focus": "HDU0:FOCUS",
        "Humidity": "HDU0:HUMIDITY",
    }


def _read_display_header_fields_manual(path, mapping: dict) -> dict[str, str]:
    """Manual-mode counterpart to `_read_display_header_fields`.

    Uses whichever qualified header key the user explicitly assigned to
    each column, instead of the fixed best-effort mapping. Deliberately
    shows the RAW value with no unit suffix or domain-specific formatting
    (unlike Auto mode's "48.1K"/"0.23\u00b0" style) -- Auto's formatting
    assumes a KNOWN field (it always appends "K" because it knows it
    picked TSYS1 specifically), which doesn't hold for an arbitrary
    user-chosen keyword. This trades some display polish for not
    mislabeling units on a value the code doesn't actually know the
    meaning of.
    """
    fields: dict[str, str] = {}
    for column in HEADER_FIELDS_COLUMNS:
        if column == "LCP/RCP":
            lcp_key, rcp_key = mapping.get(column, (None, None))
            lcp_val = _resolve_qualified_key(path, lcp_key)
            rcp_val = _resolve_qualified_key(path, rcp_key)
            fields[column] = f"{lcp_val}/{rcp_val}" if lcp_val is not None and rcp_val is not None else "pending"
        else:
            value = _resolve_qualified_key(path, mapping.get(column))
            fields[column] = value if value is not None else "pending"
    return fields


# --------------------------------------------------------------------------
# GLOBAL MANUAL MAPPING (this revision, replaces per-file mapping)
# --------------------------------------------------------------------------
# Real reported problem with a 230+ file batch: Manual mode used to render
# one full expander with its own ~10 selectboxes PER FILE
# (`_render_manual_mapping_expander`, one call per filename in a loop) --
# roughly 2,300 widgets for a 230-file load, re-rendered on every single
# rerun. That's both the direct cause of the reported lag, and tedious in
# its own right: assigning "Vlsr comes from SPVLSR" 230 times when every
# file in a load comes from the same instrument/receiver configuration in
# practice was never actually useful, just repetitive.
#
# Fix: ONE mapping card, ONE set of ~10 selectboxes total, applied to
# EVERY loaded file at once -- not a full picker set per file. The picker
# OPTIONS (which real header keywords are available to choose from) are
# read from just the first file in the current selection; this is fine in
# practice since files from one load share the same header schema, and
# `_resolve_qualified_key()` already resolves per-file and degrades
# gracefully to "pending" if a chosen key happens to be absent from some
# other specific file's header -- it doesn't assume every file has it.
#
# Persisted as one flat dict at
# st.session_state["file_loader_manual_mapping_global"], replacing the
# old per-file dict-of-dicts at "file_loader_manual_mapping".
# --------------------------------------------------------------------------

def _render_manual_mapping_card(filenames: list[str]) -> dict:
    """Single, file-agnostic 'Manual column mapping' card, with an
    explicit Apply Mapping button (this revision).

    Wrapped in `st.form()` rather than bare selectboxes -- outside a
    form, EVERY individual selectbox change triggers its own full
    Streamlit rerun immediately, which re-runs the header-fields table's
    full per-file disk-read loop on every single field pick, not just
    once you're done choosing. Inside a form, none of the selectboxes
    trigger a rerun on their own; only clicking "Apply Mapping" (the
    form's submit button) does, and it commits every field's choice
    together in that one rerun. This also means a half-finished set of
    picks (e.g. Vlsr assigned, Object not yet touched) never gets applied
    to the table mid-edit -- the previously-applied mapping stays in
    effect until Apply is actually clicked.

    See the "GLOBAL MANUAL MAPPING" comment above for why this is one
    shared card for every loaded file, not one per file. Returns the
    currently APPLIED mapping dict -- NOT necessarily whatever is
    currently live in the form's widgets, if Apply hasn't been clicked
    since the last change.
    """
    none_option = "\u2014 none \u2014"
    reference_filename = filenames[0] if filenames else None
    preview_items: list[tuple[str, str, str]] = []
    if reference_filename:
        reference_path = fits_ingest.get_archive_root() / reference_filename
        preview_items = _flatten_header_preview(reference_path)
    options = [none_option] + [qk for qk, _, _ in preview_items]

    applied = st.session_state.setdefault("file_loader_manual_mapping_global", _default_manual_mapping())

    with st.expander("Manual column mapping (applies to every loaded file)", expanded=False):
        if not preview_items:
            st.caption("No files loaded yet \u2014 nothing to map.")
            return applied

        st.caption(
            f"Field choices are read from {reference_filename}'s header. Pick your fields "
            "below, then click Apply Mapping \u2014 the table only updates once you apply, "
            "not on every individual selection."
        )

        with st.form(key="manual_mapping_form"):
            pending: dict = {}
            for column in HEADER_FIELDS_COLUMNS:
                if column == "LCP/RCP":
                    lcp_default, rcp_default = applied.get(column) or (None, None)
                    lcp_col, rcp_col = st.columns(2)
                    with lcp_col:
                        lcp_choice = st.selectbox(
                            "LCP source field", options=options,
                            index=options.index(lcp_default) if lcp_default in options else 0,
                            key="manual_map_global_LCP",
                        )
                    with rcp_col:
                        rcp_choice = st.selectbox(
                            "RCP source field", options=options,
                            index=options.index(rcp_default) if rcp_default in options else 0,
                            key="manual_map_global_RCP",
                        )
                    pending[column] = (
                        None if lcp_choice == none_option else lcp_choice,
                        None if rcp_choice == none_option else rcp_choice,
                    )
                else:
                    default = applied.get(column)
                    choice = st.selectbox(
                        f"{column} source field", options=options,
                        index=options.index(default) if default in options else 0,
                        key=f"manual_map_global_{column}",
                    )
                    pending[column] = None if choice == none_option else choice

            # No key= here -- st.form_submit_button() on this project's
            # pinned streamlit==1.32.0 doesn't accept one (added in a
            # later Streamlit release). Not needed anyway: a form can
            # only have one submit button, already uniquely scoped by
            # the form's own key ("manual_mapping_form" above).
            submitted = st.form_submit_button("Apply Mapping", type="primary")

        if submitted:
            st.session_state["file_loader_manual_mapping_global"] = pending
            applied = pending
            session_store.checkpoint_session("Header mapping applied")

    return applied


def _render_header_fields_table() -> None:
    """Real per-file header-fields table (FR-03 handoff step 6).

    One row per active (non-quarantined) file, per the confirmed design
    answer from earlier in the FR-03 handoff -- replaces the static
    HEADER_FIELDS_ROWS sample data. Uses st.dataframe rather than the
    hand-rolled _render_table_header/_render_table_row helpers, per the
    build spec's own explicit guidance for this specific table ("clean
    Pandas DataFrame ... st.dataframe()") -- the column-name search
    filter (kept from before) doesn't need hand-rolled HTML the way the
    Quarantine button's inline row layout does on the validation table.

    Also doubles as the FR-02 "FITS extension viewer": per the confirmed
    answer, that requirement IS a searchable metadata table via
    st.dataframe() with no raw binary reaching the client -- exactly what
    this function already is. No separate component was built for it.

    REVISED after first real-world use: each row now shows the 9 curated
    columns (HEADER_FIELDS_COLUMNS -- best-effort/Auto or user-assigned/
    Manual, see below) PLUS every other real, non-plumbing header field
    found in that file (`_read_all_raw_fields`), in BOTH Auto and Manual
    mode. Originally the raw fields only showed inside a Manual-mode-only
    "header preview" expander -- moved into the main table because (a)
    that's genuinely what the build spec's "Search 30+ fields..."
    placeholder was describing all along, not just a curated 9-column
    preview, and (b) Auto mode couldn't be searched against any of that
    data before, which defeated the point of the search box existing.
    The search box now filters over the REAL full column set for
    whichever file(s) are loaded, not a fixed 9-name list -- so which
    columns are searchable can vary slightly by file (a field present in
    one file's header but not another's still shows as a column, just
    NaN for files that don't have it -- pandas handles that natively).

    See `_read_display_header_fields`'s docstring for exactly which
    curated Auto-mode fields are confirmed-real vs. best-effort/flagged
    (Tsys, Focus units) vs. genuinely unavailable (RA/Dec, shown as
    "pending"). Manual mode (`_render_manual_mapping_card` /
    `_read_display_header_fields_manual`) lets a user override any
    curated column's source field, applied to every loaded file at once
    (see the "GLOBAL MANUAL MAPPING" comment above that function for why
    this is no longer per-file); the raw columns are always a straight
    dump regardless of mode, since they ARE the source data, not a
    derived/mapped value.
    """
    quarantined = st.session_state.get("file_loader_quarantined", set())
    filenames = [f for f in _get_target_filenames() if f not in quarantined]

    mode = st.radio(
        "Column mapping mode",
        options=["Auto", "Manual"],
        key="file_loader_mapping_mode",
        horizontal=True,
    )

    search = st.text_input(
        "Search fields",
        placeholder="Search 30+ fields\u2026",
        key="file_loader_field_search",
        label_visibility="collapsed",
    )

    # The manual mapping card must render (and update session_state)
    # BEFORE the rows below read that state -- a selectbox's new value
    # from this rerun isn't in session_state until the widget itself has
    # been instantiated. One card, applied to every file below -- not one
    # per file (see "GLOBAL MANUAL MAPPING" comment above).
    global_mapping = None
    if mode == "Manual":
        global_mapping = _render_manual_mapping_card(filenames)

    with st.container(border=False):
        if not filenames:
            st.caption("No active files to show header fields for.")
        else:
            rows = []
            for filename in filenames:
                path = fits_ingest.get_archive_root() / filename
                if mode == "Manual":
                    curated_fields = _read_display_header_fields_manual(path, global_mapping)
                else:
                    curated_fields = _read_display_header_fields(path)
                raw_fields = _read_all_raw_fields(path)

                # Real bug found and fixed here: "HPBW" is the one curated
                # column whose display name is literally identical (same
                # case) to its actual raw FITS keyword -- every other
                # curated column differs in case from its raw source
                # ("Object" vs "OBJECT", "Focus" vs "FOCUS", "Humidity" vs
                # "HUMIDITY", "Date" vs "DATE-OBS"), so only HPBW ever
                # collided. Without this, row.update(raw_fields) below
                # would silently overwrite whatever curated_fields (Auto
                # OR Manual-mode-assigned) had just computed for "HPBW"
                # with the raw dump's own value, making a Manual HPBW
                # reassignment look like it had no effect even though it
                # was computed correctly one line earlier.
                raw_fields = {
                    (f"{key} (raw)" if key in _CURATED_COLUMN_NAMES else key): value
                    for key, value in raw_fields.items()
                }

                row = {"File": filename}
                row.update(curated_fields)  # curated columns first, in HEADER_FIELDS_COLUMNS order
                row.update(raw_fields)      # then every other real field found in this file
                rows.append(row)

            df = pd.DataFrame(rows).set_index("File")

            if search:
                matching_columns = [c for c in df.columns if search.lower() in c.lower()]
                if not matching_columns:
                    st.caption(f'No fields match "{search}" among this file set\'s real header fields.')
                    df = None
                else:
                    df = df[matching_columns]

            if df is not None:
                st.dataframe(df, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="HARTSPEC \u2014 File Loader", layout="wide", initial_sidebar_state="expanded")

    session_store.init_session_state()
    sidebar.render_sidebar(current_stage=STAGE_NUMBER)
    styles.inject_base_css()

    # Streamlit's own st.expander header ("Dev override: choose files
    # manually") and widget labels (e.g. the "Dev override" text area's
    # own label) are rendered as native chrome, not through unsafe_allow_html
    # markdown -- there's no HTML string here we can wrap in a themed
    # <div>, unlike the custom "Load details" content rows below. That
    # native text falls back to Streamlit's own base theme from
    # .streamlit/config.toml, which is static per server instance and
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
        /* Compact inline action buttons for the validation table (Quarantine
           / Continue / Cancel, and Quarantine all) -- these are small
           inline actions, not primary CTAs, and
           Streamlit's default button padding/height made Quarantine not
           fit comfortably in its column. Scoped to only the buttons
           immediately following a `.hs-compact-btn-marker` span (one is
           emitted right before each such button in _render_validation_table)
           using the same `:has()` sibling-selector technique
           utils/sidebar.py already uses for its own nav buttons -- proven to
           work on this pinned Streamlit version, which has no per-widget
           `st-key-` CSS class yet. Deliberately NOT a change to
           utils/styles.py's global button rules, since those also style the
           app's primary/secondary CTAs everywhere else. */
        /* Streamlit dims ("hazes") every element it considers stale while a
           rerun is in progress -- on this page a rerun after quarantining
           can take a while, and the whole page went ghostly for the
           duration. Spinners (st.spinner) now signal progress instead, so
           the dimming is switched off here. Page-local on purpose; if it
           should apply app-wide it can be promoted to utils/styles.py. */
        [data-stale="true"],
        .element-container[data-stale="true"],
        .stale-element {{
            opacity: 1 !important;
            transition: none !important;
        }}
        /* Flagged rows (st.columns blocks carrying a .hs-flagged-row-{0,1}
           marker) get the same background stripe, bottom border and left
           padding as the plain-HTML OK rows (_render_table_row), using the
           same theme tokens -- so every row in the validation table looks
           like one object. Targets the column block itself via :has(), the
           same sibling/descendant technique used for the compact buttons. */
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-row-0),
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-row-1) {{
            border-bottom: 1px solid {_theme['border-subtle']};
            padding: 2px 24px 2px 0;
            gap: 0 !important;
            min-height: {VALIDATION_ROW_HEIGHT}px;
            box-sizing: border-box;
            align-items: stretch !important;
        }}
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-row-0) {{
            background-color: {_theme['bg-panel']};
        }}
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-row-1) {{
            background-color: {_theme['bg-panel-alt']};
        }}
        /* Centre each flagged-row cell vertically. Markdown wraps inline HTML (the status badge) in a <p> with a
           bottom margin, which pushed the badge above the text and inflated the row; zero it, drop the
           column's internal gap, and centre column content. */
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-row-0) > [data-testid="column"],
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-row-1) > [data-testid="column"],
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-row-0) > [data-testid="stColumn"],
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-row-1) > [data-testid="stColumn"] {{
            display: flex;
            flex-direction: column;
            justify-content: center;
        }}
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-row-0) [data-testid="stVerticalBlock"],
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-row-1) [data-testid="stVerticalBlock"] {{
            gap: 0.25rem !important;
        }}
        [data-testid="stVerticalBlock"]:has(> .element-container .hs-validation-table-marker)
            [data-testid="stMarkdownContainer"] p {{
            margin: 0 !important;
        }}
        /* Row being confirmed: the confirmation text wraps and the Continue/Cancel buttons stack, so it needs more
           room than a normal row (it was squished at the normal height). */
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-pending) {{
            min-height: {VALIDATION_PENDING_ROW_HEIGHT}px;
            padding-top: 8px;
            padding-bottom: 8px;
        }}
        /* Remove every spacing source around the validation table's elements (wrapper margins/padding). */
        [data-testid="stVerticalBlock"]:has(> .element-container .hs-validation-table-marker)
            > .element-container {{
            padding: 0 !important;
            min-height: 0 !important;
        }}
        [data-testid="stVerticalBlock"]:has(> .element-container .hs-validation-table-marker)
            [data-testid="stMarkdownContainer"] {{
            margin: 0 !important;
            padding: 0 !important;
        }}
        /* Validation table: Streamlit puts a 1rem gap between stacked elements. OK rows are plain HTML and
           looked contiguous, but a flagged/quarantined row is an st.columns() block, so the gap showed up
           as a hole between the two kinds of row. Zero the gap for this table's own container only. */
        [data-testid="stVerticalBlock"]:has(> .element-container .hs-validation-table-marker) {{
            gap: 0 !important;
        }}
        [data-testid="stVerticalBlock"]:has(> .element-container .hs-validation-table-marker)
            > .element-container {{
            margin: 0 !important;
        }}
        .element-container:has(.hs-validation-table-marker) {{
            display: none;
        }}
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-row-0),
        [data-testid="stHorizontalBlock"]:has(.hs-flagged-row-1) {{
            margin: 0 !important;
        }}
        .element-container:has(.hs-compact-btn-marker) + .element-container button {{
            padding: 2px 10px !important;
            font-size: 10px !important;
            min-height: 24px !important;
            height: 24px !important;
            line-height: 1 !important;
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
    notice = st.session_state.pop("file_loader_validation_notice", None)
    if notice:
        st.warning(notice)
    _render_validation_table()

    st.markdown(f"<div style='height:{styles.SECTION_GAP}px'></div>", unsafe_allow_html=True)
    with st.spinner("Reading FITS headers…"):
        _render_header_fields_table()

    if st.session_state.get("file_loader_load_done"):
        session_store.mark_stage_complete(STAGE_KEY)
    session_store.checkpoint_session("File loading and validation recorded")

    if st.session_state.get("file_loader_load_done"):
        # "Continue to X ->" pattern, matching Page 03's own button
        # (see 03_Bandpass_Correction.py's "Continue to Baseline Block
        # Editor ->"). Only shown once loading actually succeeded for at
        # least one file -- same gate mark_stage_complete() above already
        # uses, so this button can never appear ahead of the stage it's
        # meant to follow. Styled as the primary CTA per the build spec's
        # own description of Page 01's equivalent button ("Load into
        # Pipeline ->" primary button) -- Page 03's current button doesn't
        # set type="primary" and renders as secondary instead, which looks
        # like a separate small inconsistency worth fixing there too, not
        # copied here on purpose.
        st.markdown(f"<div style='height:{styles.SECTION_GAP}px'></div>", unsafe_allow_html=True)
        if st.button("Continue to Bandpass Correction →", type="primary", key="continue_to_bandpass"):
            st.switch_page("pages/03_Bandpass_Correction.py")


if __name__ == "__main__":
    main()
    