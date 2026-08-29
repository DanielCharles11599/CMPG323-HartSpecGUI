"""Tests for pages/02_File_Loader.py (FR-02 load, FR-03 validation/quarantine).

Uses Streamlit's AppTest harness against real synthetic FITS files (see
tests/fixtures/make_fixtures.py + tests/conftest.py) rather than mocking
utils.fits_ingest -- this exercises the real clc/load_file.py and
clc/load_file2.py code paths, which is the whole point of this page.

Run: pytest tests/test_02_File_Loader.py -v

NOTE: first AppTest.run() in a session imports specutils (via
clc/load_file2.py), which is genuinely slow (~1-2s cold). The default
AppTest timeout (3s) can be too tight on a slower machine/CI runner --
every at.run() call below passes timeout=30 for that reason, not because
anything is actually hanging.

--------------------------------------------------------------------------
FR-03 MULTI-FILE REVISION (this revision)
--------------------------------------------------------------------------
Rewritten to match pages/02_File_Loader.py's move from a single target
filename to a list (`_get_target_filenames()` / session_state key
"file_loader_target_filenames", plural). Key differences from the prior
version of this test file:

- `_app_for()` now sets the plural, list-valued session_state key.
- The validation-table / quarantine tests (`test_validation_table_shows_*`,
  `test_quarantine_button_updates_status`) previously worked against
  static VALIDATION_ROWS sample data that didn't actually depend on which
  file was loaded -- a FLAGGED row showed up regardless. Now that the
  table is built from real per-file ingest+verify results, those tests
  have to actually load a file that's really bad (unrecognized.fits) to
  have anything to flag. Rewritten below to load two files together
  (one good, one bad) and assert on the real outcome.
- New tests added specifically for multi-file behavior: loading several
  files at once, partial failure across a set, and the Page 01 handoff
  carrying more than one selected file through to real per-file rows.
--------------------------------------------------------------------------
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

PAGE_PATH = str(Path(__file__).resolve().parents[1] / "hartspec_gui" / "pages" / "02_File_Loader.py")


def _app_for(*filenames: str) -> AppTest:
    """Build an AppTest instance targeting one or more fixture filenames.

    Requires the `fits_archive` (or `real_fits_archive`) fixture to have
    run first (sets FITS_ARCHIVE_PATH) -- callers must request it via a
    test argument even if they don't use the returned path directly.
    """
    at = AppTest.from_file(PAGE_PATH)
    at.session_state["file_loader_target_filenames"] = list(filenames)
    return at


def _markdown_html(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown if m.value)


# --------------------------------------------------------------------------
# Real files (good.fits / faulty.fits) -- opt-in via real_fits_archive.
# These don't assert a specific outcome for faulty.fits, since structural
# verification (fits.verify / checksum) has already been confirmed to find
# nothing wrong with it -- see tests/test_fits_verify.py's diagnostic tests
# and the FR-03 session notes. faulty.fits is expected to load and verify
# CLEAN at this layer; whatever makes it "faulty" is out of scope for what
# this page currently checks.
# --------------------------------------------------------------------------
def test_real_good_fits_loads(real_fits_archive):
    at = _app_for("good.fits")
    at.run(timeout=30)
    assert not at.exception, f"Exception(s): {[str(e) for e in at.exception]}"
    assert at.session_state["file_loader_load_done"] is True


def test_real_faulty_fits_does_not_crash_the_page(real_fits_archive):
    """Whatever 'faulty' means, the page itself must never raise -- and per
    the FR-03 investigation, faulty.fits is expected to load and pass
    structural verification cleanly (it's not byte-corrupt)."""
    at = _app_for("faulty.fits")
    at.run(timeout=30)
    assert not at.exception, f"Exception(s): {[str(e) for e in at.exception]}"
    assert at.session_state["file_loader_load_done"] is True
    markdown_html = _markdown_html(at)
    assert "OK" in markdown_html


# --------------------------------------------------------------------------
# Page 01 -> Page 02 handoff (utils/source_browser_logic.THIS_STAGE_KEY)
# --------------------------------------------------------------------------
def test_page01_selection_is_picked_up_by_page02(fits_archive):
    """Simulates what 01_Source_Browser.py writes on 'Load into Pipeline',
    without actually driving page 01's UI -- confirms page 02 reads the
    real pipeline_data shape, keyed by the real THIS_STAGE_KEY, not a
    guessed key name."""
    from utils.source_browser_logic import THIS_STAGE_KEY

    at = AppTest.from_file(PAGE_PATH)
    at.session_state["pipeline_data"] = {
        THIS_STAGE_KEY: {"selected_files": ["good_dateobs.fits"], "frequency": "1420.405 MHz — HI line"}
    }
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["file_loader_load_done"] is True
    markdown_html = _markdown_html(at)
    assert "good_dateobs.fits" in markdown_html
    assert "DATE-OBS" in markdown_html


def test_page01_multiple_selected_files_all_processed(fits_archive):
    """The actual point of FR-03: page 01's selected_files is a list, and
    every file in it must be loaded + validated, not just the first."""
    from utils.source_browser_logic import THIS_STAGE_KEY

    at = AppTest.from_file(PAGE_PATH)
    at.session_state["pipeline_data"] = {
        THIS_STAGE_KEY: {"selected_files": ["good_date.fits", "good_dateobs.fits", "unrecognized.fits"]}
    }
    at.run(timeout=30)
    assert not at.exception
    markdown_html = _markdown_html(at)
    assert "good_date.fits" in markdown_html
    assert "good_dateobs.fits" in markdown_html
    assert "unrecognized.fits" in markdown_html
    assert "Loaded 2 of 3 file" in markdown_html


def test_standalone_override_still_works_without_page01(fits_archive):
    """Page 02 must still be independently testable/runnable without page 01
    ever having run -- this is what every other test in this file relies on."""
    at = _app_for("good_date.fits")
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["file_loader_load_done"] is True


# --------------------------------------------------------------------------
# FR-02: real ingestion
# --------------------------------------------------------------------------
def test_page_loads_without_exception(fits_archive):
    at = _app_for("good_date.fits")
    at.run(timeout=30)
    assert not at.exception


def test_date_convention_file_loads_successfully(fits_archive):
    at = _app_for("good_date.fits")
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["file_loader_load_done"] is True
    markdown_html = _markdown_html(at)
    assert "DATE" in markdown_html


def test_dateobs_convention_file_falls_back_and_loads(fits_archive):
    """This is the FR-02 'auto-detect DATE vs DATE-OBS' requirement --
    load_file() should fail on this file (no DATE key), and load_file2()
    should succeed on the fallback."""
    at = _app_for("good_dateobs.fits")
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["file_loader_load_done"] is True
    markdown_html = _markdown_html(at)
    assert "DATE-OBS" in markdown_html


def test_unrecognized_file_fails_gracefully_without_exception(fits_archive):
    at = _app_for("unrecognized.fits")
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["file_loader_load_done"] is False
    error_texts = "\n".join(e.value for e in at.error)
    assert "Could not load" in error_texts


def test_failed_load_does_not_mark_pipeline_stage_complete(fits_archive):
    at = _app_for("unrecognized.fits")
    at.run(timeout=30)
    assert not at.exception
    try:
        completed = at.session_state["completed_stages"]
    except KeyError:
        completed = set()
    assert "file_loader" not in completed


def test_successful_load_marks_pipeline_stage_complete(fits_archive):
    at = _app_for("good_date.fits")
    at.run(timeout=30)
    assert not at.exception
    assert "file_loader" in at.session_state["completed_stages"]


def test_partial_failure_across_multiple_files_still_marks_complete(fits_archive):
    """Confirmed design: if AT LEAST ONE file loaded, the stage still
    counts as in-progress/complete for pipeline purposes -- a single bad
    file in a multi-file selection shouldn't block the whole stage."""
    at = _app_for("good_date.fits", "unrecognized.fits")
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["file_loader_load_done"] is True
    assert "file_loader" in at.session_state["completed_stages"]
    error_texts = "\n".join(e.value for e in at.error)
    assert "Could not load 1 of 2" in error_texts


def test_successful_load_writes_audit_log_entry(fits_archive):
    at = _app_for("good_date.fits")
    at.run(timeout=30)
    assert not at.exception
    audit = at.session_state["audit_log"]
    assert any("good_date.fits loaded" in e["message"] for e in audit)


def test_failed_load_writes_audit_log_entry(fits_archive):
    at = _app_for("unrecognized.fits")
    at.run(timeout=30)
    assert not at.exception
    audit = at.session_state["audit_log"]
    assert any("FAILED to load" in e["message"] for e in audit)


def test_rerun_does_not_reopen_file_or_duplicate_audit_entry(fits_archive):
    """Clicking Quarantine triggers a rerun -- that rerun must not silently
    re-open the FITS file or write a second audit log entry."""
    at = _app_for("good_date.fits")
    at.run(timeout=30)
    at.run(timeout=30)
    assert not at.exception
    audit = at.session_state["audit_log"]
    load_entries = [e for e in audit if "good_date.fits loaded" in e["message"]]
    assert len(load_entries) == 1


def test_rerun_does_not_reverify_or_duplicate_audit_entry(fits_archive):
    """Same guarantee as above, for the FR-03 verify step."""
    at = _app_for("good_date.fits")
    at.run(timeout=30)
    at.run(timeout=30)
    assert not at.exception
    audit = at.session_state["audit_log"]
    verify_entries = [e for e in audit if "good_date.fits passed structural verification" in e["message"]]
    assert len(verify_entries) == 1


# --------------------------------------------------------------------------
# FR-03: real per-file validation table / quarantine (still session-state
# only for the actual move -- see module docstring in the page). Rewritten
# from the old static-sample-data version: these now load a real bad file
# (unrecognized.fits) alongside a good one, since the validation table is
# now built from real per-file results, not a fixed sample unrelated to
# what was actually loaded.
# --------------------------------------------------------------------------
def test_validation_table_shows_ok_for_clean_file(fits_archive):
    at = _app_for("good_date.fits")
    at.run(timeout=30)
    assert not at.exception
    markdown_html = _markdown_html(at)
    assert "OK" in markdown_html
    assert "FLAGGED" not in markdown_html


def test_validation_table_shows_flagged_for_bad_file(fits_archive):
    at = _app_for("good_date.fits", "unrecognized.fits")
    at.run(timeout=30)
    assert not at.exception
    markdown_html = _markdown_html(at)
    assert "OK" in markdown_html
    assert "FLAGGED" in markdown_html


def test_quarantine_button_stages_pending_confirmation_not_immediate(fits_archive):
    """FR-03 handoff step 4: clicking Quarantine must NOT quarantine
    immediately -- it stages a pending confirmation instead."""
    at = _app_for("good_date.fits", "unrecognized.fits")
    at.run(timeout=30)
    at.button(key="quarantine_unrecognized.fits").click().run(timeout=30)
    assert not at.exception
    assert at.session_state["file_loader_pending_quarantine"] == "unrecognized.fits"
    try:
        quarantined_now = at.session_state["file_loader_quarantined"]
    except KeyError:
        quarantined_now = set()
    assert "unrecognized.fits" not in quarantined_now
    markdown_html = _markdown_html(at)
    assert "does NOT yet move the file" in markdown_html
    assert at.button(key="confirm_quarantine_unrecognized.fits").label == "Continue"
    assert at.button(key="cancel_quarantine_unrecognized.fits").label == "Cancel"


def test_confirming_quarantine_updates_status(fits_archive):
    at = _app_for("good_date.fits", "unrecognized.fits")
    at.run(timeout=30)
    at.button(key="quarantine_unrecognized.fits").click().run(timeout=30)
    at.button(key="confirm_quarantine_unrecognized.fits").click().run(timeout=30)
    assert not at.exception
    assert "unrecognized.fits" in at.session_state["file_loader_quarantined"]
    assert at.session_state["file_loader_pending_quarantine"] is None
    markdown_html = _markdown_html(at)
    assert "QUARANTINED" in markdown_html
    audit = at.session_state["audit_log"]
    assert any("unrecognized.fits quarantined" in e["message"] for e in audit)


def test_cancelling_quarantine_leaves_file_flagged_not_quarantined(fits_archive):
    at = _app_for("good_date.fits", "unrecognized.fits")
    at.run(timeout=30)
    at.button(key="quarantine_unrecognized.fits").click().run(timeout=30)
    at.button(key="cancel_quarantine_unrecognized.fits").click().run(timeout=30)
    assert not at.exception
    try:
        quarantined_now = at.session_state["file_loader_quarantined"]
    except KeyError:
        quarantined_now = set()
    assert "unrecognized.fits" not in quarantined_now
    assert at.session_state["file_loader_pending_quarantine"] is None
    markdown_html = _markdown_html(at)
    assert "FLAGGED" in markdown_html
    assert "QUARANTINED" not in markdown_html


def test_quarantine_confirmation_scoped_to_one_file_at_a_time(fits_archive):
    """Clicking Quarantine on a second flagged row while one is already
    pending re-targets the single pending confirmation rather than
    stacking two -- per the handoff's explicit "one file at a time" scope.
    """
    at = _app_for("good_date.fits", "unrecognized.fits", "truncated.fits")
    at.run(timeout=30)
    at.button(key="quarantine_unrecognized.fits").click().run(timeout=30)
    assert at.session_state["file_loader_pending_quarantine"] == "unrecognized.fits"

    at.button(key="quarantine_truncated.fits").click().run(timeout=30)
    assert at.session_state["file_loader_pending_quarantine"] == "truncated.fits"

    # Confirming now only affects the currently-pending file, not the
    # earlier one that was staged and then re-targeted away from.
    at.button(key="confirm_quarantine_truncated.fits").click().run(timeout=30)
    assert not at.exception
    assert "truncated.fits" in at.session_state["file_loader_quarantined"]
    assert "unrecognized.fits" not in at.session_state["file_loader_quarantined"]


def test_quarantined_file_is_not_reloaded_on_rerun(fits_archive):
    """Once quarantined, a file must be excluded from the active load loop
    (per _render_load_progress's own design) and shown via its cached
    validation row rather than triggering a fresh _run_real_load call --
    this is the forward-compatibility guarantee for step 5's real
    shutil.move(), where the file won't exist at its original path anymore.
    """
    at = _app_for("good_date.fits", "unrecognized.fits")
    at.run(timeout=30)
    at.button(key="quarantine_unrecognized.fits").click().run(timeout=30)
    at.button(key="confirm_quarantine_unrecognized.fits").click().run(timeout=30)
    at.run(timeout=30)  # a further, unrelated rerun
    assert not at.exception
    markdown_html = _markdown_html(at)
    assert "Quarantined by user action" in markdown_html
    audit = at.session_state["audit_log"]
    load_attempts = [e for e in audit if "unrecognized.fits" in e["message"] and "loaded in" in e["message"]]
    # unrecognized.fits genuinely fails ingestion regardless -- the real
    # assertion is that quarantining it doesn't cause additional load
    # attempts beyond the one from before it was quarantined.
    assert len(load_attempts) <= 1


def test_verify_failure_flags_a_file_that_loaded_fine(fits_archive, monkeypatch):
    """Ingestion (FR-02) and structural verification (FR-03) are
    independent checks -- a file can pass load_file() and still fail
    verify_fits_file(). None of the synthetic fixtures happen to hit this
    combination naturally (the one byte-corrupt fixture, truncated.fits,
    fails to even open, so it's caught by the ingest branch first) -- so
    this test forces the verify-fails branch directly to confirm the page
    surfaces it correctly, independent of fixture availability.
    """
    import utils.fits_ingest as fits_ingest_module

    def fake_verify(path):
        return fits_ingest_module.VerificationResult(
            filename=Path(path).name,
            path=Path(path),
            ok=False,
            issues=["VerifyError: forced for test"],
        )

    monkeypatch.setattr(fits_ingest_module, "verify_fits_file", fake_verify)

    at = _app_for("good_date.fits")
    at.run(timeout=30)
    assert not at.exception
    markdown_html = _markdown_html(at)
    assert "FLAGGED" in markdown_html
    assert "VerifyError: forced for test" in markdown_html


# --------------------------------------------------------------------------
# Header-fields table search (static sample data for now -- see next step)
# --------------------------------------------------------------------------
def test_header_fields_search_filters_columns(fits_archive):
    at = _app_for("good_date.fits")
    at.run(timeout=30)
    at.text_input(key="file_loader_field_search").set_value("Vlsr").run(timeout=30)
    assert not at.exception
    markdown_html = _markdown_html(at)
    assert "Vlsr" in markdown_html
    assert "Humidity" not in markdown_html