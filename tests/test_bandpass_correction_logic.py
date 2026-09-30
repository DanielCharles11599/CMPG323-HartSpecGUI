# test_bandpass_correction_logic.py
#
# Unit tests for:
#
#     hartspec_gui/utils/bandpass_correction_logic.py
#
# These tests deliberately inject spectra directly into the logic functions.
#
# This means pytest does NOT need to run through `streamlit run`, and the
# scientific correction logic can be tested independently of Streamlit's
# session-state runtime.


from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Import setup
# ---------------------------------------------------------------------------

# Add the repository root to sys.path so Python can import:
#
#     hartspec_gui.utils.bandpass_correction_logic
#
# tests/
#   test_bandpass_correction_logic.py
#
# parents[1] == CMPG323-HartSpecGUI/
sys.path.insert(
    0,
    str(
        Path(__file__)
        .resolve()
        .parents[1]
    ),
)


from hartspec_gui.utils.bandpass_correction_logic import (  # noqa: E402
    MODE_OPTIONS,
    freq_switch_correct,
    get_corrected_spectrum,
    get_raw_pair,
    pos_switch_correct,
    stage_summary,
)


# ---------------------------------------------------------------------------
# Shared spectrum fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def identical_grid_pair():
    """Return two spectra sharing exactly the same Vlsr grid.

    This pair is particularly useful for position-switch testing because
    position switching performs direct element-wise subtraction without
    restricting the velocity range.
    """

    spec1 = {
        "Vlsr": np.array(
            [0.0, 1.0, 2.0]
        ),
        "LCP": np.array(
            [10.0, 11.0, 12.0]
        ),
        "RCP": np.array(
            [5.0, 6.0, 7.0]
        ),
    }

    spec2 = {
        "Vlsr": np.array(
            [0.0, 1.0, 2.0]
        ),
        "LCP": np.array(
            [1.0, 1.0, 1.0]
        ),
        "RCP": np.array(
            [2.0, 2.0, 2.0]
        ),
    }

    return spec1, spec2


@pytest.fixture
def offset_grid_pair():
    """Return a frequency-switch style pair with overlapping Vlsr grids."""

    spec1 = {
        "Vlsr": np.array(
            [0.0, 1.0, 2.0]
        ),
        "LCP": np.array(
            [10.0, 11.0, 12.0]
        ),
        "RCP": np.array(
            [5.0, 6.0, 7.0]
        ),
    }

    spec2 = {
        "Vlsr": np.array(
            [1.0, 2.0, 3.0]
        ),
        "LCP": np.array(
            [1.0, 1.0, 1.0]
        ),
        "RCP": np.array(
            [2.0, 2.0, 2.0]
        ),
    }

    return spec1, spec2


@pytest.fixture
def loaded_pair(
    identical_grid_pair,
):
    """Return a Page-02-style list containing two valid spectra."""

    spec1, spec2 = identical_grid_pair

    return [
        spec1,
        spec2,
    ]


# ---------------------------------------------------------------------------
# get_raw_pair()
# ---------------------------------------------------------------------------

class TestGetRawPair:
    """Tests for Page 02 -> Page 03 spectrum-pair validation."""

    def test_returns_two_loaded_spectra(
        self,
        loaded_pair,
    ):
        expected1, expected2 = loaded_pair

        spec1, spec2 = get_raw_pair(
            loaded_pair,
        )

        assert spec1 is expected1
        assert spec2 is expected2

    def test_empty_pair_raises(self):
        with pytest.raises(
            ValueError,
            match="requires two",
        ):
            get_raw_pair(
                [],
            )

    def test_only_one_spectrum_raises(self):
        only_one = [
            {
                "Vlsr": np.array([0.0]),
                "LCP": np.array([1.0]),
                "RCP": np.array([1.0]),
            }
        ]

        with pytest.raises(
            ValueError,
            match="requires two",
        ):
            get_raw_pair(
                only_one,
            )

    def test_missing_required_key_raises(self):
        spec1 = {
            "Vlsr": np.array(
                [0.0, 1.0]
            ),
            "LCP": np.array(
                [1.0, 2.0]
            ),

            # RCP intentionally omitted.
        }

        spec2 = {
            "Vlsr": np.array(
                [0.0, 1.0]
            ),
            "LCP": np.array(
                [1.0, 2.0]
            ),
            "RCP": np.array(
                [1.0, 2.0]
            ),
        }

        with pytest.raises(
            ValueError,
            match="missing required field",
        ):
            get_raw_pair(
                [spec1, spec2],
            )

    def test_inconsistent_internal_array_lengths_raise(
        self,
    ):
        spec1 = {
            "Vlsr": np.array(
                [0.0, 1.0, 2.0]
            ),
            "LCP": np.array(
                [1.0, 2.0]
            ),
            "RCP": np.array(
                [1.0, 2.0, 3.0]
            ),
        }

        spec2 = {
            "Vlsr": np.array(
                [0.0, 1.0, 2.0]
            ),
            "LCP": np.array(
                [1.0, 2.0, 3.0]
            ),
            "RCP": np.array(
                [1.0, 2.0, 3.0]
            ),
        }

        with pytest.raises(
            ValueError,
            match="inconsistent array lengths",
        ):
            get_raw_pair(
                [spec1, spec2],
            )


