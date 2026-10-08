import numpy as np
from utils.baseline_polynomial_adapter import build_clc_masks, fit_polynomial_comparison, flatten_spectrum_for_orders

def test_flat_regions_are_fitting_inputs_and_peaks_preserved():
    v = np.linspace(-10, 10, 101)
    baseline = 2.0 + .01*v + .002*v**2 + .0001*v**3
    peak = np.where((v > -1) & (v < 1), 5.0, 0.0)
    observed = baseline + peak
    spectrum = {"Vlsr":v,"LCP":observed,"RCP":observed*1.1}
    blocks = [{"start":-9.0,"end":-5.0},{"start":5.0,"end":9.0}]
    mask_l, mask_r, _, _ = build_clc_masks(v,blocks)
    assert np.all(mask_l[(v>=-9)&(v<=-5)] == 0)
    assert np.all(mask_l[(v>-1)&(v<1)] == 1)
    assert np.array_equal(mask_l,mask_r)
    result = fit_polynomial_comparison(spectrum,blocks)
    assert result["baseline_channel_count"] == int(np.sum(mask_l == 0))
    corrected = flatten_spectrum_for_orders(spectrum,result,{"LCP":3,"RCP":3})
    assert len(corrected["Vlsr"]) == len(v)
    assert np.allclose(np.asarray(corrected["LCP"])[(v>-1)&(v<1)],5.0,atol=1e-6)
    assert np.allclose(np.asarray(corrected["RCP"])[(v>-1)&(v<1)],5.5,atol=1e-6)
