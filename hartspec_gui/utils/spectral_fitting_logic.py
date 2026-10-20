# spectral_fitting_logic.py — FR-14/15/16/17: pure (Streamlit-free) spectral line fitting for Page 07.
#
# FR mapping (Technical Specs §4.6 / User Stories §3.3): FR-14 1D Gaussian, FR-15 Polynomial Peak, FR-16 2D Gaussian,
# FR-17 Multi-component; FIT_TYPES is in that order (the order of the Page 07 control).
#
# STATUS: Page 07 no longer calls run_fit(). The page now uses the clc/ adapters in utils/fitting_helpers.py
# (run_gaussf / run_fit_max / run_2d_gauss, results returned as FitResult). This module still provides FitResult,
# FIT_TYPES and the scipy reproductions below, which are kept for their tests until the team confirms they can go.
#
# Extracted from 07_Spectral_Fitting.py so the fitting code can be unit-tested (70% coverage target on
# fitting code) without a Streamlit runtime. The model mathematics is unchanged from the page-local
# versions: same Gaussian parameterisation, same scipy.optimize.curve_fit calls, same initial guesses for
# the 1D Gaussian, polynomial and (whenever >= 3 local maxima exist) multi-component fits.
#
# What changed relative to the page-local functions (each is covered by tests/test_spectral_fitting_logic.py):
#   * Two-component ("2D Gaussian") seeding now starts from two DISTINCT peaks. It used to start from the
#     two tallest channels, which are adjacent channels of the same line -- on a well-separated two-line
#     blend that recovered the wrong amplitudes in 195 of 200 simulated spectra (distinct-peak seeding: 0/200).
#   * A fit that fails, or falls back to a simpler model, now says so (FitResult.notes / fit_type_used) instead
#     of silently showing a 1D Gaussian under a "Multi-component" label.
#   * Unconstrained uncertainties are reported as "not constrained" rather than "inf".
#   * Units come from the caller (K before calibration, Jy after) instead of a hardcoded "K".
#   * Reported FWHM is always positive (the model only depends on FWHM squared, so curve_fit may return a
#     negative value that describes the same curve).
#
# No clc/Gaussf.py call is made: its callable signature has not been confirmed (see 07_Spectral_Fitting.py).
# These are standard scipy reproductions, NOT clc output, so the 6-significant-figure CLI-regression rule for
# clc/ numerics does not apply here.
#
# TODO: confirm against design
#   * The "2D Gaussian" two-component 1D fit and the full-range polynomial below are superseded on the page by the
#     spatial clc/2D_Gauss_fit.py fit (FR-16) and clc/fit_max.py window fit (FR-15); see utils/fitting_helpers.py.
#   * FR-17 "Multi-component": number of components is fixed at 3. Confirm the spec's count / selection rule.
#   * All Gaussian fits assume an emission line (positive peak), as for maser spectra; an absorption line is
#     not fitted correctly.
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit
from scipy.signal import find_peaks

FIT_TYPES = ["1D Gaussian", "Polynomial Peak", "2D Gaussian", "Multi-component"]  # FR-14, 15, 16, 17

FWHM_PER_SIGMA = 2.3548  # kept identical to the original page-local constant (exact value is 2.35482...)
POLYNOMIAL_ORDER = 4
MULTI_COMPONENTS = 3

_NOT_CONSTRAINED = "not constrained"


class FitError(ValueError):
    """Input the fitters cannot use (non-finite values, too few channels, mismatched lengths)."""


