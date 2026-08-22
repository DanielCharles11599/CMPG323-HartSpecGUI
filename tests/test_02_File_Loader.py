"""Smoke tests for pages/02_File_Loader.py using streamlit.testing.v1.AppTest.

Run with: pytest tests/test_02_file_loader.py -v
"""

from pathlib import Path
import sys

from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HARTSPEC_GUI = PROJECT_ROOT / "hartspec_gui"
sys.path.insert(0, str(HARTSPEC_GUI))

PAGE_PATH = str(Path(__file__).resolve().parents[1] / "hartspec_gui" / "pages" / "02_File_Loader.py")


def _fast_app() -> AppTest:
    """Build the AppTest instance with a near-instant simulated load,
    so the test doesn't sleep for the real 5-second FR-02 animation."""
    at = AppTest.from_file(PAGE_PATH, default_timeout=30)
    return at


def test_page_loads_without_exception():
    at = _fast_app()
    # Speed up the simulated load loop before the first run.
    at.session_state["file_loader_load_done"] = True  # skip animation for this test
    at.run()
    assert not at.exception


def test_validation_table_shows_expected_badges():
    at = _fast_app()
    at.session_state["file_loader_load_done"] = True
    at.run()
    assert not at.exception
    markdown_html = " ".join(m.value for m in at.markdown)
    assert "OK" in markdown_html
    assert "FLAGGED" in markdown_html
    assert "spectrum_003.fits" in markdown_html


def test_quarantine_button_updates_status():
    at = _fast_app()
    at.session_state["file_loader_load_done"] = True
    at.run()
    assert not at.exception

    quarantine_buttons = [b for b in at.button if "Quarantine" in b.label]
    assert len(quarantine_buttons) == 1

    quarantine_buttons[0].click().run()
    assert not at.exception
    assert "spectrum_003.fits" in at.session_state["file_loader_quarantined"]

    markdown_html = " ".join(m.value for m in at.markdown)
    assert "QUARANTINED" in markdown_html


def test_header_fields_search_filters_columns():
    at = _fast_app()
    at.session_state["file_loader_load_done"] = True
    at.run()
    assert not at.exception

    search_box = at.text_input(key="file_loader_field_search")
    search_box.set_value("tsys").run()
    assert not at.exception

    markdown_html = " ".join(m.value for m in at.markdown)
    assert "Tsys" in markdown_html
    assert "Humidity" not in markdown_html


def test_pipeline_stage_marked_complete_after_load():
    at = _fast_app()
    at.session_state["file_loader_load_done"] = True
    at.run()
    assert not at.exception
    assert "file_loader" in at.session_state["completed_stages"]
