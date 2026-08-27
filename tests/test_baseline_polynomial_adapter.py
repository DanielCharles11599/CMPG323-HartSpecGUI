# test_baseline_polynomial_adapter.py — CLC-alignment tests for Page 4 polynomial math.

import numpy as np

from utils.baseline_polynomial_adapter import (
    build_clc_masks,
    fit_polynomial_comparison,
    flatten_spectrum_for_orders,
)


def _spectrum() -> dict[str, np.ndarray]:
    vlsr = np.linspace(-15.0, 15.0, 121)
    lcp = 2.0 + 0.15 * vlsr + 0.01 * vlsr**2 + 0.0005 * vlsr**3
    rcp = 1.5 - 0.08 * vlsr + 0.006 * vlsr**2 - 0.0002 * vlsr**3
    # Add a line feature outside the two baseline blocks so it is not used by
    # the polynomial fit, matching the intended Blocks.py workflow.
    line = 3.0 * np.exp(-0.5 * (vlsr / 1.0) ** 2)
    return {"Vlsr": vlsr, "LCP": lcp + line, "RCP": rcp + 0.8 * line}


def test_mask_semantics_match_blocks_py_zero_inside_selected_blocks() -> None:
    spectrum = _spectrum()
    blocks = [{"start": -12.0, "end": -5.0}, {"start": 5.0, "end": 12.0}]
    mask, mask2, vll, vrl = build_clc_masks(spectrum["Vlsr"], blocks)
    inside = ((spectrum["Vlsr"] >= -12.0) & (spectrum["Vlsr"] <= -5.0)) | (
        (spectrum["Vlsr"] >= 5.0) & (spectrum["Vlsr"] <= 12.0)
    )
    np.testing.assert_array_equal(mask[inside], 0)
    np.testing.assert_array_equal(mask[~inside], 1)
    np.testing.assert_array_equal(mask2, mask)
    assert vll == -12.0
    assert vrl == 12.0


def test_six_panel_fit_matches_blocks_py_polyfit_expression_to_machine_precision() -> None:
    spectrum = _spectrum()
    blocks = [{"start": -12.0, "end": -5.0}, {"start": 5.0, "end": 12.0}]
    result = fit_polynomial_comparison(spectrum, blocks)
    assert result["provider"] == "clc"
    assert len(result["panels"]) == 6

    mask, _, _, _ = build_clc_masks(spectrum["Vlsr"], blocks)
    vel_mask = np.ma.array(spectrum["Vlsr"], mask=mask)
    amp_mask = np.ma.array(spectrum["LCP"], mask=mask)
    expected = np.poly1d(np.ma.polyfit(vel_mask, amp_mask, 4))(spectrum["Vlsr"])
    actual_panel = next(
        panel for panel in result["panels"] if panel["polarization"] == "LCP" and panel["order"] == 4
    )
    np.testing.assert_allclose(actual_panel["fit"], expected, rtol=1e-12, atol=1e-12)


def test_manual_selected_orders_flatten_using_flat_base_subtraction_semantics() -> None:
    spectrum = _spectrum()
    blocks = [{"start": -12.0, "end": -5.0}, {"start": 5.0, "end": 12.0}]
    result = fit_polynomial_comparison(spectrum, blocks)
    selected = {"LCP": 3, "RCP": 4}
    flattened = flatten_spectrum_for_orders(spectrum, result, selected)

    for polarization, order in selected.items():
        panel = next(
            panel
            for panel in result["panels"]
            if panel["polarization"] == polarization and panel["order"] == order
        )
        expected = np.asarray(spectrum[polarization]) - np.asarray(panel["fit"])
        np.testing.assert_allclose(flattened[polarization], expected, rtol=1e-12, atol=1e-12)


def test_stats_manager_chi_s_scores_and_orders_are_reproduced_exactly() -> None:
    """Page 4 must expose the same six scores that Stats_manager.chi_S accumulates."""
    spectrum = _spectrum()
    blocks = [{"start": -12.0, "end": -5.0}, {"start": 5.0, "end": 12.0}]
    result = fit_polynomial_comparison(spectrum, blocks)
    mask, _, vll, vrl = build_clc_masks(spectrum["Vlsr"], blocks)

    # Literal reference accumulation from the supplied Stats_manager.chi_S.
    vl = None
    vr = None
    mask3 = np.ones(len(spectrum["Vlsr"]))
    mask3[np.where(np.logical_and(spectrum["Vlsr"] >= vll, spectrum["Vlsr"] <= vrl))] = 0
    for index in range(0, len(mask) - 1, 1):
        if spectrum["Vlsr"][index] <= vll and spectrum["Vlsr"][index + 1] >= vll:
            vl = index
        if (
            spectrum["Vlsr"][index] <= vrl
            and spectrum["Vlsr"][index + 1] >= vrl
            and vrl < spectrum["Vlsr"][len(mask3) - 1]
        ):
            vr = index
        if spectrum["Vlsr"][len(mask) - 1] < vrl:
            vr = len(mask3) - 2

    assert vl is not None and vr is not None
    reference_scores = {"LCP": {}, "RCP": {}}
    for polarization in ("LCP", "RCP"):
        observed = spectrum[polarization]
        for order in (3, 4, 5):
            panel = next(
                panel
                for panel in result["panels"]
                if panel["polarization"] == polarization and panel["order"] == order
            )
            fitted = np.asarray(panel["fit"])
            score = 0.0
            for index in range(vl, vr, 1):
                if mask[index] == 0:
                    score += ((observed[index] - fitted[index]) ** 2) / fitted[index]
            reference_scores[polarization][order] = float(score)
            assert panel["chi_squared"] == reference_scores[polarization][order]

    expected_orders = {
        polarization: min((3, 4, 5), key=lambda order: abs(reference_scores[polarization][order]))
        for polarization in ("LCP", "RCP")
    }
    assert result["auto_orders"] == expected_orders
