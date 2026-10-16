# fitting_helpers.py — FR-17: bridge between the Streamlit page and clc/Spec_comp.py (multi-component decomposition).
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

import importlib
import math
import threading
from types import ModuleType
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

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
