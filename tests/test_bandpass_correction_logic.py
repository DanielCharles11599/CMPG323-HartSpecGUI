# test_bandpass_correction_logic.py — unit tests for
# utils/bandpass_correction_logic.py (FR-04 Bandpass Correction). Pure-Python/
# NumPy logic only, so these run without a Streamlit runtime, per pytest>=7.4
# (see requirements.txt).
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hartspec_gui"))

from hartspec_gui.utils.bandpass_correction_logic import (  # noqa: E402
    MODE_OPTIONS,
    freq_switch_correct,
    get_corrected_spectrum,
    get_placeholder_raw_pair,
    pos_switch_correct,
    stage_summary,
)


class TestGetPlaceholderRawPair:
    def test_frequency_switch_grids_are_offset_but_overlap(self):
        spec1, spec2 = get_placeholder_raw_pair("Frequency Switch")
        assert spec1["Vlsr"].size == spec2["Vlsr"].size
        common = np.intersect1d(spec1["Vlsr"], spec2["Vlsr"])
        assert 0 < common.size < spec1["Vlsr"].size

    def test_position_switch_grids_are_identical(self):
        spec1, spec2 = get_placeholder_raw_pair("Position Switch")
        np.testing.assert_array_equal(spec1["Vlsr"], spec2["Vlsr"])

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError):
            get_placeholder_raw_pair("Not A Mode")

    def test_deterministic_across_calls(self):
        spec1a, spec2a = get_placeholder_raw_pair("Frequency Switch")
        spec1b, spec2b = get_placeholder_raw_pair("Frequency Switch")
        np.testing.assert_array_equal(spec1a["LCP"], spec1b["LCP"])
        np.testing.assert_array_equal(spec2a["RCP"], spec2b["RCP"])

    def test_reference_throw_has_no_synthetic_line(self):
        # amplitude_scale=0.0 for spec2 in Frequency Switch / off-source in
        # Position Switch -- its LCP/RCP should hover around the flat
        # baseline (45.0 / 44.6) with no ~2.4K Gaussian bump riding on top.
        _, spec2 = get_placeholder_raw_pair("Frequency Switch")
        assert spec2["LCP"].max() < 45.5


class TestFreqSwitchCorrect:
    def test_matches_manual_subtraction_on_simple_arrays(self):
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
        new_spec1, new_spec2 = freq_switch_correct(spec1, spec2)

        # spec1_common = positions [1, 2] of spec1 (Vlsr values 1, 2 also in spec2)
        np.testing.assert_array_equal(new_spec1["Vlsr"], [1.0, 2.0])
        np.testing.assert_array_equal(new_spec1["LCP"], [10.0, 11.0])  # (11-1), (12-1)
        np.testing.assert_array_equal(new_spec1["RCP"], [4.0, 5.0])  # (6-2), (7-2)

        # spec2_common = positions [0, 1] of spec2 (Vlsr values 1, 2 also in spec1)
        np.testing.assert_array_equal(new_spec2["Vlsr"], [1.0, 2.0])
        np.testing.assert_array_equal(new_spec2["LCP"], [-9.0, -10.0])  # (1-10), (1-11)
        np.testing.assert_array_equal(new_spec2["RCP"], [-3.0, -4.0])  # (2-5), (2-6)

    def test_output_restricted_to_common_vlsr_only(self):
        spec1, spec2 = get_placeholder_raw_pair("Frequency Switch")
        new_spec1, new_spec2 = freq_switch_correct(spec1, spec2)

        assert new_spec1["Vlsr"].size < spec1["Vlsr"].size
        assert new_spec2["Vlsr"].size < spec2["Vlsr"].size
        assert set(np.round(new_spec1["Vlsr"], 6)) == set(np.round(new_spec2["Vlsr"], 6))

    def test_output_arrays_stay_aligned_with_their_own_vlsr(self):
        spec1, spec2 = get_placeholder_raw_pair("Frequency Switch")
        new_spec1, new_spec2 = freq_switch_correct(spec1, spec2)

        assert new_spec1["LCP"].size == new_spec1["Vlsr"].size == new_spec1["RCP"].size
        assert new_spec2["LCP"].size == new_spec2["Vlsr"].size == new_spec2["RCP"].size

    def test_does_not_mutate_inputs(self):
        spec1, spec2 = get_placeholder_raw_pair("Frequency Switch")
        spec1_vlsr_before = spec1["Vlsr"].copy()
        freq_switch_correct(spec1, spec2)
        np.testing.assert_array_equal(spec1["Vlsr"], spec1_vlsr_before)


class TestPosSwitchCorrect:
    def test_elementwise_subtraction_no_intersection_needed(self):
        spec1 = {"Vlsr": np.array([0.0, 1.0]), "LCP": np.array([10.0, 20.0]), "RCP": np.array([5.0, 6.0])}
        spec2 = {"Vlsr": np.array([0.0, 1.0]), "LCP": np.array([1.0, 2.0]), "RCP": np.array([1.0, 1.0])}

        result = pos_switch_correct(spec1, spec2)

        np.testing.assert_array_equal(result["LCP"], [9.0, 18.0])
        np.testing.assert_array_equal(result["RCP"], [4.0, 5.0])
        np.testing.assert_array_equal(result["Vlsr"], spec1["Vlsr"])

    def test_preserves_vlsr_grid_length(self):
        spec1, spec2 = get_placeholder_raw_pair("Position Switch")
        result = pos_switch_correct(spec1, spec2)
        assert result["Vlsr"].size == spec1["Vlsr"].size


class TestGetCorrectedSpectrum:
    @pytest.mark.parametrize("mode", MODE_OPTIONS)
    def test_returns_nonempty_spectrum_for_every_mode(self, mode):
        corrected = get_corrected_spectrum(mode)
        assert corrected["Vlsr"].size > 0
        assert corrected["LCP"].size == corrected["Vlsr"].size
        assert corrected["RCP"].size == corrected["Vlsr"].size

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError):
            get_corrected_spectrum("Not A Mode")


class TestStageSummary:
    def test_summary_fields(self):
        corrected = get_corrected_spectrum("Position Switch")
        summary = stage_summary("Position Switch", corrected)

        assert summary["mode"] == "Position Switch"
        assert summary["n_channels"] == corrected["Vlsr"].size
        assert summary["vlsr_range_kms"][0] <= summary["vlsr_range_kms"][1]

    def test_empty_spectrum_gives_empty_range(self):
        empty = {"Vlsr": np.array([]), "LCP": np.array([]), "RCP": np.array([])}
        summary = stage_summary("Position Switch", empty)
        assert summary["vlsr_range_kms"] == []
        assert summary["n_channels"] == 0