# ---------------------------------------------------------------------------
# freq_switch_correct()
# ---------------------------------------------------------------------------

class TestFreqSwitchCorrect:
    """Tests reproducing clc/Baseline.py frequency-switch behaviour."""

    def test_manual_subtraction_and_common_velocity_filter(
        self,
        offset_grid_pair,
    ):
        spec1, spec2 = offset_grid_pair

        new_spec1, new_spec2 = freq_switch_correct(
            spec1,
            spec2,
        )

        # Common Vlsr values are 1 and 2.
        np.testing.assert_array_equal(
            new_spec1["Vlsr"],
            [1.0, 2.0],
        )

        np.testing.assert_array_equal(
            new_spec2["Vlsr"],
            [1.0, 2.0],
        )

        # Full subtraction first:
        #
        # spec1 LCP - spec2 LCP
        # [10,11,12] - [1,1,1]
        # = [9,10,11]
        #
        # spec1 common positions are indices 1 and 2.
        np.testing.assert_array_equal(
            new_spec1["LCP"],
            [10.0, 11.0],
        )

        np.testing.assert_array_equal(
            new_spec1["RCP"],
            [4.0, 5.0],
        )

        # Reverse subtraction:
        #
        # [1,1,1] - [10,11,12]
        # = [-9,-10,-11]
        #
        # spec2 common positions are indices 0 and 1.
        np.testing.assert_array_equal(
            new_spec2["LCP"],
            [-9.0, -10.0],
        )

        np.testing.assert_array_equal(
            new_spec2["RCP"],
            [-3.0, -4.0],
        )

    def test_only_common_velocity_channels_are_kept(
        self,
        offset_grid_pair,
    ):
        spec1, spec2 = offset_grid_pair

        new_spec1, new_spec2 = freq_switch_correct(
            spec1,
            spec2,
        )

        assert len(
            new_spec1["Vlsr"]
        ) < len(
            spec1["Vlsr"]
        )

        assert len(
            new_spec2["Vlsr"]
        ) < len(
            spec2["Vlsr"]
        )

        assert set(
            new_spec1["Vlsr"]
        ) == set(
            new_spec2["Vlsr"]
        )

    def test_output_arrays_remain_aligned(
        self,
        offset_grid_pair,
    ):
        spec1, spec2 = offset_grid_pair

        new_spec1, new_spec2 = freq_switch_correct(
            spec1,
            spec2,
        )

        assert (
            len(new_spec1["Vlsr"])
            == len(new_spec1["LCP"])
            == len(new_spec1["RCP"])
        )

        assert (
            len(new_spec2["Vlsr"])
            == len(new_spec2["LCP"])
            == len(new_spec2["RCP"])
        )

    def test_does_not_mutate_input_spectra(
        self,
        offset_grid_pair,
    ):
        spec1, spec2 = offset_grid_pair

        spec1_vlsr_before = (
            spec1["Vlsr"].copy()
        )

        spec1_lcp_before = (
            spec1["LCP"].copy()
        )

        spec2_rcp_before = (
            spec2["RCP"].copy()
        )

        freq_switch_correct(
            spec1,
            spec2,
        )

        np.testing.assert_array_equal(
            spec1["Vlsr"],
            spec1_vlsr_before,
        )

        np.testing.assert_array_equal(
            spec1["LCP"],
            spec1_lcp_before,
        )

        np.testing.assert_array_equal(
            spec2["RCP"],
            spec2_rcp_before,
        )

    def test_different_channel_counts_raise(self):
        spec1 = {
            "Vlsr": np.array(
                [0.0, 1.0, 2.0]
            ),
            "LCP": np.array(
                [10.0, 11.0, 12.0]
            ),
            "RCP": np.array(
                [5.0, 6.0, 7.0]
            ),
        }

        spec2 = {
            "Vlsr": np.array(
                [0.0, 1.0]
            ),
            "LCP": np.array(
                [1.0, 1.0]
            ),
            "RCP": np.array(
                [2.0, 2.0]
            ),
        }

        with pytest.raises(
            ValueError,
            match="different LCP channel counts",
        ):
            freq_switch_correct(
                spec1,
                spec2,
            )


# ---------------------------------------------------------------------------
# pos_switch_correct()
# ---------------------------------------------------------------------------

