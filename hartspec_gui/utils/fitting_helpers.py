# fitting_helpers.py — FR-14/15/16/17: bridge between the Streamlit page and clc/ (Gaussf.py, fit_max.py,
# 2D_Gauss_fit.py, Spec_comp.py).
#
# Pure Python (no Streamlit import) so every function is unit-testable. clc/Spec_comp.py is NEVER modified (CON-01).
#
# Facts about clc/Spec_comp.py that shape this module (verified against the file itself, not the written spec):
#   * Signature is Spec_comp(Vlsr, Amp, half_width); half_width is accepted but never used inside the function.
#   * It performs exactly THREE sequential subtract-and-fit Gaussian fits via specutils.fit_lines (astropy fitter).
#   * It RETURNS NOTHING (results are local variables), has no termination options, no covariance and no locking, and
#     it calls plt.* / print. The file also has no import statements of its own.
# Consequences:
#   * run_spec_comp() temporarily supplies the missing names, swaps plt for a no-op and wraps fit_lines with a recorder
#     so each fitted Gaussian is captured exactly as Spec_comp computed it. Module globals are restored afterwards.
#   * Termination criteria are applied to that sequence. Each Spec_comp fit works on the residual left by the previous
#     ones, so stopping after k components gives exactly the first k components -- stopping early is equivalent.
#     max_components > 3 therefore cannot add components (Spec_comp stops at 3).
#   * Spec_comp gives no uncertainties. Uncertainties and parameter locking come from refit_free(), a scipy
#     curve_fit refit of the user's table that is clearly separate from Spec_comp's numbers.
from __future__ import annotations

import ast
import contextlib
import functools
import importlib
import importlib.util
import io
import math
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Mapping, Optional

import numpy as np
import pandas as pd
from scipy.optimize import OptimizeWarning, curve_fit

from utils.spectral_fitting_logic import FitResult

FWHM_PER_SIGMA = 2.0 * math.sqrt(2.0 * math.log(2.0))
MAX_COMPONENTS = 20
SPEC_COMP_MAX_COMPONENTS = 3  # Spec_comp.py hard-codes three sequential fits

COL_ID = "Component"
COL_AMP = "Amplitude"
COL_CENTER = "Center Vlsr (km/s)"
COL_FWHM = "FWHM (km/s)"
COL_LOCK = "Lock"
TABLE_COLUMNS = [COL_ID, COL_AMP, COL_CENTER, COL_FWHM, COL_LOCK]

Params = list[dict[str, Any]]  # [{"id": "Comp 1", "amplitude": .., "center": .., "fwhm": .., "fixed": bool}, ...]

_SPEC_COMP_LOCK = threading.Lock()  # Spec_comp globals are patched during a call -- one call at a time


class DecompositionError(Exception):
    """Spec_comp.py could not be run (missing dependency, bad input, or an exception inside the fit)."""


class FitError(Exception):
    """scipy curve_fit refit failed (non-convergence, singular matrix, infeasible start)."""


# ---------------------------------------------------------------------
# Model maths
# ---------------------------------------------------------------------
def gaussian(v: np.ndarray, amplitude: float, center: float, fwhm: float) -> np.ndarray:
    """Gaussian profile parameterised by FWHM (km/s): amplitude * exp(-(v - center)^2 / (2 sigma^2))."""
    sigma = fwhm / FWHM_PER_SIGMA
    return amplitude * np.exp(-((v - center) ** 2) / (2.0 * sigma ** 2))


def component_curves(v: np.ndarray, params: Params) -> list[np.ndarray]:
    """One curve per component, in table order."""
    return [gaussian(v, p["amplitude"], p["center"], p["fwhm"]) for p in params]


def composite(v: np.ndarray, params: Params) -> np.ndarray:
    """Sum of all component Gaussians (zeros when the table is empty)."""
    total = np.zeros_like(np.asarray(v, dtype=float))
    for curve in component_curves(v, params):
        total = total + curve
    return total


def estimate_noise(y: np.ndarray) -> float:
    """Robust white-noise sigma from second differences (a smooth line barely contributes; MAD ignores line peaks).

    For white noise sigma, var(y[i+1] - 2 y[i] + y[i-1]) = 6 sigma^2. First differences were tried and read 20-30 %
    high because steep line wings leak into them.

    # TODO: confirm against design -- the written spec does not say how sigma_RMS is measured; replace with the
    # pipeline's own noise estimate if one exists.
    """
    y = np.asarray(y, dtype=float)
    if y.size < 3:
        return float("nan")
    d2 = y[2:] - 2.0 * y[1:-1] + y[:-2]
    mad = np.median(np.abs(d2 - np.median(d2)))
    return float(1.4826 * mad / math.sqrt(6.0))


def compute_stats(v: np.ndarray, y: np.ndarray, params: Params) -> dict[str, float]:
    """Residual statistics: ``rms_residual`` and reduced ``chi2`` (sigma from estimate_noise, dof = N - free params)."""
    resid = np.asarray(y, dtype=float) - composite(v, params)
    rms = float(np.sqrt(np.mean(resid ** 2))) if resid.size else float("nan")
    sigma = estimate_noise(y)
    n_free = 3 * sum(1 for p in params if not p["fixed"])
    dof = resid.size - n_free
    if dof > 0 and np.isfinite(sigma) and sigma > 0:
        chi2 = float(np.sum((resid / sigma) ** 2) / dof)
    else:
        chi2 = float("nan")
    return {"chi2": chi2, "rms_residual": rms}