@dataclass(frozen=True)
class FitResult:
    """Outcome of one fit request.

    ``curve`` is None when no fit could be produced; ``notes`` then says why. ``curve_x`` is None when ``curve``
    is aligned channel-for-channel with the input velocities. ``rows`` are display-ready
    ``(parameter, value, error)`` strings for the fit-parameters table.
    """

    fit_type_requested: str
    fit_type_used: str
    curve: np.ndarray | None
    rows: tuple[tuple[str, str, str], ...]
    notes: tuple[str, ...]
    converged: bool
    curve_x: np.ndarray | None = None  # x of ``curve`` when it is not sampled on the full velocity axis (fit_max.py)

    @property
    def ok(self) -> bool:
        """True when a fit curve was produced."""
        return self.curve is not None

    @property
    def fell_back(self) -> bool:
        """True when a simpler model than the requested one is being shown."""
        return self.ok and self.fit_type_used != self.fit_type_requested


# --------------------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------------------
def _gaussian(x, amp, center, fwhm, offset):
    """Gaussian parameterised by FWHM plus a constant offset."""
    sigma = fwhm / FWHM_PER_SIGMA
    return amp * np.exp(-0.5 * ((x - center) / sigma) ** 2) + offset


def _double_gaussian(x, amp1, c1, fwhm1, amp2, c2, fwhm2, offset):
    """Sum of two Gaussians sharing one offset."""
    return _gaussian(x, amp1, c1, fwhm1, 0.0) + _gaussian(x, amp2, c2, fwhm2, 0.0) + offset


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def _fmt(value: float, unit: str) -> str:
    """Format a value with its unit, e.g. ``8.42 K``."""
    return f"{value:.2f} {unit}"


def _fmt_err(error: float, unit: str) -> str:
    """Format a 1-sigma uncertainty, or say it could not be estimated."""
    return _fmt(error, unit) if np.isfinite(error) else _NOT_CONSTRAINED


def _validated(vlsr, intensity, n_params: int) -> tuple[np.ndarray, np.ndarray]:
    """Return 1-D float arrays, or raise FitError if they cannot be fitted with ``n_params`` parameters."""
    v = np.asarray(vlsr, dtype=float).reshape(-1)
    y = np.asarray(intensity, dtype=float).reshape(-1)
    if v.size != y.size:
        raise FitError(f"Velocity and intensity lengths differ ({v.size} vs {y.size}).")
    if v.size <= n_params:
        raise FitError(f"Only {v.size} channels are available; at least {n_params + 1} are needed for this fit.")
    if not (np.all(np.isfinite(v)) and np.all(np.isfinite(y))):
        raise FitError("The spectrum contains NaN or infinite values.")
    return v, y


