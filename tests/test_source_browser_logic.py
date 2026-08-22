# test_source_browser_logic.py — unit tests for utils/source_browser_logic.py
# (FR-01 Source Browser). Pure-Python logic only, so these run without a
# Streamlit runtime, per pytest>=7.4 (see requirements.txt).

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hartspec_gui"))

from utils.source_browser_logic import (  # noqa: E402
    SourceFileEntry,
    SourceGroupEntry,
    all_filenames,
    build_summary_text,
    files_by_name,
    frequency_display_name,
    get_source_groups,
    status_css_class,
)


class TestGetSourceGroups:
    def test_returns_two_groups_matching_build_spec_labels(self):
        groups = get_source_groups()
        assert [g.label for g in groups] == ["2026-08 Observations", "2026-07 Observations"]

    def test_displayed_counts_match_build_spec_even_though_not_all_rows_are_itemized(self):
        groups = get_source_groups()
        assert groups[0].displayed_count == 12
        assert groups[1].displayed_count == 8


class TestFlattenHelpers:
    def test_all_filenames_preserves_group_then_file_order(self):
        groups = get_source_groups()
        assert all_filenames(groups) == [
            "spectrum_001.fits",
            "spectrum_002.fits",
            "spectrum_003.fits",
            "pss_survey_014.txt",
            "pss_survey_015.txt",
        ]

    def test_files_by_name_indexes_every_file(self):
        groups = get_source_groups()
        index = files_by_name(groups)
        assert set(index) == set(all_filenames(groups))
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
        self.groups = get_source_groups()
        self.index = files_by_name(self.groups)

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