# ---------------------------------------------------------------------
# Running clc/Spec_comp.py (unmodified)
# ---------------------------------------------------------------------
class _NullPlt:
    """Stand-in for matplotlib.pyplot: Spec_comp draws figures that the web GUI must not accumulate."""

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


def _patch_spec_comp_namespace(module: ModuleType, recorded: list[Any]) -> dict[str, tuple[bool, Any]]:
    """Give Spec_comp the names it uses but never imports; record every fit_lines result. Returns restore info."""
    names = ("np", "u", "models", "Spectrum1D", "fit_lines", "plt")
    saved = {n: (n in vars(module), vars(module).get(n)) for n in names}
    ns = vars(module)
    try:
        ns.setdefault("np", np)
        if "u" not in ns or "models" not in ns:
            from astropy import units as u
            from astropy.modeling import models
            ns.setdefault("u", u)
            ns.setdefault("models", models)
        if "Spectrum1D" not in ns:
            from specutils import Spectrum1D
            ns["Spectrum1D"] = Spectrum1D
        if "fit_lines" not in ns:
            from specutils.fitting import fit_lines as real_fit_lines
        else:
            real_fit_lines = ns["fit_lines"]
    except ImportError as exc:  # astropy / specutils absent
        _restore_spec_comp_namespace(module, saved)
        raise DecompositionError(f"Spec_comp.py needs astropy and specutils (import failed: {exc})") from exc

    def recording_fit_lines(*args: Any, **kwargs: Any) -> Any:
        model = real_fit_lines(*args, **kwargs)
        recorded.append(model)
        return model

    ns["fit_lines"] = recording_fit_lines
    ns["plt"] = _NullPlt()
    return saved


def _restore_spec_comp_namespace(module: ModuleType, saved: dict[str, tuple[bool, Any]]) -> None:
    """Undo _patch_spec_comp_namespace so the module is left exactly as it was found."""
    ns = vars(module)
    for name, (existed, value) in saved.items():
        if existed:
            ns[name] = value
        else:
            ns.pop(name, None)


def _model_to_component(model: Any) -> dict[str, float]:
    """astropy Gaussian1D (possibly with Quantity parameters) -> amplitude / center / FWHM as plain floats."""
    def val(x: Any) -> float:
        return float(np.asarray(getattr(x, "value", x)).reshape(-1)[0])

    return {
        "amplitude": val(model.amplitude),
        "center": val(model.mean),
        "fwhm": abs(val(model.stddev)) * FWHM_PER_SIGMA,
    }


def run_spec_comp(vlsr: np.ndarray, amp: np.ndarray, half_width: float = 1.0,
                  module: Optional[ModuleType] = None) -> Params:
    """Run clc/Spec_comp.py unmodified and return its sequential Gaussian fits as a params list (all unlocked).

    Args:
        vlsr: velocity axis (km/s). amp: intensity (K or Jy).
        half_width: forwarded to Spec_comp, which currently ignores it.
        module: override for tests; defaults to ``clc.Spec_comp``.
    Raises:
        DecompositionError: bad input, missing dependency, or any exception raised inside Spec_comp.
    """
    v = np.asarray(vlsr, dtype=float)
    y = np.asarray(amp, dtype=float)
    if v.shape != y.shape or v.ndim != 1 or v.size < 10:
        raise DecompositionError("Velocity and intensity must be 1-D arrays of equal length (at least 10 channels).")
    if not (np.all(np.isfinite(v)) and np.all(np.isfinite(y))):
        raise DecompositionError("The spectrum contains NaN/inf channels; clean or mask them before decomposing.")
    try:
        mod = module if module is not None else importlib.import_module("clc.Spec_comp")
        func = getattr(mod, "Spec_comp")
    except (ImportError, AttributeError) as exc:
        raise DecompositionError(f"clc/Spec_comp.py could not be loaded: {exc}") from exc

    recorded: list[Any] = []
    with _SPEC_COMP_LOCK:
        saved = _patch_spec_comp_namespace(mod, recorded)
        try:
            func(v.copy(), y.copy(), half_width)
        except Exception as exc:  # any failure inside the legacy module must not crash the server
            raise DecompositionError(f"Spec_comp.py raised {type(exc).__name__}: {exc}") from exc
        finally:
            _restore_spec_comp_namespace(mod, saved)
    if not recorded:
        raise DecompositionError("Spec_comp.py completed without fitting any component.")
    comps = [_model_to_component(m) for m in recorded]
    return renumber([{**c, "fixed": False} for c in comps])


def apply_termination(v: np.ndarray, y: np.ndarray, sequence: Params, max_components: int, rms_cutoff: float,
                      chi2_threshold: float) -> tuple[Params, str]:
    """Keep the leading components of ``sequence`` that satisfy the termination criteria.

    Component k is kept when (a) k <= max_components, (b) the peak of the residual before it exceeds
    ``rms_cutoff`` x sigma, and (c) for k > 1 it lowers the reduced chi2 by at least ``chi2_threshold``.
    Returns (kept params, human-readable stop reason).
    """
    sigma = estimate_noise(y)
    kept: Params = []
    reason = "all components returned by Spec_comp.py were kept"
    prev_chi2 = float("nan")
    for k, comp in enumerate(sequence, start=1):
        if k > max_components:
            reason = f"stopped at max_components = {max_components}"
            break
        peak = float(np.max(np.asarray(y, dtype=float) - composite(v, kept)))
        if np.isfinite(sigma) and peak < rms_cutoff * sigma:
            reason = f"stopped: residual peak {peak:.4g} is below {rms_cutoff:g} x sigma_RMS ({sigma:.4g})"
            break
        trial = kept + [comp]
        chi2 = compute_stats(v, y, trial)["chi2"]
        if k > 1 and np.isfinite(prev_chi2) and np.isfinite(chi2) and (prev_chi2 - chi2) < chi2_threshold:
            reason = f"stopped: component {k} lowers reduced chi2 by less than {chi2_threshold:g}"
            break
        kept, prev_chi2 = trial, chi2
    return renumber(kept), reason


