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
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

PAGE_PATH = str(Path(__file__).resolve().parents[1] / "hartspec_gui" / "pages" / "02_File_Loader.py")


def _app_for(filename: str) -> AppTest:
    """Build an AppTest instance targeting a specific fixture filename.

    Requires the `fits_archive` fixture to have run first (sets
    HARTSPEC_FITS_ARCHIVE_ROOT) -- callers must request it via a test
    argument even if they don't use the returned path directly.
    """
    at = AppTest.from_file(PAGE_PATH)
    at.session_state["file_loader_target_filename"] = filename
    return at


# --------------------------------------------------------------------------
# Real files (good.fits / faulty.fits) -- opt-in via real_fits_archive.
# These don't assert a specific outcome for faulty.fits, since we don't yet
# know WHY it's faulty (wrong convention vs. genuinely corrupt/incomplete) --
# run with `-s` to see IngestResult.convention/load_errors printed, then we
# can tighten these into real assertions once we know what we're looking at.
# --------------------------------------------------------------------------
def test_real_good_fits_loads(real_fits_archive):
    at = _app_for("good.fits")
    at.run(timeout=30)
    assert not at.exception, f"Exception(s): {[str(e) for e in at.exception]}"
    assert at.session_state["file_loader_load_done"] is True
    print(f"\ngood.fits loaded OK")


def test_real_faulty_fits_does_not_crash_the_page(real_fits_archive):
    """Whatever 'faulty' means, the page itself must never raise -- it
    should either load with a convention, or fail gracefully via st.error()."""
    at = _app_for("faulty.fits")
    at.run(timeout=30)
    assert not at.exception, f"Exception(s): {[str(e) for e in at.exception]}"
    load_done = at.session_state["file_loader_load_done"]
    if load_done:
        print(f"\nfaulty.fits actually loaded fine (not corrupt at the header level)")
    else:
        error_texts = "\n".join(e.value for e in at.error)
        print(f"\nfaulty.fits failed to load, as expected. Page error shown:\n{error_texts}")
        assert "Could not load" in error_texts


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
    markdown_html = "\n".join(m.value for m in at.markdown if m.value)
    assert "good_dateobs.fits" in markdown_html
    assert "DATE-OBS" in markdown_html


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
    markdown_html = "\n".join(m.value for m in at.markdown if m.value)
    assert "DATE" in markdown_html


def test_dateobs_convention_file_falls_back_and_loads(fits_archive):
    """This is the FR-02 'auto-detect DATE vs DATE-OBS' requirement --
    load_file() should fail on this file (no DATE key), and load_file2()
    should succeed on the fallback."""
    at = _app_for("good_dateobs.fits")
    at.run(timeout=30)
    assert not at.exception
    assert at.session_state["file_loader_load_done"] is True
    markdown_html = "\n".join(m.value for m in at.markdown if m.value)
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


# --------------------------------------------------------------------------
# FR-03: validation table / quarantine (still session-state only, not wired
# to a real quarantine function yet -- see module docstring in the page)
# --------------------------------------------------------------------------
def test_validation_table_shows_expected_badges(fits_archive):
    at = _app_for("good_date.fits")
    at.run(timeout=30)
    assert not at.exception
    markdown_html = "\n".join(m.value for m in at.markdown if m.value)
    assert "OK" in markdown_html
    assert "FLAGGED" in markdown_html


def test_quarantine_button_updates_status(fits_archive):
    at = _app_for("good_date.fits")
    at.run(timeout=30)
    at.button(key="quarantine_spectrum_003.fits").click().run(timeout=30)
    assert not at.exception
    assert "spectrum_003.fits" in at.session_state["file_loader_quarantined"]
    markdown_html = "\n".join(m.value for m in at.markdown if m.value)
    assert "QUARANTINED" in markdown_html


# --------------------------------------------------------------------------
# Header-fields table search (static sample data for now -- see next step)
# --------------------------------------------------------------------------
def test_header_fields_search_filters_columns(fits_archive):
    at = _app_for("good_date.fits")
    at.run(timeout=30)
    at.text_input(key="file_loader_field_search").set_value("Vlsr").run(timeout=30)
    assert not at.exception
    markdown_html = "\n".join(m.value for m in at.markdown if m.value)
    assert "Vlsr" in markdown_html
    assert "Humidity" not in markdown_html