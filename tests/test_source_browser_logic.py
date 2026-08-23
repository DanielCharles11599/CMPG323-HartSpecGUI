# test_source_browser_logic.py — unit tests for utils/source_browser_logic.py
# (FR-01 Source Browser). Pure-Python logic only, so these run without a
# Streamlit runtime, per pytest>=7.4 (see requirements.txt).
#
# astropy.io.fits.getheader is monkeypatched rather than given real FITS
# files to parse — these tests are about scan_source_groups()'s own logic
# (grouping, status handling, missing directories), not about astropy's FITS
# parsing, which is already astropy's own well-tested responsibility.

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hartspec_gui"))

from utils import source_browser_logic as sbl  # noqa: E402
from utils.source_browser_logic import (  # noqa: E402
    SourceFileEntry,
    all_filenames,
    build_summary_text,
    files_by_name,
    frequency_display_name,
    get_source_groups,
    scan_source_groups,
    status_css_class,
)


@pytest.fixture
def fake_fits_header(monkeypatch):
    """Replace astropy.io.fits.getheader with a tiny in-memory stand-in.

    Test fixture files just contain "KEY=value" lines; a file containing the
    literal string "CORRUPT" simulates an unreadable header (astropy would
    raise for real malformed FITS, which _scan_fits_file catches broadly via
    `except Exception`).
    """

    def _parse_value(raw: str):
        raw = raw.strip()
        try:
            return float(raw) if "." in raw else int(raw)
        except ValueError:
            return raw

    def _fake_getheader(path):
        text = Path(path).read_text()
        if "CORRUPT" in text:
            raise OSError("simulated corrupt FITS header")
        header = {}
        for line in text.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                header[key.strip()] = _parse_value(value)
        return header

    monkeypatch.setattr(sbl.fits, "getheader", _fake_getheader)


class TestFormatDeclination:
    def test_numeric_degrees_positive(self):
        assert sbl._format_declination(12.5667) == "+12°34'"

    def test_numeric_degrees_negative(self):
        assert sbl._format_declination(-4.5) == "-4°30'"

    def test_preformatted_string_passthrough(self):
        assert sbl._format_declination("+12:34:00") == "+12:34:00"

    def test_none_and_unparsable_return_none(self):
        assert sbl._format_declination(None) is None
        assert sbl._format_declination(object()) is None


class TestScanSourceGroups:
    def test_scans_real_fits_and_pss_files(self, tmp_path, fake_fits_header):
        fits_dir = tmp_path / "fits"
        pss_dir = tmp_path / "pss"
        fits_dir.mkdir()
        pss_dir.mkdir()

        (fits_dir / "spectrum_002.fits").write_text("DATE-OBS=2026-08-12T10:00:00\nDEC=12.5667\n")
        (pss_dir / "pss_survey_014.txt").write_text("some pss calibration data\n")

        groups = scan_source_groups(fits_dir, pss_dir)
        index = {f.filename: f for g in groups for f in g.files}

        assert index["spectrum_002.fits"].status == "OK"
        assert index["spectrum_002.fits"].observation_date == "2026-08-12"
        assert index["spectrum_002.fits"].declination == "+12°34'"
        assert index["spectrum_002.fits"].file_type == "FITS"

        assert index["pss_survey_014.txt"].status == "OK"
        assert index["pss_survey_014.txt"].file_type == "PSS"
        assert index["pss_survey_014.txt"].observation_date is None

    def test_corrupt_fits_header_is_flagged_not_crashed(self, tmp_path, fake_fits_header):
        fits_dir = tmp_path / "fits"
        fits_dir.mkdir()
        (fits_dir / "bad.fits").write_text("CORRUPT GARBAGE, NOT A REAL HEADER")

        groups = scan_source_groups(fits_dir, tmp_path / "pss")
        entry = next(f for g in groups for f in g.files if f.filename == "bad.fits")
        assert entry.status == "FLAGGED"
        assert entry.observation_date is None

    def test_groups_by_header_observation_month(self, tmp_path, fake_fits_header):
        fits_dir = tmp_path / "fits"
        fits_dir.mkdir()
        (fits_dir / "a.fits").write_text("DATE-OBS=2026-08-10T00:00:00\n")
        (fits_dir / "b.fits").write_text("DATE-OBS=2026-07-15T00:00:00\n")

        groups = scan_source_groups(fits_dir, tmp_path / "pss")
        labels = [g.label for g in groups]
        assert labels == ["2026-08 Observations", "2026-07 Observations"]  # most recent first

    def test_missing_directories_return_empty_list_not_an_error(self, tmp_path):
        groups = scan_source_groups(tmp_path / "no-such-fits-dir", tmp_path / "no-such-pss-dir")
        assert groups == []

    def test_files_within_a_group_are_sorted_by_filename(self, tmp_path, fake_fits_header):
        fits_dir = tmp_path / "fits"
        fits_dir.mkdir()
        (fits_dir / "z_spectrum.fits").write_text("DATE-OBS=2026-08-01T00:00:00\n")
        (fits_dir / "a_spectrum.fits").write_text("DATE-OBS=2026-08-02T00:00:00\n")

        groups = scan_source_groups(fits_dir, tmp_path / "pss")
        filenames = [f.filename for f in groups[0].files]
        assert filenames == ["a_spectrum.fits", "z_spectrum.fits"]


