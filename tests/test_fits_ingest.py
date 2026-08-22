"""Unit tests for utils/fits_ingest.py, run against real FITS files.

Fixtures (tests/fixtures/) are real HartRAO data:
- sample_ok.fits: loads cleanly through both clc/load_file.py and
  clc/load_file2.py.
- sample_broken_no_restfreq.fits: missing a RESTFREQ key in HDU0, which
  crashes clc/load_file.py, and missing DATE-OBS (legacy DATE convention),
  which is the condition FR-02's auto-detection is meant to surface.

Run with: pytest tests/test_fits_ingest.py -v
"""

from pathlib import Path

import pytest

from utils import fits_ingest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_OK = FIXTURES_DIR / "sample_ok.fits"
SAMPLE_BROKEN = FIXTURES_DIR / "sample_broken_no_restfreq.fits"


class TestIngestOkFile:
    def test_status_ok(self):
        result = fits_ingest.ingest_fits(SAMPLE_OK)
        assert result.status == "ok"
        assert result.issues == []

    def test_scalar_fields_populated(self):
        result = fits_ingest.ingest_fits(SAMPLE_OK)
        assert result.scalar_fields is not None
        assert result.scalar_fields["object"] == "G328.24-0.55"
        assert result.scalar_fields["HPBW"] == pytest.approx(0.116)

    def test_array_fields_split_out(self):
        result = fits_ingest.ingest_fits(SAMPLE_OK)
        assert result.array_fields is not None
        assert "Vlsr" in result.array_fields
        assert "LCP" in result.array_fields
        assert "RCP" in result.array_fields
        # array fields must never leak into scalar_fields
        assert "Vlsr" not in result.scalar_fields

    def test_date_convention_modern(self):
        result = fits_ingest.ingest_fits(SAMPLE_OK)
        assert result.date_convention == "DATE-OBS"

    def test_raw_header_always_populated(self):
        result = fits_ingest.ingest_fits(SAMPLE_OK)
        assert len(result.raw_header) > 0
        assert "HDU0.OBJECT" in result.raw_header

    def test_priority_field_rows_cover_all_nine(self):
        result = fits_ingest.ingest_fits(SAMPLE_OK)
        rows = dict(fits_ingest.priority_field_rows(result))
        expected_labels = {
            "Vlsr", "LCP/RCP", "HPBW", "Tsys", "Date",
            "Object", "RA/Dec", "Focus", "Humidity",
        }
        assert set(rows.keys()) == expected_labels
        assert rows["Object"] == "G328.24-0.55"

    def test_ra_dec_genuinely_unavailable(self):
        # Documented gap, not a bug: neither loader nor the raw header
        # exposes source RA/Dec on real HartRAO files -- only telescope
        # LONGITUD/LATITUDE. This test pins that fact so a future header
        # format change gets caught instead of silently masked.
        result = fits_ingest.ingest_fits(SAMPLE_OK)
        assert "RA" not in result.raw_header.get("HDU0.OBJECT", "")
        assert not any(k.endswith(".RA") or k.endswith(".DEC") for k in result.raw_header)


class TestIngestBrokenFile:
    def test_status_error(self):
        result = fits_ingest.ingest_fits(SAMPLE_BROKEN)
        assert result.status == "error"

    def test_issue_names_restfreq(self):
        result = fits_ingest.ingest_fits(SAMPLE_BROKEN)
        assert any("RESTFREQ" in issue for issue in result.issues)

    def test_scalar_fields_none_on_crash(self):
        result = fits_ingest.ingest_fits(SAMPLE_BROKEN)
        assert result.scalar_fields is None

    def test_raw_header_fallback_still_available(self):
        # load_file.py crashing shouldn't leave the page with nothing --
        # raw_header must still be populated so the table isn't blank.
        result = fits_ingest.ingest_fits(SAMPLE_BROKEN)
        assert len(result.raw_header) > 0
        assert result.raw_header["HDU0.OBJECT"] == "G328.24-0.55"

    def test_legacy_date_convention_detected(self):
        result = fits_ingest.ingest_fits(SAMPLE_BROKEN)
        assert result.date_convention == "DATE (legacy)"
        assert any("Legacy DATE convention" in issue for issue in result.issues)

    def test_priority_rows_degrade_gracefully(self):
        # Even with load_file.py crashed entirely, priority fields that
        # exist in the raw header (Date, Object, Focus, Humidity, HPBW)
        # should still show a value via the fallback path.
        result = fits_ingest.ingest_fits(SAMPLE_BROKEN)
        rows = dict(fits_ingest.priority_field_rows(result))
        assert "not available" not in rows["Object"]
        assert "not available" not in rows["Date"]
        assert rows["Vlsr"] == "not available"  # array data, only in the crashed dict