# ---------------------------------------------------------------------
# Refit with locking (scipy curve_fit) -- provides uncertainties
# ---------------------------------------------------------------------
def refit_free(v: np.ndarray, y: np.ndarray, params: Params) -> tuple[Params, list[Optional[dict]], list[list[float]]]:
    """Refit all UNLOCKED components jointly with curve_fit; locked components are held exactly and subtracted.

    Returns (new params, per-component uncertainties, covariance of shape 3N x 3N). Uncertainties are None for
    locked components or when curve_fit cannot estimate them; covariance rows/cols of locked parameters are 0.
    Raises FitError on non-convergence, singular matrices or an infeasible starting table.
    """
    v = np.asarray(v, dtype=float)
    y = np.asarray(y, dtype=float)
    if not params:
        raise FitError("There are no components to fit.")
    free = [i for i, p in enumerate(params) if not p["fixed"]]
    if not free:
        raise FitError("All components are locked -- unlock at least one to refit.")
    fixed_curve = composite(v, [p for p in params if p["fixed"]])

    def model(x: np.ndarray, *theta: float) -> np.ndarray:
        total = fixed_curve.copy()
        for j in range(len(free)):
            total = total + gaussian(x, theta[3 * j], theta[3 * j + 1], theta[3 * j + 2])
        return total

    p0 = [params[i][key] for i in free for key in ("amplitude", "center", "fwhm")]
    lower = [-np.inf, float(v.min()), 1e-6] * len(free)
    upper = [np.inf, float(v.max()), np.inf] * len(free)
    try:
        popt, pcov = curve_fit(model, v, y, p0=p0, bounds=(lower, upper), max_nfev=2000)
    except (RuntimeError, ValueError, np.linalg.LinAlgError) as exc:
        raise FitError(f"The fit did not converge ({exc}). Try different starting values.") from exc
    if not np.all(np.isfinite(popt)):
        raise FitError("The fit returned non-finite parameters. Try different starting values.")

    new_params = [dict(p) for p in params]
    for j, i in enumerate(free):
        new_params[i].update(amplitude=float(popt[3 * j]), center=float(popt[3 * j + 1]), fwhm=float(popt[3 * j + 2]))
    pcov = np.asarray(pcov, dtype=float)
    estimable = pcov.shape == (3 * len(free),) * 2 and np.all(np.isfinite(pcov))
    errs = np.sqrt(np.diag(pcov)) if estimable else None
    uncertainties: list[Optional[dict]] = [None] * len(params)
    covariance = np.zeros((3 * len(params), 3 * len(params)))
    for j, i in enumerate(free):
        if errs is not None:
            uncertainties[i] = {"amplitude_err": float(errs[3 * j]), "center_err": float(errs[3 * j + 1]),
                                "fwhm_err": float(errs[3 * j + 2])}
            for k, i2 in enumerate(free):
                covariance[3 * i:3 * i + 3, 3 * i2:3 * i2 + 3] = pcov[3 * j:3 * j + 3, 3 * k:3 * k + 3]
    return new_params, uncertainties, covariance.tolist()


# ---------------------------------------------------------------------
# Table <-> params
# ---------------------------------------------------------------------
def renumber(params: Params) -> Params:
    """Give components sequential ids 'Comp 1', 'Comp 2', ... in table order."""
    return [{**p, "id": f"Comp {i}"} for i, p in enumerate(params, start=1)]


def df_from_params(params: Params) -> pd.DataFrame:
    """Params -> DataFrame for st.data_editor (columns TABLE_COLUMNS)."""
    rows = [[p["id"], p["amplitude"], p["center"], p["fwhm"], bool(p["fixed"])] for p in params]
    return pd.DataFrame(rows, columns=TABLE_COLUMNS).astype(
        {COL_ID: "object", COL_AMP: "float64", COL_CENTER: "float64", COL_FWHM: "float64", COL_LOCK: "bool"})


def params_from_df(df: pd.DataFrame) -> tuple[Params, list[str]]:
    """Edited table -> (valid params, problems). Incomplete or invalid rows are skipped and reported, never raised."""
    params: Params = []
    problems: list[str] = []
    for n, (_, row) in enumerate(df.iterrows(), start=1):
        try:
            amp, cen, fwhm = float(row[COL_AMP]), float(row[COL_CENTER]), float(row[COL_FWHM])
        except (TypeError, ValueError):
            problems.append(f"Row {n} is incomplete and is ignored until filled in.")
            continue
        if not all(np.isfinite([amp, cen, fwhm])):
            problems.append(f"Row {n} is incomplete and is ignored until filled in.")
        elif fwhm <= 0:
            problems.append(f"Row {n}: FWHM must be greater than 0 -- row ignored.")
        elif len(params) >= MAX_COMPONENTS:
            problems.append(f"Row {n}: at most {MAX_COMPONENTS} components are supported -- row ignored.")
        else:
            lock = row[COL_LOCK]
            params.append({"id": "", "amplitude": amp, "center": cen, "fwhm": fwhm,
                           "fixed": bool(lock) if lock is not None and lock == lock else False})
    return renumber(params), problems


