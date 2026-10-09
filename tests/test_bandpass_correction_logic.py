"""Unit tests for the current FR-04 bandpass-correction logic.

These tests target the entry-pair API used by Page 03:
    build_bandpass_result(mode, (entry1, entry2))

They test the numerical correction functions directly and do not launch Streamlit.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Add the repository root so the test can import hartspec_gui.utils.*.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hartspec_gui.utils.bandpass_correction_logic import (  # noqa: E402
    MODE_OPTIONS,
    build_bandpass_result,
    common_velocity_range,
    freq_switch_correct,
    get_full_integration_pairs,
    pos_switch_correct,
    stage_summary,
    suggest_mode,
)


@pytest.fixture
def identical_grid_pair():
    """Two spectra with identical velocity grids and known channel values."""
    spec1 = {
        "Vlsr": np.array([0.0, 1.0, 2.0]),
        "LCP": np.array([10.0, 11.0, 12.0]),
        "RCP": np.array([5.0, 6.0, 7.0]),
    }
    spec2 = {
        "Vlsr": np.array([0.0, 1.0, 2.0]),
        "LCP": np.array([1.0, 1.0, 1.0]),
        "RCP": np.array([2.0, 2.0, 2.0]),
    }
    return spec1, spec2


@pytest.fixture
def offset_grid_pair():
    """Two spectra with partially overlapping Vlsr grids."""
    spec1 = {
        "Vlsr": np.array([0.0, 1.0, 2.0]),
        "LCP": np.array([10.0, 11.0, 12.0]),
        "RCP": np.array([5.0, 6.0, 7.0]),
    }
    spec2 = {
        "Vlsr": np.array([1.0, 2.0, 3.0]),
        "LCP": np.array([1.0, 1.0, 1.0]),
        "RCP": np.array([2.0, 2.0, 2.0]),
    }
    return spec1, spec2


def make_entry(filename, spectrum, *, position="ON", pointing=0, observation_dir="obs-A"):
    """Build the metadata wrapper expected by the current pairing API."""
    return {
        "filename": filename,
        "spectrum": spectrum,
        "position": position,
        "pointing": pointing,
        "observation_dir": observation_dir,
    }


def make_pair(spectra, *, positions=("ON", "OFF"), filenames=("first.fits", "second.fits")):
    spec1, spec2 = spectra
    return (
        make_entry(filenames[0], spec1, position=positions[0]),
        make_entry(filenames[1], spec2, position=positions[1]),
    )


class TestModeOptions:
    def test_exposes_the_two_specified_modes(self):
        assert MODE_OPTIONS == ["Frequency Switch", "Position Switch"]


class TestFreqSwitchCorrect:
    def test_subtracts_both_directions_and_keeps_common_velocity_channels(self, offset_grid_pair):
        spec1, spec2 = offset_grid_pair
        corrected1, corrected2 = freq_switch_correct(spec1, spec2)

        np.testing.assert_array_equal(corrected1["Vlsr"], [1.0, 2.0])
        np.testing.assert_array_equal(corrected1["LCP"], [10.0, 11.0])
        np.testing.assert_array_equal(corrected1["RCP"], [4.0, 5.0])
        np.testing.assert_array_equal(corrected2["Vlsr"], [1.0, 2.0])
        np.testing.assert_array_equal(corrected2["LCP"], [-9.0, -10.0])
        np.testing.assert_array_equal(corrected2["RCP"], [-3.0, -4.0])

    def test_output_arrays_are_aligned(self, offset_grid_pair):
        corrected1, corrected2 = freq_switch_correct(*offset_grid_pair)
        for corrected in (corrected1, corrected2):
            assert len(corrected["Vlsr"]) == len(corrected["LCP"]) == len(corrected["RCP"])

    def test_does_not_mutate_inputs(self, offset_grid_pair):
        spec1, spec2 = offset_grid_pair
        before = {
            "spec1_vlsr": spec1["Vlsr"].copy(),
            "spec1_lcp": spec1["LCP"].copy(),
            "spec2_rcp": spec2["RCP"].copy(),
        }
        freq_switch_correct(spec1, spec2)
        np.testing.assert_array_equal(spec1["Vlsr"], before["spec1_vlsr"])
        np.testing.assert_array_equal(spec1["LCP"], before["spec1_lcp"])
        np.testing.assert_array_equal(spec2["RCP"], before["spec2_rcp"])

    def test_missing_required_field_raises(self, identical_grid_pair):
        spec1, spec2 = identical_grid_pair
        invalid = {key: value for key, value in spec1.items() if key != "RCP"}
        with pytest.raises(ValueError, match="missing required field"):
            freq_switch_correct(invalid, spec2)

    def test_inconsistent_internal_array_lengths_raise(self, identical_grid_pair):
        _spec1, spec2 = identical_grid_pair
        invalid = {
            "Vlsr": np.array([0.0, 1.0, 2.0]),
            "LCP": np.array([1.0, 2.0]),
            "RCP": np.array([1.0, 2.0, 3.0]),
        }
        with pytest.raises(ValueError, match="inconsistent array lengths"):
            freq_switch_correct(invalid, spec2)

    def test_different_channel_counts_raise(self):
        spec1 = {"Vlsr": np.array([0.0, 1.0, 2.0]), "LCP": np.array([1., 2., 3.]), "RCP": np.array([1., 2., 3.])}
        spec2 = {"Vlsr": np.array([0.0, 1.0]), "LCP": np.array([1., 2.]), "RCP": np.array([1., 2.])}
        with pytest.raises(ValueError, match="different LCP channel counts"):
            freq_switch_correct(spec1, spec2)


class TestPosSwitchCorrect:
    def test_subtracts_lcp_and_rcp_elementwise(self, identical_grid_pair):
        corrected = pos_switch_correct(*identical_grid_pair)
        np.testing.assert_array_equal(corrected["LCP"], [9.0, 10.0, 11.0])
        np.testing.assert_array_equal(corrected["RCP"], [3.0, 4.0, 5.0])

    def test_preserves_first_spectrum_velocity_grid_and_metadata(self, identical_grid_pair):
        spec1, spec2 = identical_grid_pair
        spec1["source_metadata"] = "keep-me"
        corrected = pos_switch_correct(spec1, spec2)
        np.testing.assert_array_equal(corrected["Vlsr"], spec1["Vlsr"])
        assert corrected["source_metadata"] == "keep-me"

    def test_does_not_mutate_inputs(self, identical_grid_pair):
        spec1, spec2 = identical_grid_pair
        before_lcp = spec1["LCP"].copy()
        pos_switch_correct(spec1, spec2)
        np.testing.assert_array_equal(spec1["LCP"], before_lcp)

    def test_different_channel_counts_raise(self):
        spec1 = {"Vlsr": np.array([0., 1., 2.]), "LCP": np.array([1., 2., 3.]), "RCP": np.array([1., 2., 3.])}
        spec2 = {"Vlsr": np.array([0., 1.]), "LCP": np.array([1., 2.]), "RCP": np.array([1., 2.])}
        with pytest.raises(ValueError, match="different LCP channel counts"):
            pos_switch_correct(spec1, spec2)


class TestBuildBandpassResult:
    @pytest.mark.parametrize("mode", MODE_OPTIONS)
    def test_returns_valid_corrected_spectrum_for_each_mode(self, mode, identical_grid_pair):
        pair = make_pair(identical_grid_pair)
        result = build_bandpass_result(mode, pair)
        corrected = result["corrected"]
        assert corrected["Vlsr"].size > 0
        assert corrected["Vlsr"].size == corrected["LCP"].size == corrected["RCP"].size
        assert result["mode"] == mode

    def test_position_switch_values_and_metadata(self, identical_grid_pair):
        pair = make_pair(identical_grid_pair, positions=("ON", "OFF"), filenames=("on.fits", "off.fits"))
        result = build_bandpass_result("Position Switch", pair)
        np.testing.assert_array_equal(result["corrected"]["LCP"], [9.0, 10.0, 11.0])
        np.testing.assert_array_equal(result["corrected"]["RCP"], [3.0, 4.0, 5.0])
        assert result["filename1"] == "on.fits"
        assert result["filename2"] == "off.fits"
        assert result["position1"] == "ON"
        assert result["position2"] == "OFF"

    def test_repeated_builds_produce_identical_corrected_arrays(self, identical_grid_pair):
        pair = make_pair(identical_grid_pair)
        first = build_bandpass_result("Position Switch", pair)["corrected"]
        second = build_bandpass_result("Position Switch", pair)["corrected"]
        for key in ("Vlsr", "LCP", "RCP"):
            np.testing.assert_array_equal(first[key], second[key])

    def test_frequency_switch_keeps_first_corrected_spectrum(self, offset_grid_pair):
        result = build_bandpass_result("Frequency Switch", make_pair(offset_grid_pair))
        np.testing.assert_array_equal(result["corrected"]["Vlsr"], [1.0, 2.0])
        np.testing.assert_array_equal(result["corrected"]["LCP"], [10.0, 11.0])
        np.testing.assert_array_equal(result["corrected"]["RCP"], [4.0, 5.0])

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown bandpass mode"):
            build_bandpass_result("Not A Mode", None)

    def test_frequency_switch_with_no_common_channels_raises(self):
        spec1 = {"Vlsr": np.array([0., 1.]), "LCP": np.array([4., 5.]), "RCP": np.array([6., 7.])}
        spec2 = {"Vlsr": np.array([2., 3.]), "LCP": np.array([1., 2.]), "RCP": np.array([1., 2.])}
        with pytest.raises(ValueError, match="no common velocity channels"):
            build_bandpass_result("Frequency Switch", make_pair((spec1, spec2)))


class TestPairingAndModeSuggestion:
    def test_pairs_full_integrations_and_orders_on_before_off(self, identical_grid_pair):
        spec1, spec2 = identical_grid_pair
        entries = [
            make_entry("off.fits", spec2, position="OFF"),
            make_entry("not-full.fits", spec1, position="ON", pointing=1),
            make_entry("on.fits", spec1, position="ON"),
            make_entry("extra.fits", spec2, position="OFF"),
        ]
        pairs = get_full_integration_pairs(entries)
        assert len(pairs) == 1
        assert pairs[0][0]["filename"] == "on.fits"
        assert pairs[0][1]["filename"] == "off.fits"

    def test_pairs_are_kept_separate_by_observation_directory(self, identical_grid_pair):
        spec1, spec2 = identical_grid_pair
        entries = [
            make_entry("a-on.fits", spec1, position="ON", observation_dir="obs-A"),
            make_entry("a-off.fits", spec2, position="OFF", observation_dir="obs-A"),
            make_entry("b-on.fits", spec1, position="ON", observation_dir="obs-B"),
            make_entry("b-off.fits", spec2, position="OFF", observation_dir="obs-B"),
        ]
        pairs = get_full_integration_pairs(entries)
        assert len(pairs) == 2
        assert [(pair[0]["filename"], pair[1]["filename"]) for pair in pairs] == [
            ("a-on.fits", "a-off.fits"),
            ("b-on.fits", "b-off.fits"),
        ]

    @pytest.mark.parametrize(
        ("second_position", "expected_mode"),
        [("ON", "Frequency Switch"), ("OFF", "Position Switch"), ("UNKNOWN", None), ("", None)],
    )
    def test_suggest_mode_uses_second_position_metadata(self, identical_grid_pair, second_position, expected_mode):
        pair = make_pair(identical_grid_pair, positions=("ON", second_position))
        mode, _reason = suggest_mode(pair)
        assert mode == expected_mode


class TestCommonVelocityRange:
    def test_returns_extent_of_exactly_shared_channels(self, offset_grid_pair):
        assert common_velocity_range(*offset_grid_pair) == [1.0, 2.0]

    def test_returns_empty_for_disjoint_velocity_extents(self):
        spec1 = {"Vlsr": np.array([0., 1.]), "LCP": np.array([1., 2.]), "RCP": np.array([1., 2.])}
        spec2 = {"Vlsr": np.array([2., 3.]), "LCP": np.array([1., 2.]), "RCP": np.array([1., 2.])}
        assert common_velocity_range(spec1, spec2) == []


class TestStageSummary:
    def test_summary_fields(self, identical_grid_pair):
        result = build_bandpass_result("Position Switch", make_pair(identical_grid_pair))
        summary = stage_summary("Position Switch", result["corrected"])
        assert summary == {
            "mode": "Position Switch",
            "n_channels": 3,
            "vlsr_range_kms": [0.0, 2.0],
        }

    def test_empty_spectrum_gives_empty_range(self):
        empty = {"Vlsr": np.array([]), "LCP": np.array([]), "RCP": np.array([])}
        assert stage_summary("Position Switch", empty) == {
            "mode": "Position Switch",
            "n_channels": 0,
            "vlsr_range_kms": [],
        }
