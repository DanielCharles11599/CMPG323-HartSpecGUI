import numpy as np

from utils.baseline_polynomial_adapter import (
    build_clc_masks,
    fit_polynomial_comparison,
    flatten_spectrum_for_orders,
)


def test_flat_regions_are_fitting_inputs_and_peaks_preserved():
    vlsr = np.linspace(-10, 10, 101)
    baseline = 2.0 + 0.01 * vlsr + 0.002 * vlsr**2 + 0.0001 * vlsr**3
    peak = np.where((vlsr > -1) & (vlsr < 1), 5.0, 0.0)
    observed = baseline + peak
    spectrum = {"Vlsr": vlsr, "LCP": observed, "RCP": observed * 1.1}
    blocks = [{"start": -9.0, "end": -5.0}, {"start": 5.0, "end": 9.0}]

    mask_lcp, mask_rcp, _, _ = build_clc_masks(vlsr, blocks)
    assert np.all(mask_lcp[(vlsr >= -9) & (vlsr <= -5)] == 0)
    assert np.all(mask_lcp[(vlsr > -1) & (vlsr < 1)] == 1)
    assert np.array_equal(mask_lcp, mask_rcp)

    result = fit_polynomial_comparison(spectrum, blocks)
    assert result["baseline_channel_count"] == int(np.sum(mask_lcp == 0))

    corrected = flatten_spectrum_for_orders(spectrum, result, {"LCP": 3, "RCP": 3})
    assert len(corrected["Vlsr"]) == len(vlsr)
    line_channels = (vlsr > -1) & (vlsr < 1)
    assert np.allclose(np.asarray(corrected["LCP"])[line_channels], 5.0, atol=1e-6)
    assert np.allclose(np.asarray(corrected["RCP"])[line_channels], 5.5, atol=1e-6)