# ---------------------------------------------------------------------
# Session JSON (FR-19 / NFR-08)
# ---------------------------------------------------------------------
def _json_num(x: Any) -> Optional[float]:
    """float, or None for NaN/inf/None (JSON has no NaN)."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _align(uncertainties: Optional[list], params: Params) -> list:
    """Uncertainties list matching params one-to-one, or all-None when absent / stale (length mismatch)."""
    if uncertainties is not None and len(uncertainties) == len(params):
        return list(uncertainties)
    return [None] * len(params)


def build_fitting_block(params: Params, uncertainties: Optional[list], covariance: Optional[list],
                        stats: dict[str, float]) -> dict[str, Any]:
    """Session-JSON ``fitting`` block (spec §6.6). Spectral arrays are deliberately NOT included."""
    uncs = _align(uncertainties, params)
    return {
        "type": "multi_component",
        "params": [{"id": p["id"], "amplitude": p["amplitude"], "center": p["center"], "fwhm": p["fwhm"],
                    "fixed": bool(p["fixed"])} for p in params],
        "uncertainties": [
            {"amplitude_err": None, "center_err": None, "fwhm_err": None} if u is None else
            {k: _json_num(u.get(k)) for k in ("amplitude_err", "center_err", "fwhm_err")} for u in uncs],
        "covariance": [[_json_num(c) for c in row] for row in covariance] if covariance else [],
        "statistics": {"chi2": _json_num(stats.get("chi2")), "rms_residual": _json_num(stats.get("rms_residual"))},
    }


def restore_from_block(block: dict[str, Any]) -> Params:
    """Session-JSON ``fitting`` block -> params with full float fidelity. Raises ValueError if malformed."""
    if not isinstance(block, dict) or block.get("type") != "multi_component":
        raise ValueError("Saved fit is not a multi-component fit.")
    out: Params = []
    for i, p in enumerate(block.get("params", []), start=1):
        try:
            amp, cen, fwhm = float(p["amplitude"]), float(p["center"]), float(p["fwhm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Saved component {i} is malformed: {exc}") from exc
        if not all(math.isfinite(x) for x in (amp, cen, fwhm)) or fwhm <= 0:
            raise ValueError(f"Saved component {i} has invalid values.")
        out.append({"id": str(p.get("id", "")), "amplitude": amp, "center": cen, "fwhm": fwhm,
                    "fixed": bool(p.get("fixed", False))})
    return renumber(out)


def summary_rows(params: Params, uncertainties: Optional[list]) -> list[dict[str, Any]]:
    """Flatten to the {parameter, value, error} shape the other fit types store (Page 08 reads this shape)."""
    uncs = _align(uncertainties, params)
    rows = []
    for p, u in zip(params, uncs):
        for label, key, err_key in (("Amplitude", "amplitude", "amplitude_err"),
                                    ("Center (Vlsr)", "center", "center_err"), ("FWHM", "fwhm", "fwhm_err")):
            err = None if u is None else u.get(err_key)
            rows.append({"parameter": f"{p['id']} {label}", "value": p[key], "error": err})
    return rows


# ---------------------------------------------------------------------
# Persistent-JSON mapping: pipeline_data["07_spectral_fitting"]["multi_component"]  <->  stages.fitting
# (called by utils/session_store.py; kept here so it is testable without Streamlit)
# ---------------------------------------------------------------------
FITTING_STAGE_KEY = "07_spectral_fitting"


def stages_from_pipeline(pipeline_data: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the JSON ``stages`` object from live pipeline_data: ``{"fitting": <block>}`` or ``{}``.

    Derived on every write, so switching to another fit type (whose summary has no multi_component block) drops
    ``stages.fitting`` instead of leaving a stale one behind.
    """
    stage = pipeline_data.get(FITTING_STAGE_KEY) if isinstance(pipeline_data, Mapping) else None
    block = stage.get("multi_component") if isinstance(stage, Mapping) else None
    if isinstance(block, dict) and block.get("type") == "multi_component":
        return {"fitting": block}
    return {}


def validate_stages(stages: Any) -> None:
    """Envelope check for a loaded ``stages`` value. Raises ValueError; unknown fitting types are accepted."""
    if stages is None:
        return
    if not isinstance(stages, dict):
        raise ValueError("Invalid session JSON: stages must be an object. The current session was not changed.")
    if "fitting" in stages and not isinstance(stages["fitting"], dict):
        raise ValueError("Invalid session JSON: stages.fitting must be an object. The current session was not changed.")


def merge_stages_into_pipeline(pipeline_data: dict[str, Any], stages: Any) -> dict[str, Any]:
    """Put ``stages.fitting`` back where Page 07 reads it (in place). ``stages.fitting`` wins over a stale copy.

    If the file holds only ``stages.fitting`` (no Page 07 summary), a minimal summary is created so the Fit type
    control is seeded as Multi-component.
    """
    fitting = stages.get("fitting") if isinstance(stages, dict) else None
    if not isinstance(fitting, dict) or fitting.get("type") != "multi_component":
        return pipeline_data
    stage = pipeline_data.get(FITTING_STAGE_KEY)
    if not isinstance(stage, dict):
        stage = {"fit_type": "Multi-component", "fit_type_requested": "Multi-component"}
        pipeline_data[FITTING_STAGE_KEY] = stage
    stage["multi_component"] = fitting
    return pipeline_data


