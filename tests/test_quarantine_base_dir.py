# test_quarantine_base_dir.py — FR-03: Flagged/ is created in the browsed directory, not in FITS_ARCHIVE_PATH.
"""Regression tests for the quarantine-destination bug.

Bug: `Flagged/` was always created under FITS_ARCHIVE_PATH, so researchers who browsed to another directory
lost track of their quarantined files. `move_to_quarantine(filename, base_dir=...)` now creates it in the browsed
directory and never falls back to the archive root.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from utils import fits_ingest


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    """An archive root (what FITS_ARCHIVE_PATH points at) and a separate directory the user 'browsed' to."""
    archive = tmp_path / "archive"
    browsed = tmp_path / "browsed"
    archive.mkdir()
    browsed.mkdir()
    monkeypatch.setenv("FITS_ARCHIVE_PATH", str(archive))
    return archive, browsed


def _make(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_flagged_created_in_browsed_dir_not_archive_root(dirs):
    archive, browsed = dirs
    src = _make(browsed / "bad.fits")
    dest = fits_ingest.move_to_quarantine(str(src.resolve()), base_dir=browsed)
    assert dest == browsed / "Flagged" / "bad.fits"
    assert dest.is_file() and not src.exists()
    assert not (archive / "Flagged").exists()  # nothing may land in FITS_ARCHIVE_PATH


def test_subdirectory_file_goes_to_one_flat_flagged_in_browsed_dir(dirs):
    archive, browsed = dirs
    src = _make(browsed / "2026-08" / "bad.fits")
    dest = fits_ingest.move_to_quarantine(str(src.resolve()), base_dir=browsed)
    assert dest == browsed / "Flagged" / "bad.fits"
    assert not (archive / "Flagged").exists()


def test_relative_filename_under_archive_with_browsed_subdir(dirs):
    archive, _ = dirs
    _make(archive / "2026-08" / "bad.fits")
    sub = archive / "2026-08"
    dest = fits_ingest.move_to_quarantine("2026-08/bad.fits", base_dir=sub)
    assert dest == sub / "Flagged" / "bad.fits"
    assert not (archive / "Flagged").exists()


def test_no_base_dir_keeps_archive_root_behaviour(dirs):
    archive, _ = dirs
    _make(archive / "bad.fits")
    assert fits_ingest.move_to_quarantine("bad.fits") == archive / "Flagged" / "bad.fits"


def test_name_collision_gets_suffix_not_overwrite(dirs):
    _, browsed = dirs
    _make(browsed / "Flagged" / "bad.fits", "old")
    src = _make(browsed / "bad.fits", "new")
    dest = fits_ingest.move_to_quarantine(str(src.resolve()), base_dir=browsed)
    assert dest.name == "bad__2.fits"
    assert (browsed / "Flagged" / "bad.fits").read_text() == "old"


def test_missing_browsed_dir_raises_and_does_not_fall_back(dirs, tmp_path):
    archive, browsed = dirs
    src = _make(browsed / "bad.fits")
    with pytest.raises(fits_ingest.QuarantineError):
        fits_ingest.move_to_quarantine(str(src.resolve()), base_dir=tmp_path / "does_not_exist")
    assert src.exists() and not (archive / "Flagged").exists()


def test_browsing_into_flagged_folder_does_not_nest(dirs):
    _, browsed = dirs
    flagged = browsed / "Flagged"
    src = _make(flagged / "bad.fits")
    assert fits_ingest.move_to_quarantine(str(src.resolve()), base_dir=flagged) == src
    assert src.is_file() and not (flagged / "Flagged").exists() and not (flagged / "bad__2.fits").exists()


def test_quarantine_dir_matches_actual_destination(dirs):
    """The folder shown in the Page 02 confirm text must be the folder the file really lands in."""
    archive, browsed = dirs
    assert fits_ingest.quarantine_dir(browsed) == browsed / "Flagged"
    assert fits_ingest.quarantine_dir(browsed / "Flagged") == browsed / "Flagged"
    assert fits_ingest.quarantine_dir(None) == archive / "Flagged"
    src = _make(browsed / "bad.fits")
    dest = fits_ingest.move_to_quarantine(str(src.resolve()), base_dir=browsed)
    assert dest.parent == fits_ingest.quarantine_dir(browsed)
