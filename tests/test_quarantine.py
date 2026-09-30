"""Direct unit tests for utils.fits_ingest.move_to_quarantine() (FR-03
handoff step 5) -- independent of pages/02_File_Loader.py's AppTest
coverage, which only exercises this through the confirm/cancel UI flow.
These test the function's own contract in isolation: real moves,
collision handling, and error paths.

All tests use `isolated_fits_archive` (function-scoped, see conftest.py),
never the shared session-scoped `fits_archive` -- every test here performs
a real, destructive filesystem move.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.fits_ingest import QuarantineError, move_to_quarantine


def test_move_to_quarantine_moves_the_file(isolated_fits_archive):
    original = isolated_fits_archive / "good_date.fits"
    assert original.is_file()

    dest = move_to_quarantine("good_date.fits")

    assert not original.exists()
    assert dest.is_file()
    assert dest == isolated_fits_archive / "Flagged" / "good_date.fits"


def test_move_to_quarantine_creates_flagged_dir_if_missing(isolated_fits_archive):
    flagged_dir = isolated_fits_archive / "Flagged"
    assert not flagged_dir.exists()

    move_to_quarantine("good_date.fits")

    assert flagged_dir.is_dir()


def test_move_to_quarantine_uses_basename_for_nested_filename(isolated_fits_archive):
    """Per the function's own docstring: a subdirectory-prefixed filename
    (as Page 01's directory-tree scan can produce) lands at the basename
    directly under Flagged/, not a mirrored subdirectory -- the build
    spec describes a single flat Flagged/ directory."""
    subdir = isolated_fits_archive / "2026-08"
    subdir.mkdir()
    nested = subdir / "nested_target.fits"
    (isolated_fits_archive / "good_date.fits").rename(nested)

    dest = move_to_quarantine("2026-08/nested_target.fits")

    assert dest == isolated_fits_archive / "Flagged" / "nested_target.fits"
    assert dest.is_file()
    assert not nested.exists()


def test_move_to_quarantine_does_not_overwrite_existing_collision(isolated_fits_archive):
    """Two different files that would both land on the same Flagged/
    basename must NOT silently overwrite each other -- that would be
    silent data loss on an archive that's read-only everywhere except
    this one action."""
    subdir = isolated_fits_archive / "2026-08"
    subdir.mkdir()
    duplicate_named = subdir / "good_date.fits"
    # Give it different content so we can tell the two apart after the move.
    duplicate_named.write_bytes((isolated_fits_archive / "good_date.fits").read_bytes() + b"\x00EXTRA")

    first_dest = move_to_quarantine("good_date.fits")
    second_dest = move_to_quarantine("2026-08/good_date.fits")

    assert first_dest != second_dest
    assert first_dest.name == "good_date.fits"
    assert second_dest.name == "good_date__2.fits"
    assert first_dest.is_file() and second_dest.is_file()
    # Confirm neither file's content was clobbered by the other.
    assert first_dest.read_bytes() != second_dest.read_bytes()


def test_move_to_quarantine_raises_quarantine_error_for_missing_file(isolated_fits_archive):
    with pytest.raises(QuarantineError, match="was not found"):
        move_to_quarantine("does_not_exist.fits")


def test_move_to_quarantine_never_raises_raw_oserror(isolated_fits_archive, monkeypatch):
    """QuarantineError is the ONLY exception type this function should
    ever raise -- callers (the page) catch that one type and show one
    consistent message, so a raw OSError/shutil.Error leaking through
    would silently bypass that error handling."""
    import shutil as shutil_module

    def _boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(shutil_module, "move", _boom)

    with pytest.raises(QuarantineError, match="could not move"):
        move_to_quarantine("good_date.fits")


def test_move_to_quarantine_reports_flagged_dir_creation_failure(isolated_fits_archive, monkeypatch):
    """If Flagged/ can't be created (permissions, disk full, etc.), that
    must also surface as QuarantineError, not a raw OSError."""

    def _boom(self, *args, **kwargs):
        raise OSError("simulated permission denied")

    monkeypatch.setattr(Path, "mkdir", _boom)

    with pytest.raises(QuarantineError, match="could not create/access"):
        move_to_quarantine("good_date.fits")
        