# ---------------------------------------------------------------------
# FR-14 / FR-15 / FR-16 adapters: clc/Gaussf.py, clc/fit_max.py, clc/2D_Gauss_fit.py (never modified, CON-01)
#
# Facts about those files that shape this section (verified against the files, not the written spec):
#   * Gaussf.gaussf(x, hp, *p) takes the HPBW ``hp`` as a CONSTANT and fits only p = (amplitude, mu); there is no
#     offset term and no curve_fit call inside it. The adapter supplies curve_fit, with the HPBW held fixed.
#   * fit_max.fit_max(spec, peak_vel, half_width, order): ``half_width`` is in CHANNELS (not km/s); it reads the
#     columns 'Vlsr' and 'ave_pol' (its docstring says 'Amp'); the window is range(chan - hw, chan + hw), i.e. the
#     upper end is exclusive and a window running off the start would silently wrap; it returns
#     (chans, peak amplitude, fit_x, fit) with the curve sampled at 50 points; it prints to stdout.
#   * 2D_Gauss_fit.py is a DEMO SCRIPT: importing it runs a fit, saves 2D_Gauss.pdf and calls plt.show(). Only its
#     ``twoD_Gaussian`` function is needed, so it is read out of the source with ``ast`` and executed alone.
#     TODO: confirm against design -- guarding the demo with ``if __name__ == "__main__":`` would let it be imported
#     normally (a Phase 0-style mechanical change; not made here).
# ---------------------------------------------------------------------
POLYNOMIAL_ORDERS = (2, 3, 4)  # FR-15 selector: 2nd to 4th order
# TODO: confirm against design -- the spec gives no default half-width (in channels) for the polynomial window.
DEFAULT_HALF_WIDTH_CHANNELS = 10
PARAM_NAMES_2D = ("Amplitude", "X center", "Y center", "Major axis (σ_x)", "Minor axis (σ_y)", "Position angle",
                  "Offset")
COV_LABELS_2D = ("Amplitude", "X center", "Y center", "σ_x", "σ_y", "θ (rad)", "Offset")  # clc units (radians)
SYNTHETIC_TRUTH_2D = (3.0, 0.8, -0.5, 3.0, 2.0, 0.3, 0.5)  # amplitude, x0, y0, sigma_x, sigma_y, theta (rad), offset
_NOT_CONSTRAINED = "not constrained"


class ClcLoadError(Exception):
    """A clc/ module (or the function needed from it) could not be loaded."""


def _failed(requested: str, reason: str) -> FitResult:
    return FitResult(requested, requested, None, (), (reason,), False)


def _fmt(value: float, unit: str) -> str:
    return f"{value:.4g} {unit}".strip()


def _fmt_err(error: float, unit: str) -> str:
    return _fmt(error, unit) if np.isfinite(error) else _NOT_CONSTRAINED


def _spectrum_arrays(vlsr: Any, intensity: Any, min_size: int) -> tuple[np.ndarray, np.ndarray]:
    """1-D float arrays of equal length and all finite; raises ValueError with a user-readable reason."""
    v = np.asarray(vlsr, dtype=float).reshape(-1)
    y = np.asarray(intensity, dtype=float).reshape(-1)
    if v.size != y.size:
        raise ValueError(f"Velocity and intensity lengths differ ({v.size} vs {y.size}).")
    if v.size < min_size:
        raise ValueError(f"Only {v.size} channels are available; at least {min_size} are needed for this fit.")
    if not (np.all(np.isfinite(v)) and np.all(np.isfinite(y))):
        raise ValueError("The spectrum contains NaN or infinite values.")
    return v, y


def _clc_function(module: Optional[ModuleType], module_name: str, function_name: str) -> Callable:
    """The named function from clc/<module_name>.py (``module`` overrides the import, for tests)."""
    try:
        mod = module if module is not None else importlib.import_module(f"clc.{module_name}")
        return getattr(mod, function_name)
    except (ImportError, AttributeError) as exc:
        raise ClcLoadError(f"clc/{module_name}.py could not be loaded: {exc}") from exc


def _step(v: np.ndarray) -> float:
    return float(np.mean(np.abs(np.diff(v)))) if v.size > 1 else 0.1


def estimate_fwhm(vlsr: Any, intensity: Any) -> float:
    """Half-maximum width (km/s) of the tallest line, used only as the default HPBW input. Falls back to 4.0 km/s."""
    v = np.asarray(vlsr, dtype=float).reshape(-1)
    y = np.asarray(intensity, dtype=float).reshape(-1)
    if v.size < 3 or v.size != y.size or not (np.all(np.isfinite(v)) and np.all(np.isfinite(y))):
        return 4.0
    peak = int(np.argmax(y))
    base = float(np.median(y))
    if y[peak] <= base:
        return 4.0
    half = base + (y[peak] - base) / 2.0
    lo = hi = peak
    while lo > 0 and y[lo - 1] >= half:
        lo -= 1
    while hi < y.size - 1 and y[hi + 1] >= half:
        hi += 1
    return float(max(abs(v[hi] - v[lo]), _step(v), 1e-3))


