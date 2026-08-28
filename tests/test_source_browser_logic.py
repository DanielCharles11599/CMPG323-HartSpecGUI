# test_source_browser_logic.py — unit tests for utils/source_browser_logic.py
# (FR-01 Source & Frequency Browser). Pure-Python logic only, so these run
# without a Streamlit runtime, per pytest>=7.4 (see requirements.txt).
#
# astropy.io.fits.getheader is monkeypatched rather than given real FITS
# files to parse — these tests are about scan_fits_directory_tree()'s own
# logic (tree structure, filtering, status handling), not astropy's FITS
# parsing itself.

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hartspec_gui"))

from utils import source_browser_logic as sbl  # noqa: E402
from utils.source_browser_logic import (  # noqa: E402
    build_summary_text,
    default_fits_directory,
    distinct_frequencies_mhz,
    distinct_source_names,
    earliest_observation_date,
    flatten_files,
    matching_files,
    run_file_check_placeholder,
    scan_fits_directory_tree,
    status_css_class,
)


@pytest.fixture
def fake_fits_header(monkeypatch):
    """Replace astropy.io.fits.getheader with a tiny in-memory stand-in.

    Fixture files contain "KEY=value" lines; a file containing the literal
    string "CORRUPT" simulates an unreadable header.
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


def _write_fits(path: Path, date_obs=None, obj=None, restfreq_hz=None, corrupt=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if corrupt:
        path.write_text("CORRUPT GARBAGE, NOT A REAL HEADER")
        return
    lines = []
    if date_obs:
        lines.append(f"DATE-OBS={date_obs}")
    if obj:
        lines.append(f"OBJECT={obj}")
    if restfreq_hz is not None:
        lines.append(f"RESTFREQ={restfreq_hz}")
    path.write_text("\n".join(lines) + "\n")


class TestDefaultFitsDirectory:
    def test_uses_env_var_when_set(self, monkeypatch):
        monkeypatch.setenv("FITS_ARCHIVE_PATH", "/custom/path")
        assert default_fits_directory() == "/custom/path"

    def test_falls_back_to_local_relative_path_when_nothing_available(self, monkeypatch):
        monkeypatch.delenv("FITS_ARCHIVE_PATH", raising=False)
        monkeypatch.setattr(sbl.Path, "is_dir", lambda self: False)
        assert default_fits_directory() == "./data/fits"


class TestScanFitsDirectoryTree:
    def test_missing_directory_returns_none(self, tmp_path):
        assert scan_fits_directory_tree(tmp_path / "does-not-exist") is None

    def test_finds_fits_and_fit_extensions(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "a.fits", date_obs="2026-08-01T00:00:00", obj="W3(OH)", restfreq_hz=1420405751.786)
        _write_fits(tmp_path / "b.fit", date_obs="2026-08-02T00:00:00", obj="W3(OH)", restfreq_hz=1420405751.786)
        (tmp_path / "notes.txt").write_text("not a fits file")

        tree = scan_fits_directory_tree(tmp_path)
        filenames = {f.filename for f in flatten_files(tree)}
        assert filenames == {"a.fits", "b.fit"}

    def test_builds_nested_structure_for_subdirectories(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "2026-08" / "a.fits", date_obs="2026-08-01T00:00:00", obj="W3(OH)")
        _write_fits(tmp_path / "2026-07" / "b.fits", date_obs="2026-07-01T00:00:00", obj="W49N")

        tree = scan_fits_directory_tree(tmp_path)
        subdir_names = {child.name for child in tree.subdirectories}
        assert subdir_names == {"2026-08", "2026-07"}

    def test_corrupt_header_is_flagged_not_crashed(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "bad.fits", corrupt=True)
        tree = scan_fits_directory_tree(tmp_path)
        entry = flatten_files(tree)[0]
        assert entry.status == "FLAGGED"
        assert entry.source_name is None
        assert entry.frequency_mhz is None

    def test_restfreq_hz_converted_to_mhz(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "a.fits", obj="W3(OH)", restfreq_hz=1420405751.786)
        tree = scan_fits_directory_tree(tmp_path)
        entry = flatten_files(tree)[0]
        assert entry.frequency_mhz == pytest.approx(1420.406, abs=0.001)

    def test_max_depth_stops_descending(self, tmp_path, fake_fits_header):
        deep_path = tmp_path
        for i in range(6):
            deep_path = deep_path / f"level{i}"
        _write_fits(deep_path / "deep.fits", obj="X")

        tree = scan_fits_directory_tree(tmp_path, max_depth=2)
        # Should not find the file 6 levels down when capped at depth 2.
        assert flatten_files(tree) == []


class TestDropdownOptions:
    def test_distinct_source_names_sorted_and_deduplicated(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "a.fits", obj="W49N")
        _write_fits(tmp_path / "b.fits", obj="W3(OH)")
        _write_fits(tmp_path / "c.fits", obj="W49N")

        tree = scan_fits_directory_tree(tmp_path)
        assert distinct_source_names(tree) == ["W3(OH)", "W49N"]

    def test_distinct_frequencies_sorted_and_deduplicated(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "a.fits", obj="X", restfreq_hz=1420405751.786)
        _write_fits(tmp_path / "b.fits", obj="X", restfreq_hz=1612231000.0)
        _write_fits(tmp_path / "c.fits", obj="X", restfreq_hz=1420405751.786)

        tree = scan_fits_directory_tree(tmp_path)
        freqs = distinct_frequencies_mhz(tree)
        assert freqs == sorted(freqs)
        assert len(freqs) == 2

    def test_files_without_headers_are_excluded_from_options(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "bad.fits", corrupt=True)
        tree = scan_fits_directory_tree(tmp_path)
        assert distinct_source_names(tree) == []
        assert distinct_frequencies_mhz(tree) == []


class TestMatchingFiles:
    def test_filters_by_both_source_and_frequency(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "a.fits", obj="W3(OH)", restfreq_hz=1420405751.786)
        _write_fits(tmp_path / "b.fits", obj="W3(OH)", restfreq_hz=1612231000.0)
        _write_fits(tmp_path / "c.fits", obj="W49N", restfreq_hz=1420405751.786)

        tree = scan_fits_directory_tree(tmp_path)
        matched = matching_files(tree, "W3(OH)", 1420.406)
        assert [f.filename for f in matched] == ["a.fits"]

    def test_none_filters_match_everything(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "a.fits", obj="W3(OH)")
        _write_fits(tmp_path / "b.fits", obj="W49N")
        tree = scan_fits_directory_tree(tmp_path)
        assert len(matching_files(tree, None, None)) == 2

    def test_none_tree_returns_empty(self):
        assert matching_files(None, "X", 1.0) == []


class TestEarliestObservationDate:
    def test_returns_minimum_date(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "a.fits", obj="X", date_obs="2026-08-12T00:00:00")
        _write_fits(tmp_path / "b.fits", obj="X", date_obs="2026-07-01T00:00:00")
        tree = scan_fits_directory_tree(tmp_path)
        files = flatten_files(tree)
        assert earliest_observation_date(files) == "2026-07-01"

    def test_none_when_no_dates_available(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "bad.fits", corrupt=True)
        tree = scan_fits_directory_tree(tmp_path)
        files = flatten_files(tree)
        assert earliest_observation_date(files) is None

    def test_empty_list_returns_none(self):
        assert earliest_observation_date([]) is None


class TestStatusCssClass:
    @pytest.mark.parametrize(
        "status,expected",
        [("OK", "ok"), ("ok", "ok"), ("FLAGGED", "error"), ("QUARANTINED", "error"),
         ("WARNING", "warning"), ("SOMETHING_UNKNOWN", "info")],
    )
    def test_maps_known_and_unknown_statuses(self, status, expected):
        assert status_css_class(status) == expected


class TestBuildSummaryText:
    def test_empty_selection(self):
        assert build_summary_text([], "W3(OH)", 1420.406, None) == "No matching FITS files for the current filters."

    def test_singular_vs_plural_and_all_fields_present(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "a.fits", obj="W3(OH)", restfreq_hz=1420405751.786, date_obs="2026-08-12T00:00:00")
        tree = scan_fits_directory_tree(tmp_path)
        files = flatten_files(tree)

        text = build_summary_text(files, "W3(OH)", 1420.406, "2026-08-12")
        assert text == "1 file matched — W3(OH) · 1420.406 MHz · earliest observation 2026-08-12"

    def test_missing_earliest_date_degrades_gracefully(self, tmp_path, fake_fits_header):
        _write_fits(tmp_path / "a.fits", obj="W3(OH)", restfreq_hz=1420405751.786)
        tree = scan_fits_directory_tree(tmp_path)
        files = flatten_files(tree)
        text = build_summary_text(files, "W3(OH)", 1420.406, None)
        assert "date pending" in text


class TestRunFileCheckPlaceholder:
    def test_writes_a_block_file_listing_the_given_paths(self, tmp_path):
        workspace_dir = tmp_path / "workspace"
        fits_paths = [tmp_path / "a.fits", tmp_path / "b.fits"]

        block_file = run_file_check_placeholder(fits_paths, workspace_dir)

        assert block_file.exists()
        content = block_file.read_text().splitlines()
        assert content == [str(p) for p in fits_paths]

    def test_creates_workspace_directory_if_missing(self, tmp_path):
        workspace_dir = tmp_path / "nested" / "workspace"
        run_file_check_placeholder([], workspace_dir)
        assert workspace_dir.is_dir()
