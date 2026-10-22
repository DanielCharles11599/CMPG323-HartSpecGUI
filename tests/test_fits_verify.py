"""Tests for utils.fits_ingest.verify_fits_file() (FR-03, step 1).

Structural-corruption check only -- see verify_fits_file's docstring for
what it does and doesn't cover. Synthetic-fixture tests below are the ones
that run everywhere (CI, any teammate's machine). The real_fits_archive
tests at the bottom are diagnostic, not pass/fail: we don't yet know what's
actually wrong with faulty.fits, so those tests report findings via -s
output rather than asserting a specific outcome.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utils.fits_ingest import verify_fits_file


def test_good_date_file_verifies_clean(fits_archive):
    result = verify_fits_file(fits_archive / "good_date.fits")
    assert result.ok, f"expected no issues, got: {result.issues}"
    assert result.issues == []


def test_good_dateobs_file_verifies_clean(fits_archive):
    result = verify_fits_file(fits_archive / "good_dateobs.fits")
    assert result.ok, f"expected no issues, got: {result.issues}"


def test_unrecognized_file_is_structurally_fine(fits_archive):
    """Missing science keys (TCAL1 etc.) is an FR-02/ingest concern, not a
    structural one -- verify_fits_file() should NOT flag this file, even
    though ingest_fits_file() would fail to load it.
    """
    result = verify_fits_file(fits_archive / "unrecognized.fits")
    assert result.ok, f"expected no structural issues, got: {result.issues}"


def test_truncated_file_is_flagged(fits_archive):
    result = verify_fits_file(fits_archive / "truncated.fits")
    assert not result.ok
    assert result.issues, "expected at least one issue for a byte-truncated file"


def test_missing_file_is_flagged_not_raised():
    result = verify_fits_file(Path("/nonexistent/path/does_not_exist.fits"))
    assert not result.ok
    assert result.issues


def test_result_never_raises_on_garbage_bytes(tmp_path):
    """Not a FITS file at all -- still must return a result, not raise."""
    garbage = tmp_path / "not_a_fits_file.fits"
    garbage.write_bytes(b"this is definitely not a FITS file" * 10)
    result = verify_fits_file(garbage)
    assert not result.ok
    assert result.issues


# ---------------------------------------------------------------------------
# Diagnostic tests against the REAL good.fits / faulty.fits, per the FR-03
# handoff: "build the fits.verify() check first, run it against faulty.fits
# empirically, and let the actual result tell us". These are opt-in
# (real_fits_archive skips automatically if HARTSPEC_REAL_FITS_DIR isn't
# set) and print findings rather than asserting a specific outcome, since
# we don't yet know what's actually wrong with faulty.fits.
#
# Run with -s to see the printed output:
#   pytest tests/test_fits_verify.py -v -s -k real
# ---------------------------------------------------------------------------

def test_real_good_fits_diagnostic(real_fits_archive):
    path = real_fits_archive / "good.fits"
    if not path.is_file():
        pytest.skip(f"good.fits not found at {path}")
    result = verify_fits_file(path)
    print(f"\n--- good.fits ---\nok={result.ok}\nchecksum_checked={result.checksum_checked}")
    for issue in result.issues:
        print(f"  ISSUE: {issue}")


def test_real_faulty_fits_diagnostic(real_fits_archive):
    path = real_fits_archive / "faulty.fits"
    if not path.is_file():
        pytest.skip(f"faulty.fits not found at {path}")
    result = verify_fits_file(path)
    print(f"\n--- faulty.fits ---\nok={result.ok}\nchecksum_checked={result.checksum_checked}")
    for issue in result.issues:
        print(f"  ISSUE: {issue}")
    if result.ok:
        print(
            "  NOTE: verify_fits_file found NOTHING wrong with faulty.fits. "
            "Whatever makes it 'faulty' is invisible to this structural check "
            "-- likely bad/NaN data values or something else a human judges, "
            "not byte-level corruption. Report this back before building FR-03 further."
        )