def default_gaussian_guess(vlsr: Any, intensity: Any) -> tuple[float, float, float]:
    """(amplitude, centre km/s, HPBW km/s) defaults for the FR-14 controls, taken from the tallest channel."""
    v = np.asarray(vlsr, dtype=float).reshape(-1)
    y = np.asarray(intensity, dtype=float).reshape(-1)
    peak = int(np.argmax(y))
    return float(y[peak]), float(v[peak]), estimate_fwhm(v, y)


def run_gaussf(vlsr: Any, intensity: Any, hpbw: float, amp_guess: float, center_guess: float, unit: str = "K",
               module: Optional[ModuleType] = None) -> FitResult:
    """FR-14 -- fit ``clc.Gaussf.gaussf`` with scipy curve_fit; amplitude and centre are free, HPBW is held fixed.

    The model has no baseline offset (as in Gaussf.py) and curve_fit uses its default settings. Never raises for bad
    data: returns a FitResult whose ``notes`` explain the problem.

    Args:
        vlsr, intensity: spectrum (km/s, ``unit``). hpbw: fixed half-power width in km/s.
        amp_guess, center_guess: curve_fit starting point p0 = [amplitude, centre].
    """
    name = "1D Gaussian"
    try:
        v, y = _spectrum_arrays(vlsr, intensity, 3)
    except ValueError as exc:
        return _failed(name, str(exc))
    if not (np.all(np.isfinite([hpbw, amp_guess, center_guess])) and hpbw > 0):
        return _failed(name, "The HPBW must be greater than 0 and the initial guesses must be finite numbers.")
    try:
        gaussf = _clc_function(module, "Gaussf", "gaussf")
    except ClcLoadError as exc:
        return _failed(name, str(exc))

    def model(x: np.ndarray, *p: float) -> np.ndarray:
        return gaussf(x, hpbw, *p)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", OptimizeWarning)  # un-estimable covariance is reported explicitly below
            popt, pcov = curve_fit(model, v, y, p0=[amp_guess, center_guess])
    except (RuntimeError, ValueError, np.linalg.LinAlgError) as exc:
        return _failed(name, f"1D Gaussian fit did not converge ({exc}). Try different starting values.")
    perr = np.sqrt(np.abs(np.diag(pcov)))
    converged = bool(np.all(np.isfinite(pcov)))
    notes = ["HPBW is held fixed at the value entered (clc/Gaussf.py takes it as a constant); the model has no "
             "baseline offset."]
    if not converged:
        notes.append("Parameter uncertainties could not be estimated (singular covariance); treat these values as "
                     "unreliable.")
    rows = (
        ("Amplitude", _fmt(popt[0], unit), _fmt_err(perr[0], unit)),
        ("Center (Vlsr)", _fmt(popt[1], "km/s"), _fmt_err(perr[1], "km/s")),
        ("FWHM (HPBW)", _fmt(hpbw, "km/s"), "fixed"),
    )
    return FitResult(name, name, np.asarray(model(v, *popt), dtype=float), rows, tuple(notes), converged)


def fit_max_window(vlsr: Any, peak_vel: float, half_width: int) -> Optional[tuple[float, float]]:
    """Velocity range (lo, hi) in km/s of the channels fit_max.py would use, or None if the window is unusable.

    fit_max uses range(chan - hw, chan + hw) around the channel nearest ``peak_vel``; a window that starts before
    channel 0 would silently wrap in clc, and one that ends past the last channel would raise, so both are refused.
    """
    v = np.asarray(vlsr, dtype=float).reshape(-1)
    if v.size == 0 or int(half_width) < 1 or not np.isfinite(peak_vel) or not np.all(np.isfinite(v)):
        return None
    chan = int(np.abs(v - peak_vel).argmin())
    lo, hi = chan - int(half_width), chan + int(half_width)
    if lo < 0 or hi > v.size:
        return None
    return float(v[lo]), float(v[hi - 1])


