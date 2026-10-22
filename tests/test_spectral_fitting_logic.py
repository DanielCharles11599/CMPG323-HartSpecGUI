# test_spectral_fitting_logic.py — unit tests for utils/spectral_fitting_logic.py (FR-14/15/16/17).
#
# Pure numpy/scipy, so these run without a Streamlit runtime. Synthetic spectra use a fixed RNG seed so results
# are reproducible. These fits are standard scipy reproductions, not clc/ output, so the 6-significant-figure
# CLI-regression rule does not apply; instead the tests assert recovery of known injected parameters.

import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import OptimizeWarning

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hartspec_gui"))

from utils import spectral_fitting_logic as slf  # noqa: E402
from utils.spectral_fitting_logic import FIT_TYPES, run_fit  # noqa: E402

V = np.linspace(-20, 20, 1024)  # standard 1024-channel spectrum (project performance target)


def _gauss(x, amp, center, fwhm):
    return amp * np.exp(-0.5 * ((x - center) / (fwhm / 2.3548)) ** 2)


def _value(result, name):
    """Numeric part of a formatted row value, e.g. '8.42 K' -> 8.42."""
    row = next(r for r in result.rows if r[0] == name)
    return float(row[1].split()[0])


def _single_line(seed=1):
    rng = np.random.default_rng(seed)
    return _gauss(V, 8.42, -4.2, 2.31) + rng.normal(0, 0.15, V.size)


def _two_lines(seed, c1=-6.0, c2=3.0, a1=8.0, a2=5.0):
    rng = np.random.default_rng(seed)
    return _gauss(V, a1, c1, 2.0) + _gauss(V, a2, c2, 2.5) + rng.normal(0, 0.15, V.size)


# ---- FR-14: 1D Gaussian ---------------------------------------------------------------------------------
def test_1d_gaussian_recovers_injected_parameters():
    result = run_fit("1D Gaussian", V, _single_line())
    assert result.ok and result.converged and not result.fell_back
    assert abs(_value(result, "Amplitude") - 8.42) < 0.15
    assert abs(_value(result, "Center (Vlsr)") - (-4.2)) < 0.05
    assert abs(_value(result, "FWHM") - 2.31) < 0.15


def test_units_come_from_the_caller_not_hardcoded():
    rows = run_fit("1D Gaussian", V, _single_line() * 10, unit="Jy").rows
    amplitude_row = next(r for r in rows if r[0] == "Amplitude")
    assert amplitude_row[1].endswith(" Jy") and amplitude_row[2].endswith(" Jy")
    assert " K" not in amplitude_row[1]


def test_reported_fwhm_is_positive_even_if_curve_fit_returns_negative(monkeypatch):
    # The model depends only on fwhm**2, so curve_fit may legitimately return -2.3 for a 2.3 km/s line.
    monkeypatch.setattr(
        slf, "curve_fit", lambda *a, **k: (np.array([8.0, 0.0, -2.3, 0.0]), np.eye(4) * 0.01)
    )
    result = run_fit("1D Gaussian", V, _single_line())
    assert _value(result, "FWHM") == 2.30


# ---- FR-15: two-component ("2D Gaussian") ------------------------------------------------------------------
def test_seed_indices_are_separated_not_adjacent_channels_of_one_peak():
    y = _single_line()
    seeds = slf.seed_indices(V, y, 2)
    assert len(seeds) == 2
    assert abs(seeds[0] - seeds[1]) >= len(V) // 20  # the old seeding used the two tallest channels (~0.1 km/s apart)


def test_two_component_recovers_both_lines_of_a_blend():
    # Regression: the old seeding recovered the wrong amplitudes in 195 of 200 blends like these.
    for seed in range(20):
        result = run_fit("2D Gaussian", V, _two_lines(seed))
        assert result.ok and not result.fell_back and result.converged, (seed, result.notes)
        amps = sorted([_value(result, "Amplitude 1"), _value(result, "Amplitude 2")])
        assert abs(amps[0] - 5.0) < 0.5 and abs(amps[1] - 8.0) < 0.5, (seed, amps)
        centers = sorted([_value(result, "Center 1 (Vlsr)"), _value(result, "Center 2 (Vlsr)")])
        assert abs(centers[0] - (-6.0)) < 0.1 and abs(centers[1] - 3.0) < 0.1, (seed, centers)