def _curve_fit(model: Callable, v: np.ndarray, y: np.ndarray, p0: list[float], maxfev: int):
    """curve_fit with scipy's OptimizeWarning suppressed.

    An un-estimable covariance is detected explicitly (non-finite errors -> ``converged=False`` and a note),
    so the warning would only be noise on the console.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", OptimizeWarning)
        return curve_fit(model, v, y, p0=p0, maxfev=maxfev)


def _greedy_separated(y: np.ndarray, count: int, min_sep: int) -> list[int]:
    """Tallest channels that are at least ``min_sep`` channels apart (fallback when few local maxima exist)."""
    chosen: list[int] = []
    for idx in np.argsort(y)[::-1]:
        if all(abs(int(idx) - c) >= min_sep for c in chosen):
            chosen.append(int(idx))
            if len(chosen) == count:
                break
    return chosen


def seed_indices(v: np.ndarray, y: np.ndarray, count: int) -> list[int]:
    """Channel indices to seed ``count`` Gaussian components from, ordered shortest to tallest.

    That ordering (tallest last) is exactly what the original multi-component code produced, which keeps
    curve_fit's starting point -- and therefore its result -- identical whenever enough local maxima exist.

    Uses the ``count`` tallest local maxima at least ~5 % of the band apart (the rule the multi-component fit
    already used). If fewer local maxima exist it falls back to the tallest channels that are still well
    separated -- never adjacent channels of one peak, which made a two-component fit start from two copies of
    the same line.
    """
    min_sep = max(len(v) // 20, 1)
    peaks, _ = find_peaks(y, distance=min_sep)
    if len(peaks) >= count:
        top = peaks[np.argsort(y[peaks])[-count:]]
        return [int(i) for i in top]
    return _greedy_separated(y, count, min_sep)[::-1]


# --------------------------------------------------------------------------------------
# Fitters -- each returns (curve, rows, converged, notes) or raises RuntimeError/ValueError/LinAlgError
# --------------------------------------------------------------------------------------
def _uncertainty_note(converged: bool) -> tuple[str, ...]:
    if converged:
        return ()
    return ("Parameter uncertainties could not be estimated (singular covariance); "
            "treat these values as unreliable.",)


def _fit_1d(v: np.ndarray, y: np.ndarray, unit: str):
    """FR-14 -- single Gaussian plus offset."""
    p0 = [y.max() - y.min(), v[np.argmax(y)], 4.0, y.min()]
    popt, pcov = _curve_fit(_gaussian, v, y, p0, maxfev=10000)
    perr = np.sqrt(np.diag(pcov))
    converged = bool(np.all(np.isfinite(perr)))
    rows = (
        ("Amplitude", _fmt(popt[0], unit), _fmt_err(perr[0], unit)),
        ("Center (Vlsr)", _fmt(popt[1], "km/s"), _fmt_err(perr[1], "km/s")),
        ("FWHM", _fmt(abs(popt[2]), "km/s"), _fmt_err(perr[2], "km/s")),
    )
    return _gaussian(v, *popt), rows, converged, _uncertainty_note(converged)


def _fit_two_component(v: np.ndarray, y: np.ndarray, unit: str):
    """FR-16 interim (see module TODO) -- two Gaussians on the velocity spectrum plus a shared offset."""
    seeds = seed_indices(v, y, 2)[::-1]  # tallest first: component 1 is the dominant line
    if len(seeds) < 2:
        raise RuntimeError("Could not find two separated peaks to seed a two-component fit.")
    p0 = [y[seeds[0]] - y.min(), v[seeds[0]], 3.0, y[seeds[1]] - y.min(), v[seeds[1]], 3.0, y.min()]
    popt, pcov = _curve_fit(_double_gaussian, v, y, p0, maxfev=20000)
    perr = np.sqrt(np.diag(pcov))
    converged = bool(np.all(np.isfinite(perr)))
    rows = []
    for k in range(2):
        amp, center, fwhm = popt[3 * k: 3 * k + 3]
        e_amp, e_center, e_fwhm = perr[3 * k: 3 * k + 3]
        rows += [
            (f"Amplitude {k + 1}", _fmt(amp, unit), _fmt_err(e_amp, unit)),
            (f"Center {k + 1} (Vlsr)", _fmt(center, "km/s"), _fmt_err(e_center, "km/s")),
            (f"FWHM {k + 1}", _fmt(abs(fwhm), "km/s"), _fmt_err(e_fwhm, "km/s")),
        ]
    return _double_gaussian(v, *popt), tuple(rows), converged, _uncertainty_note(converged)


def _fit_polynomial(v: np.ndarray, y: np.ndarray, unit: str):
    """FR-15 -- polynomial fit; see the module TODO on full-range vs around-the-peak."""
    coeffs = np.polyfit(v, y, POLYNOMIAL_ORDER)
    curve = np.polyval(coeffs, v)
    rows = [(f"Coefficient x^{POLYNOMIAL_ORDER - k}", f"{c:.4g}", "—") for k, c in enumerate(coeffs)]
    rows.append(("Peak Vlsr", _fmt(v[np.argmax(curve)], "km/s"), "—"))
    note = (f"Order-{POLYNOMIAL_ORDER} polynomial fitted over the full velocity range; "
            "the peak is the maximum of that polynomial, not of a window around the line.",)
    return curve, tuple(rows), True, note


def _fit_multi(v: np.ndarray, y: np.ndarray, unit: str):
    """FR-17 -- sum of N Gaussians seeded from the N tallest well-separated local maxima."""
    n = MULTI_COMPONENTS
    top = seed_indices(v, y, n)
    if len(top) < n:
        raise RuntimeError(f"Could not find {n} separated peaks to seed a multi-component fit.")

    def model(x, *p):
        out = np.zeros_like(x) + p[-1]
        for k in range(n):
            amp, c, fwhm = p[3 * k: 3 * k + 3]
            out += _gaussian(x, amp, c, fwhm, 0.0)
        return out

    p0: list[float] = []
    for idx in top:
        p0 += [y[idx] - y.min(), v[idx], 3.0]
    p0.append(y.min())

    popt, pcov = _curve_fit(model, v, y, p0, maxfev=30000)
    perr = np.sqrt(np.diag(pcov))
    converged = bool(np.all(np.isfinite(perr)))
    rows = []
    for k in range(n):
        amp, center, fwhm = popt[3 * k: 3 * k + 3]
        e_amp, e_center, e_fwhm = perr[3 * k: 3 * k + 3]
        rows += [
            (f"Amplitude {k + 1}", _fmt(amp, unit), _fmt_err(e_amp, unit)),
            (f"Center {k + 1} (Vlsr)", _fmt(center, "km/s"), _fmt_err(e_center, "km/s")),
            (f"FWHM {k + 1}", _fmt(abs(fwhm), "km/s"), _fmt_err(e_fwhm, "km/s")),
        ]
    return model(v, *popt), tuple(rows), converged, _uncertainty_note(converged)


_FITTERS: dict[str, tuple[Callable, int]] = {
    # fit type -> (fitter, number of free parameters, used for the minimum-channel check)
    "1D Gaussian": (_fit_1d, 4),
    "2D Gaussian": (_fit_two_component, 7),
    "Polynomial Peak": (_fit_polynomial, POLYNOMIAL_ORDER + 1),
    "Multi-component": (_fit_multi, 3 * MULTI_COMPONENTS + 1),
}
_FAILURES = (RuntimeError, ValueError, np.linalg.LinAlgError)  # curve_fit: maxfev / bad input; polyfit: LinAlgError
_FALLBACK_TO_1D = ("2D Gaussian", "Multi-component")


def _failed(requested: str, reason: str) -> FitResult:
    return FitResult(requested, requested, None, (), (reason,), False)


def run_fit(fit_type: str, vlsr, intensity, unit: str = "K") -> FitResult:
    """Fit ``intensity`` vs ``vlsr`` with the requested model.

    Never raises for bad or hard-to-fit data -- returns a FitResult whose ``notes`` explain what happened.
    The two multi-Gaussian modes fall back to a single Gaussian if they do not converge (as before), but the
    result now reports ``fit_type_used`` and a note so the UI and the saved session cannot mislabel it.

    Raises:
        ValueError: if ``fit_type`` is not one of FIT_TYPES (a programming error, not a data problem).
    """
    if fit_type not in _FITTERS:
        raise ValueError(f"Unknown fit type {fit_type!r}; expected one of {FIT_TYPES}.")
    fitter, n_params = _FITTERS[fit_type]

    try:
        v, y = _validated(vlsr, intensity, n_params)
    except FitError as exc:
        return _failed(fit_type, str(exc))

    try:
        curve, rows, converged, notes = fitter(v, y, unit)
        return FitResult(fit_type, fit_type, curve, rows, notes, converged)
    except _FAILURES as exc:
        if fit_type not in _FALLBACK_TO_1D:
            return _failed(fit_type, f"{fit_type} fit did not converge ({exc}).")

    try:
        curve, rows, converged, notes = _fit_1d(v, y, unit)
    except _FAILURES as exc:
        return _failed(
            fit_type, f"{fit_type} fit did not converge, and neither did the single-Gaussian fallback ({exc})."
        )
    fallback_note = f"{fit_type} fit did not converge; showing a single-Gaussian fit instead."
    return FitResult(fit_type, "1D Gaussian", curve, rows, (fallback_note,) + notes, converged)