def run_fit_max(vlsr: Any, intensity: Any, peak_vel: float, half_width: int, order: int, unit: str = "K",
                module: Optional[ModuleType] = None) -> FitResult:
    """FR-15 -- run ``clc.fit_max.fit_max`` on the spectrum around ``peak_vel`` (half_width in CHANNELS, order 2-4).

    ``FitResult.curve`` / ``curve_x`` are fit_max's own 50-point fit curve. Never raises for bad input.
    """
    name = "Polynomial Peak"
    try:
        v, y = _spectrum_arrays(vlsr, intensity, 3)
    except ValueError as exc:
        return _failed(name, str(exc))
    if order not in POLYNOMIAL_ORDERS:
        return _failed(name, f"Polynomial order must be one of {POLYNOMIAL_ORDERS}, not {order!r}.")
    if int(half_width) != half_width or half_width < 1:
        return _failed(name, "The half-width must be a whole number of channels, at least 1.")
    hw = int(half_width)
    if 2 * hw < order + 1:
        return _failed(name, f"An order-{order} fit needs at least {order + 1} channels; use a half-width of "
                             f"{math.ceil((order + 1) / 2)} or more.")
    if fit_max_window(v, peak_vel, hw) is None:
        return _failed(name, f"A half-width of {hw} channels around {peak_vel:.2f} km/s runs off the end of the "
                             "spectrum. Reduce the half-width or move the peak velocity inward.")
    try:
        fit_max = _clc_function(module, "fit_max", "fit_max")
    except ClcLoadError as exc:
        return _failed(name, str(exc))
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # fit_max prints banner text
            chans, peak_amp, fit_x, fit = fit_max({"Vlsr": v, "ave_pol": y}, peak_vel, hw, order)
    except (ValueError, TypeError, IndexError, KeyError, np.linalg.LinAlgError) as exc:
        return _failed(name, f"fit_max.py failed ({type(exc).__name__}: {exc}).")
    fit_x, fit = np.asarray(fit_x, dtype=float), np.asarray(fit, dtype=float)
    if not (np.all(np.isfinite(fit)) and np.all(np.isfinite(fit_x))):
        return _failed(name, "The polynomial fit returned non-finite values; try a wider window or a lower order.")
    peak_index = int(np.argmax(fit))
    rows = (
        ("Peak amplitude", _fmt(float(peak_amp), unit), "—"),
        ("Peak Vlsr", _fmt(float(fit_x[peak_index]), "km/s"), "—"),
        ("Window", f"{fit_x[0]:.2f} to {fit_x[-1]:.2f} km/s ({len(chans)} channels)", "—"),
        ("Polynomial order", str(order), "—"),
    )
    notes = [f"Order-{order} polynomial fitted by clc/fit_max.py around {peak_vel:.2f} km/s; the peak is the maximum "
             "of the fitted curve inside the window."]
    if peak_index in (0, fit.size - 1):
        notes.append("The polynomial peak sits on the edge of the window; recentre or widen the window.")
    return FitResult(name, name, fit, rows, tuple(notes), True, curve_x=fit_x)


def align_curve(vlsr: Any, curve: Any, curve_x: Any = None) -> np.ndarray:
    """``curve`` on the full velocity axis: as-is when already aligned, else linearly resampled (NaN outside).

    Used only for the saved overlay that Page 08 plots/exports channel-for-channel; the fit itself stays the clc curve.
    """
    v = np.asarray(vlsr, dtype=float).reshape(-1)
    c = np.asarray(curve, dtype=float).reshape(-1)
    if curve_x is None:
        return c
    x = np.asarray(curve_x, dtype=float).reshape(-1)
    order = np.argsort(x)
    x, c = x[order], c[order]
    aligned = np.full(v.shape, np.nan)
    inside = (v >= x[0]) & (v <= x[-1])
    aligned[inside] = np.interp(v[inside], x, c)
    return aligned


# ---------------------------------------------------------------------
# FR-16: 2D Gaussian on a spatial map (clc/2D_Gauss_fit.py::twoD_Gaussian)
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class MapData:
    """A validated st.session_state.map_2d_data: ``data`` has shape (Ny, Nx); ``x`` has Nx and ``y`` has Ny values."""

    data: np.ndarray
    x: np.ndarray
    y: np.ndarray
    unit: str = "map units"
    axis_unit: str = "map units"


@dataclass(frozen=True)
class Fit2DResult:
    """Outcome of a 2D fit. ``popt`` / ``pcov`` are in clc units (angle in radians); ``rows`` are display strings."""

    ok: bool
    popt: Optional[np.ndarray]
    pcov: Optional[np.ndarray]
    model: Optional[np.ndarray]  # fitted surface on the (Ny, Nx) grid
    rows: tuple[tuple[str, str, str], ...]
    notes: tuple[str, ...]
    converged: bool


def _failed_2d(reason: str) -> Fit2DResult:
    return Fit2DResult(False, None, None, None, (), (reason,), False)