def test_two_component_falls_back_to_1d_and_says_so(monkeypatch):
    real = slf.curve_fit

    def fake(model, *args, **kwargs):
        if model is slf._double_gaussian:
            raise RuntimeError("maxfev exceeded")
        return real(model, *args, **kwargs)

    monkeypatch.setattr(slf, "curve_fit", fake)
    result = run_fit("2D Gaussian", V, _single_line())
    assert result.ok and result.fell_back
    assert result.fit_type_requested == "2D Gaussian" and result.fit_type_used == "1D Gaussian"
    assert any("did not converge" in n for n in result.notes)
    assert len(result.rows) == 3  # single-Gaussian parameters, and the label no longer pretends otherwise


# ---- FR-16: polynomial ------------------------------------------------------------------------------------------
def test_polynomial_reports_coefficients_peak_and_full_range_note():
    result = run_fit("Polynomial Peak", V, _single_line())
    assert result.ok and result.converged
    assert len(result.rows) == slf.POLYNOMIAL_ORDER + 2  # coefficients + Peak Vlsr
    assert result.rows[-1][0] == "Peak Vlsr"
    assert any("full velocity range" in n for n in result.notes)  # documents current (unconfirmed) behaviour


# ---- FR-17: multi-component ---------------------------------------------------------------------------------------
def test_multi_component_recovers_three_separated_lines():
    rng = np.random.default_rng(11)
    y = _gauss(V, 8, -10, 2) + _gauss(V, 6, 0, 2.4) + _gauss(V, 4, 10, 2.2) + rng.normal(0, 0.12, V.size)
    result = run_fit("Multi-component", V, y)
    assert result.ok and not result.fell_back and len(result.rows) == 3 * slf.MULTI_COMPONENTS
    amps = sorted(_value(result, f"Amplitude {k}") for k in (1, 2, 3))
    assert all(abs(got - want) < 0.5 for got, want in zip(amps, (4, 6, 8))), amps


# ---- failure handling: never raise, never mislabel ---------------------------------------------------------------
def test_total_failure_returns_no_curve_and_a_reason(monkeypatch):
    def always_fail(*args, **kwargs):
        raise RuntimeError("no convergence")

    monkeypatch.setattr(slf, "curve_fit", always_fail)
    for fit_type in ("1D Gaussian", "2D Gaussian", "Multi-component"):
        result = run_fit(fit_type, V, _single_line())
        assert not result.ok and result.curve is None and result.rows == ()
        assert result.notes and "did not converge" in result.notes[0]


def test_constant_spectrum_flags_unconstrained_errors_without_scipy_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = run_fit("1D Gaussian", V, np.full(V.size, 2.0))
    assert not any(issubclass(w.category, OptimizeWarning) for w in caught)
    assert result.ok and not result.converged
    assert all("inf" not in cell for row in result.rows for cell in row)
    assert any("not constrained" in row[2] for row in result.rows)
    assert any("unreliable" in n for n in result.notes)


def test_non_finite_input_is_reported_not_raised():
    y = _single_line()
    y[10] = np.nan
    result = run_fit("1D Gaussian", V, y)
    assert not result.ok and "NaN" in result.notes[0]


def test_too_few_channels_and_length_mismatch_are_reported_not_raised():
    assert not run_fit("Multi-component", V[:5], _single_line()[:5]).ok
    mismatch = run_fit("1D Gaussian", V, _single_line()[:-1])
    assert not mismatch.ok and "lengths differ" in mismatch.notes[0]


def test_unknown_fit_type_is_a_programming_error():
    with pytest.raises(ValueError):
        run_fit("3D Gaussian", V, _single_line())


# ---- performance target: GUI response < 2 s for a 1024-channel spectrum ---------------------------------------
def test_every_fit_type_meets_the_two_second_budget_including_hard_inputs():
    rng = np.random.default_rng(0)
    hard_inputs = [_single_line(), rng.normal(0, 0.15, V.size), _two_lines(3), np.zeros(V.size)]
    for fit_type in FIT_TYPES:
        for y in hard_inputs:
            start = time.perf_counter()
            run_fit(fit_type, V, y)
            assert time.perf_counter() - start < 2.0, fit_type


# ---- FR mapping and aligned-curve contract ------------------------------------------------------------------------
def test_fit_types_follow_the_confirmed_fr_order():
    assert FIT_TYPES == ["1D Gaussian", "Polynomial Peak", "2D Gaussian", "Multi-component"]


def test_scipy_fits_return_curves_aligned_with_the_velocity_axis():
    result = run_fit("1D Gaussian", V, _single_line())
    assert result.curve_x is None and result.curve.shape == V.shape