class TestManualMapping:
    def test_override_wins_over_auto(self):
        result = fits_ingest.ingest_fits(SAMPLE_OK)
        mapping = {"Object": "HDU0.OBJECT"}
        rows = dict(fits_ingest.priority_field_rows(result, manual_mapping=mapping))
        assert "manual: HDU0.OBJECT" in rows["Object"]

    def test_unmapped_fields_unaffected(self):
        result = fits_ingest.ingest_fits(SAMPLE_OK)
        mapping = {"Object": "HDU0.OBJECT"}
        rows = dict(fits_ingest.priority_field_rows(result, manual_mapping=mapping))
        assert "manual" not in rows["Focus"]


class TestExtensionViewer:
    def test_lists_four_hdus(self):
        extensions = fits_ingest.list_extensions(SAMPLE_OK)
        assert len(extensions) == 4
        assert extensions[0].name == "PRIMARY"
        assert extensions[2].name == "Spectra"

    def test_read_extension_header_returns_tuples(self):
        cards = fits_ingest.read_extension_header(SAMPLE_OK, 0)
        assert isinstance(cards, list)
        assert all(len(c) == 3 for c in cards)
        keywords = [c[0] for c in cards]
        assert "OBJECT" in keywords

    def test_repeated_keywords_dont_collide(self):
        # Regression guard: header.cards (not header dict/keys) must be
        # used, so duplicate keywords like COMMENT don't silently overwrite.
        cards = fits_ingest.read_extension_header(SAMPLE_OK, 1)
        assert len(cards) == pytest.approx(60, abs=5)


class TestQuarantine:
    def test_moves_file_and_returns_destination(self, tmp_path):
        source = tmp_path / "to_quarantine.fits"
        source.write_bytes(SAMPLE_BROKEN.read_bytes())
        flagged_dir = tmp_path / "Flagged"

        destination = fits_ingest.move_to_flagged(source, flagged_dir=flagged_dir)

        assert not source.exists()
        assert destination.exists()
        assert destination.parent == flagged_dir

    def test_collision_gets_timestamped_not_overwritten(self, tmp_path):
        flagged_dir = tmp_path / "Flagged"
        flagged_dir.mkdir()
        (flagged_dir / "dup.fits").write_bytes(b"already here")

        source = tmp_path / "dup.fits"
        source.write_bytes(SAMPLE_BROKEN.read_bytes())

        destination = fits_ingest.move_to_flagged(source, flagged_dir=flagged_dir)

        assert destination.name != "dup.fits"
        assert destination.exists()
        assert (flagged_dir / "dup.fits").exists()  # original untouched

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            fits_ingest.move_to_flagged(tmp_path / "does_not_exist.fits", flagged_dir=tmp_path / "Flagged")


class TestListAvailableFits:
    def test_excludes_flagged_subdirectory(self, tmp_path):
        (tmp_path / "a.fits").write_bytes(b"x")
        (tmp_path / "b.fits").write_bytes(b"x")
        flagged = tmp_path / "Flagged"
        flagged.mkdir()
        (flagged / "quarantined.fits").write_bytes(b"x")

        found = fits_ingest.list_available_fits(tmp_path)

        assert {p.name for p in found} == {"a.fits", "b.fits"}

    def test_empty_dir_returns_empty_list(self, tmp_path):
        assert fits_ingest.list_available_fits(tmp_path / "nonexistent") == []