def coerce_map_2d(raw: Any) -> Optional[MapData]:
    """Validate ``map_2d_data`` ({"data", "x", "y"}); None when absent or unusable (not raised)."""
    if not isinstance(raw, Mapping) or not all(k in raw for k in ("data", "x", "y")):
        return None
    try:
        data = np.asarray(raw["data"], dtype=float)
        x = np.asarray(raw["x"], dtype=float).reshape(-1)
        y = np.asarray(raw["y"], dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return None
    if data.ndim != 2 or min(data.shape) < 3 or data.shape != (y.size, x.size):
        return None
    if not (np.all(np.isfinite(data)) and np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        return None
    return MapData(data, x, y, str(raw.get("unit", "map units")), str(raw.get("axis_unit", "map units")))


def default_p0_2d(x: np.ndarray, y: np.ndarray, data: np.ndarray) -> tuple[float, ...]:
    """Default 7-parameter guess in UI units: amplitude, x0, y0, sigma_x, sigma_y, angle in DEGREES, offset."""
    iy, ix = np.unravel_index(int(np.argmax(data)), data.shape)
    offset = float(np.median(data))
    amp = float(max(data.max() - offset, 1e-9))
    sx = float(max((np.max(x) - np.min(x)) / 10.0, 1e-6))
    sy = float(max((np.max(y) - np.min(y)) / 10.0, 1e-6))
    return amp, float(x[ix]), float(y[iy]), sx, sy, 0.0, offset


@functools.lru_cache(maxsize=4)
def _extract_twoD_gaussian(path: str) -> Callable:
    """Read ``twoD_Gaussian`` out of the clc source with ast and run only that definition (not the script body)."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "twoD_Gaussian":
            namespace: dict[str, Any] = {"np": np}
            exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), namespace)  # clc code, not input
            return namespace["twoD_Gaussian"]
    raise ClcLoadError("twoD_Gaussian was not found in clc/2D_Gauss_fit.py.")


def twoD_gaussian_model(source_path: Optional[str] = None) -> Callable:
    """clc's ``twoD_Gaussian(xy, amplitude, xo, yo, sigma_x, sigma_y, theta, offset)`` without running the script."""
    try:
        path = source_path
        if path is None:
            spec = importlib.util.find_spec("clc.2D_Gauss_fit")  # locates the file without executing it
            path = None if spec is None else spec.origin
        if not path:
            raise ClcLoadError("clc/2D_Gauss_fit.py was not found.")
        return _extract_twoD_gaussian(str(path))
    except (ImportError, OSError, SyntaxError) as exc:
        raise ClcLoadError(f"clc/2D_Gauss_fit.py could not be loaded: {exc}") from exc


def synthetic_map_2d(model: Optional[Callable] = None, source_path: Optional[str] = None) -> MapData:
    """Deterministic 41 x 41 test map (development only -- callers must refuse to save it).

    TODO: confirm against design -- the spec says to synthesise this from the Stage 6 compass measurements; that
    session structure has not been provided, so the map is generated from SYNTHETIC_TRUTH_2D instead.
    """
    model = model or twoD_gaussian_model(source_path)
    axis = np.linspace(-10.0, 10.0, 41)
    xx, yy = np.meshgrid(axis, axis)
    z = np.asarray(model((xx, yy), *SYNTHETIC_TRUTH_2D), dtype=float).reshape(xx.shape)
    z = z + np.random.default_rng(42).normal(0.0, 0.05, xx.shape)
    return MapData(z, axis.copy(), axis.copy())


def run_2d_gauss(x_axis: Any, y_axis: Any, data: Any, p0_ui: Any, unit: str = "map units",
                 axis_unit: str = "map units", model: Optional[Callable] = None,
                 source_path: Optional[str] = None) -> Fit2DResult:
    """FR-16 -- scipy curve_fit of clc's ``twoD_Gaussian`` over the whole map, exactly as 2D_Gauss_fit.py does it.

    ``p0_ui`` = (amplitude, x0, y0, sigma_x, sigma_y, angle in DEGREES, offset); the angle is converted to radians
    for clc, and the reported angle is converted back. The covariance matrix is returned in clc units (radians).
    Never raises for bad input or non-convergence.
    """
    try:
        x = np.asarray(x_axis, dtype=float).reshape(-1)
        y = np.asarray(y_axis, dtype=float).reshape(-1)
        z = np.asarray(data, dtype=float)
        p0 = np.asarray(p0_ui, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return _failed_2d("The map or the initial guesses could not be read as numbers.")
    if z.ndim != 2 or z.shape != (y.size, x.size) or z.size <= 7:
        return _failed_2d("The map must be a 2-D array of shape (Ny, Nx) with matching x and y axes.")
    if not (np.all(np.isfinite(z)) and np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        return _failed_2d("The map contains NaN or infinite values.")
    if p0.size != 7 or not np.all(np.isfinite(p0)) or p0[3] <= 0 or p0[4] <= 0:
        return _failed_2d("All seven initial guesses must be finite numbers, with both axes greater than 0.")
    try:
        gauss2d = model if model is not None else twoD_gaussian_model(source_path)
    except ClcLoadError as exc:
        return _failed_2d(str(exc))
    p0_clc = p0.copy()
    p0_clc[5] = np.radians(p0[5])
    xx, yy = np.meshgrid(x, y)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", OptimizeWarning)
            popt, pcov = curve_fit(gauss2d, (xx, yy), z.ravel(), p0=p0_clc)
    except (RuntimeError, ValueError, np.linalg.LinAlgError) as exc:
        return _failed_2d(f"2D Gaussian fit did not converge ({exc}). Try different starting values.")
    pcov = np.asarray(pcov, dtype=float)
    converged = bool(np.all(np.isfinite(pcov)))
    perr = np.sqrt(np.abs(np.diag(pcov)))
    units = (unit, axis_unit, axis_unit, axis_unit, axis_unit, "°", unit)
    values = [*popt[:5], float(np.degrees(popt[5])), popt[6]]
    errors = [*perr[:5], float(np.degrees(perr[5])), perr[6]]
    rows = tuple((n, _fmt(v, u), _fmt_err(e, u)) for n, v, e, u in zip(PARAM_NAMES_2D, values, errors, units))
    notes = ["Major/Minor axis are the σ_x / σ_y of clc's twoD_Gaussian and are not re-sorted by size."]
    if not converged:
        notes.append("Parameter uncertainties could not be estimated (singular covariance); treat these values as "
                     "unreliable.")
    surface = np.asarray(gauss2d((xx, yy), *popt), dtype=float).reshape(z.shape)
    return Fit2DResult(True, np.asarray(popt, dtype=float), pcov, surface, rows, tuple(notes), converged)


def covariance_dataframe(result: Fit2DResult) -> pd.DataFrame:
    """7 x 7 covariance matrix as a labelled DataFrame (clc units: angle in radians); non-finite entries become NaN."""
    if result.pcov is None:
        return pd.DataFrame(columns=list(COV_LABELS_2D))
    cov = np.where(np.isfinite(result.pcov), result.pcov, np.nan)
    return pd.DataFrame(cov, index=list(COV_LABELS_2D), columns=list(COV_LABELS_2D))