class TestGetSourceGroupsWrapper:
    def test_delegates_to_scan_source_groups_with_explicit_paths(self, tmp_path, fake_fits_header):
        fits_dir = tmp_path / "fits"
        fits_dir.mkdir()
        (fits_dir / "only.fits").write_text("DATE-OBS=2026-01-01T00:00:00\n")

        wrapped = get_source_groups(fits_dir=fits_dir, pss_dir=tmp_path / "pss")
        direct = scan_source_groups(fits_dir, tmp_path / "pss")
        assert [f.filename for g in wrapped for f in g.files] == [f.filename for g in direct for f in g.files]


class TestFlattenHelpers:
    def test_all_filenames_and_files_by_name(self, tmp_path, fake_fits_header):
        fits_dir = tmp_path / "fits"
        fits_dir.mkdir()
        (fits_dir / "spectrum_002.fits").write_text("DATE-OBS=2026-08-12T00:00:00\nDEC=12.5667\n")
        groups = scan_source_groups(fits_dir, tmp_path / "pss")

        names = all_filenames(groups)
        assert names == ["spectrum_002.fits"]
        index = files_by_name(groups)
        assert index["spectrum_002.fits"].observation_date == "2026-08-12"


class TestFrequencyDisplayName:
    def test_splits_on_em_dash(self):
        assert frequency_display_name("1420.405 MHz — HI line") == "HI line"

    def test_falls_back_to_full_string_without_separator(self):
        assert frequency_display_name("22235 MHz") == "22235 MHz"


class TestStatusCssClass:
    @pytest.mark.parametrize(
        "status,expected",
        [("OK", "ok"), ("ok", "ok"), ("FLAGGED", "error"), ("QUARANTINED", "error"),
         ("WARNING", "warning"), ("SOMETHING_UNKNOWN", "info")],
    )
    def test_maps_known_and_unknown_statuses(self, status, expected):
        assert status_css_class(status) == expected


class TestBuildSummaryText:
    def setup_method(self):
        self.index = {
            "spectrum_002.fits": SourceFileEntry(
                "spectrum_002.fits", "FITS", 38, "OK",
                observation_date="2026-08-12", declination="+12°34'",
            ),
            "spectrum_001.fits": SourceFileEntry("spectrum_001.fits", "FITS", 42, "OK"),
            "pss_survey_015.txt": SourceFileEntry("pss_survey_015.txt", "PSS", 3, "OK"),
        }

    def test_empty_selection(self):
        text = build_summary_text([], self.index, "1420.405 MHz — HI line")
        assert text == "No files selected — choose one or more from the list above."

    def test_matches_build_spec_sample_text_exactly(self):
        text = build_summary_text(["spectrum_002.fits"], self.index, "1420.405 MHz — HI line")
        assert text == "Selected: spectrum_002.fits · 2026-08-12 · HI line · Dec +12°34'"

    def test_multiple_selection_appends_more_count(self):
        text = build_summary_text(
            ["spectrum_002.fits", "pss_survey_015.txt"], self.index, "1420.405 MHz — HI line"
        )
        assert text.startswith("Selected: spectrum_002.fits")
        assert text.endswith("(+1 more)")

    def test_missing_metadata_degrades_gracefully(self):
        text = build_summary_text(["spectrum_001.fits"], self.index, "1420.405 MHz — HI line")
        assert "date pending" in text
        assert "pending" in text
