# test_fitting_inputs.py — FR-14–17: tests for utils/fitting_inputs.py (the owner-specified graph arithmetic).

import numpy as np
import pytest

from utils import fitting_inputs as fi


def _pipeline(lcp=2.0, rcp=4.0, factor=1.1):
    return {
        "05_calibration_dashboard": {"pss": {"lcp_window_mean": lcp, "rcp_window_mean": rcp, "frequency": "66685",
                                             "window_days": 15}},
        "06_pointing_correction": {"correction_factor": factor, "input_source": "pointing scan: x"},
    }


def test_pair_average_and_overall_mean():
    average, overall = fi.pair_average([1.0, 3.0, 5.0], [3.0, 5.0, 7.0])
    assert list(average) == [2.0, 4.0, 6.0]
    assert overall == 4.0


def test_pair_average_ignores_nan_channels_and_handles_all_nan():
    _, overall = fi.pair_average([1.0, np.nan], [3.0, np.nan])
    assert overall == 2.0
    assert np.isnan(fi.pair_average([np.nan], [np.nan])[1])


def test_graph3_is_exactly_the_owner_formula():
    lcp, rcp = np.array([1.0, 2.0]), np.array([3.0, 4.0])
    # [(LCP + RCP) * PSS] + Pointing Correction  -- note the "+"
    assert list(fi.graph3(lcp, rcp, pss=2.0, pointing_correction=1.5)) == [(1 + 3) * 2.0 + 1.5, (2 + 4) * 2.0 + 1.5]


def test_pointing_product_is_multiplicative():
    assert list(fi.pointing_product([1.0, 2.0], [3.0, 4.0], 1.5)) == [6.0, 9.0]


def test_pss_is_mean_of_lcp_and_rcp_window_means():
    pss = fi.pss_from_pipeline(_pipeline(lcp=2.0, rcp=4.0))
    assert pss.value == 3.0 and pss.lcp_mean == 2.0 and pss.rcp_mean == 4.0 and pss.frequency == "66685"


@pytest.mark.parametrize("data", [None, {}, {"05_calibration_dashboard": {}},
                                  {"05_calibration_dashboard": {"pss": {"lcp_window_mean": 2.0,
                                                                        "rcp_window_mean": None}}},
                                  {"05_calibration_dashboard": {"pss": {"lcp_window_mean": "x",
                                                                        "rcp_window_mean": 1.0}}}])
def test_pss_missing_or_unusable_is_none(data):
    assert fi.pss_from_pipeline(data) is None


def test_pointing_factor_real_vs_mock_vs_missing():
    assert fi.pointing_factor_from_pipeline(_pipeline(factor=1.25)) == 1.25
    mock = {"06_pointing_correction": {"correction_factor": 1.2, "input_source": "MOCK -- no real scan extraction yet"}}
    assert fi.pointing_factor_from_pipeline(mock) is None
    legacy = {"06_pointing_correction": {"Pointing correction factor": "1.0123"}}  # old display-string schema
    assert fi.pointing_factor_from_pipeline(legacy) is None
    assert fi.pointing_factor_from_pipeline(None) is None


def test_graph3_source_key_changes_with_every_input():
    base = fi.graph3_source_key("baseline", 3.0, 1.1)
    assert base != fi.graph3_source_key("raw", 3.0, 1.1)
    assert base != fi.graph3_source_key("baseline", 3.1, 1.1)
    assert base != fi.graph3_source_key("baseline", 3.0, 1.2)