class TestPosSwitchCorrect:
    """Tests reproducing clc/Baseline.py position-switch behaviour."""

    def test_elementwise_subtraction(
        self,
        identical_grid_pair,
    ):
        spec1, spec2 = identical_grid_pair

        result = pos_switch_correct(
            spec1,
            spec2,
        )

        np.testing.assert_array_equal(
            result["LCP"],
            [9.0, 10.0, 11.0],
        )

        np.testing.assert_array_equal(
            result["RCP"],
            [3.0, 4.0, 5.0],
        )

    def test_preserves_spec1_velocity_grid(
        self,
        identical_grid_pair,
    ):
        spec1, spec2 = identical_grid_pair

        result = pos_switch_correct(
            spec1,
            spec2,
        )

        np.testing.assert_array_equal(
            result["Vlsr"],
            spec1["Vlsr"],
        )

    def test_does_not_mutate_input(
        self,
        identical_grid_pair,
    ):
        spec1, spec2 = identical_grid_pair

        before = (
            spec1["LCP"].copy()
        )

        pos_switch_correct(
            spec1,
            spec2,
        )

        np.testing.assert_array_equal(
            spec1["LCP"],
            before,
        )

    def test_different_channel_counts_raise(self):
        spec1 = {
            "Vlsr": np.array(
                [0.0, 1.0, 2.0]
            ),
            "LCP": np.array(
                [10.0, 11.0, 12.0]
            ),
            "RCP": np.array(
                [5.0, 6.0, 7.0]
            ),
        }

        spec2 = {
            "Vlsr": np.array(
                [0.0, 1.0]
            ),
            "LCP": np.array(
                [1.0, 1.0]
            ),
            "RCP": np.array(
                [2.0, 2.0]
            ),
        }

        with pytest.raises(
            ValueError,
            match="different LCP channel counts",
        ):
            pos_switch_correct(
                spec1,
                spec2,
            )


# ---------------------------------------------------------------------------
# get_corrected_spectrum()
# ---------------------------------------------------------------------------

class TestGetCorrectedSpectrum:
    """Tests for the public Page 03 correction entry point."""

    @pytest.mark.parametrize(
        "mode",
        MODE_OPTIONS,
    )
    def test_returns_valid_spectrum_for_each_mode(
        self,
        mode,
        loaded_pair,
    ):
        corrected = get_corrected_spectrum(
            mode,
            loaded_pair,
        )

        assert (
            corrected["Vlsr"].size
            > 0
        )

        assert (
            corrected["Vlsr"].size
            == corrected["LCP"].size
            == corrected["RCP"].size
        )

    def test_position_switch_values(
        self,
        loaded_pair,
    ):
        corrected = get_corrected_spectrum(
            "Position Switch",
            loaded_pair,
        )

        np.testing.assert_array_equal(
            corrected["LCP"],
            [9.0, 10.0, 11.0],
        )

        np.testing.assert_array_equal(
            corrected["RCP"],
            [3.0, 4.0, 5.0],
        )

    def test_frequency_switch_values_on_identical_grid(
        self,
        loaded_pair,
    ):
        # When both spectra share exactly the same Vlsr grid, frequency
        # switching keeps every channel. Therefore the displayed new_spec1
        # values are numerically identical to the position-switch subtraction.
        #
        # This is expected behaviour and explains why the two Page 03 graphs
        # can look identical for certain test data.
        corrected = get_corrected_spectrum(
            "Frequency Switch",
            loaded_pair,
        )

        np.testing.assert_array_equal(
            corrected["LCP"],
            [9.0, 10.0, 11.0],
        )

        np.testing.assert_array_equal(
            corrected["RCP"],
            [3.0, 4.0, 5.0],
        )

    def test_unknown_mode_raises_before_loading_pair(
        self,
    ):
        with pytest.raises(
            ValueError,
            match="Unknown bandpass mode",
        ):
            get_corrected_spectrum(
                "Not A Mode",
                [],
            )


# ---------------------------------------------------------------------------
# stage_summary()
# ---------------------------------------------------------------------------

class TestStageSummary:
    """Tests for the lightweight pipeline/session summary."""

    def test_summary_fields(
        self,
        loaded_pair,
    ):
        corrected = get_corrected_spectrum(
            "Position Switch",
            loaded_pair,
        )

        summary = stage_summary(
            "Position Switch",
            corrected,
        )

        assert (
            summary["mode"]
            == "Position Switch"
        )

        assert (
            summary["n_channels"]
            == 3
        )

        assert (
            summary["vlsr_range_kms"]
            == [0.0, 2.0]
        )

    def test_empty_spectrum_gives_empty_range(
        self,
    ):
        empty = {
            "Vlsr": np.array([]),
            "LCP": np.array([]),
            "RCP": np.array([]),
        }

        summary = stage_summary(
            "Position Switch",
            empty,
        )

        assert (
            summary["mode"]
            == "Position Switch"
        )

        assert (
            summary["n_channels"]
            == 0
        )

        assert (
            summary["vlsr_range_kms"]
            == []
        )
        