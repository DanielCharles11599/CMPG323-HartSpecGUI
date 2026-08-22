"""Integration tests for pages/02_File_Loader.py using streamlit.testing.v1.AppTest.

Runs the real page against real FITS fixtures (tests/fixtures/), with
fits_ingest.FITS_ARCHIVE_DIR/FLAGGED_DIR monkeypatched to a tmp_path copy so
tests never touch the production /data/fits/ archive.

Run with: pytest tests/test_02_file_loader.py -v
"""

import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PAGE_PATH = str(Path(__file__).resolve().parents[1] / "hartspec_gui" / "pages" / "02_File_Loader.py")
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fits_archive(tmp_path, monkeypatch):
    """Copy both sample fixtures into a tmp /data/fits/-alike directory and
    point utils.fits_ingest at it via env var.

    Uses HARTSPEC_FITS_ARCHIVE_DIR rather than monkeypatching the module
    attribute directly: AppTest reuses Python's module cache across runs
    within the same test process, so a constant set after first import is
    invisible to it. The env var is read live by fits_ingest's
    get_fits_archive_dir()/get_flagged_dir(), so this works regardless of
    caching (verified while building this suite -- the constant-patch
    approach silently fell back to the real /data/fits/).
    """
    archive = tmp_path / "fits"
    archive.mkdir()
    for fixture in FIXTURES_DIR.glob("*.fits"):
        shutil.copy(fixture, archive / fixture.name)

    monkeypatch.setenv("HARTSPEC_FITS_ARCHIVE_DIR", str(archive))
    return archive


def _select_file(at: AppTest, filename: str) -> AppTest:
    return at.selectbox(key="file_loader_selected_path").select(filename).run()


def test_page_loads_without_exception(fits_archive):
    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    at.run()
    assert not at.exception


def test_ok_file_shows_success_and_no_quarantine_button(fits_archive):
    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    at.run()
    _select_file(at, "sample_ok.fits")
    assert not at.exception

    assert len(at.success) >= 1
    quarantine_btns = [b for b in at.button if "Quarantine this file" in b.label]
    assert len(quarantine_btns) == 0


def test_broken_file_shows_error_and_quarantine_button(fits_archive):
    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    at.run()
    _select_file(at, "sample_broken_no_restfreq.fits")
    assert not at.exception

    assert len(at.error) >= 1
    error_text = " ".join(e.value for e in at.error)
    assert "RESTFREQ" in error_text

    quarantine_btns = [b for b in at.button if "Quarantine this file" in b.label]
    assert len(quarantine_btns) == 1


def test_full_quarantine_flow_moves_file(fits_archive):
    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    at.run()
    _select_file(at, "sample_broken_no_restfreq.fits")

    quarantine_btns = [b for b in at.button if "Quarantine this file" in b.label]
    quarantine_btns[0].click().run()
    assert not at.exception

    confirm_btns = [b for b in at.button if b.label == "Confirm"]
    assert len(confirm_btns) == 1
    confirm_btns[0].click().run()
    assert not at.exception

    assert not (fits_archive / "sample_broken_no_restfreq.fits").exists()
    assert (fits_archive / "Flagged" / "sample_broken_no_restfreq.fits").exists()
    assert "file_loader" in at.session_state["completed_stages"]


def test_quarantine_cancel_leaves_file_in_place(fits_archive):
    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    at.run()
    _select_file(at, "sample_broken_no_restfreq.fits")

    quarantine_btns = [b for b in at.button if "Quarantine this file" in b.label]
    quarantine_btns[0].click().run()

    cancel_btns = [b for b in at.button if b.label == "Cancel"]
    assert len(cancel_btns) == 1
    cancel_btns[0].click().run()
    assert not at.exception

    assert (fits_archive / "sample_broken_no_restfreq.fits").exists()
    # cancelling should re-show the Quarantine start button, not leave it
    # stuck showing the confirm block
    assert len([b for b in at.button if "Quarantine this file" in b.label]) == 1


def test_ok_file_marks_stage_complete(fits_archive):
    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    at.run()
    _select_file(at, "sample_ok.fits")
    assert not at.exception
    assert "file_loader" in at.session_state["completed_stages"]


def test_broken_file_does_not_mark_stage_complete(fits_archive):
    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    at.run()
    _select_file(at, "sample_broken_no_restfreq.fits")
    assert not at.exception
    assert "file_loader" not in at.session_state["completed_stages"]


def test_manual_mapping_toggle_renders_selectboxes(fits_archive):
    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    at.run()
    _select_file(at, "sample_ok.fits")

    at.radio(key="file_loader_mapping_mode").set_value("Manual").run()
    assert not at.exception

    mapping_boxes = [sb for sb in at.selectbox if "file_loader_manual_map::" in (sb.key or "")]
    assert len(mapping_boxes) == 9  # one per priority field


def test_extension_viewer_switches_hdu_without_exception(fits_archive):
    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    at.run()
    _select_file(at, "sample_ok.fits")

    candidates = [sb for sb in at.selectbox if "file_loader_ext_choice::" in (sb.key or "")]
    assert len(candidates) == 1
    ext_box = candidates[0]

    assert "PRIMARY" in ext_box.options[0]
    ext_box.select(ext_box.options[2]).run()  # switch to the "Spectra" HDU
    assert not at.exception