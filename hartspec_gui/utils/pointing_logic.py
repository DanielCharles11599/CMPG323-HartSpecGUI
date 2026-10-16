# pointing_logic.py — FR-12/13: pure (Streamlit-free) helpers behind Page 06, Pointing Correction.
#
# What lives here:
#   * find_pointing_scans()   -- picks the HPN/HPS/HPE/HPW + on-source ON files of each pointing scan out of the
#                                observation blocks clc/File_check.py produced (Page 01 hands them over).
#   * channel/peak helpers    -- the "black point" the user picks on each compass panel snaps to a real channel.
#   * compute_pointing()      -- calls clc.Point_cor.pointcor() WITHOUT modifying Point_cor.py (see below).
#
# Why compute_pointing() wraps pointcor() instead of calling it bare (Point_cor.py itself must stay untouched):
#   1. pointcor() sets a module-level `global hp` that gaussf() reads during curve_fit. Two Streamlit sessions in one
#      server process could race on it, so every call is serialised with a lock.
#   2. pointcor() saves a PDF to the hard-coded relative path "../plots/..." (relative to the process cwd, outside the
#      mandated /data layout) and uses pyplot's global current-figure state. Inside the same lock, Point_cor's own
#      `plt` name is swapped for a thin proxy whose savefig() writes into a folder we choose (or nowhere). Only
#      Point_cor's reference is swapped -- pyplot itself and every other module are unaffected.
#   # TODO: confirm against design -- a proper fix (no global, no hard-coded path) belongs in Point_cor.py as a
#   # Phase 0 change, which the owners have not authorised; this wrapper is the page-side mitigation.
from __future__ import annotations

import hashlib
import importlib
import math
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

ROLES = ("N", "S", "E", "W", "Centre")  # left-to-right order on the page (Build Spec §7) -- NOT a geographic cross
_POSITION_TO_ROLE = {"HPN": "N", "HPS": "S", "HPE": "E", "HPW": "W"}
_POINTCOR_ARGUMENT = {"N": "north", "S": "south", "E": "east", "W": "west", "Centre": "cen"}

_POINTCOR_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Finding pointing scans in File_check's observation blocks
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PointingScan:
    """One complete pointing scan: a FITS filename for each of N, S, E, W and Centre."""

    block: str
    number: int
    files: Dict[str, str]
    # Second file Cal_point_check.py needs: the scan's second on-source file (frequency switch, position "ON") or its
    # pointing OFF file (position switch, position "OFF"). Kept apart from ``files`` so ``files`` stays the five roles.
    reference: Optional[str] = None
    reference_position: str = ""

    @property
    def key(self) -> str:
        """Stable identifier, used in session_state keys so picks reset when the scan changes."""
        return f"{self.block}#{self.number}"

    @property
    def label(self) -> str:
        """Human label for the scan selector, e.g. "20260812_0 · scan 1"."""
        name = self.block[:-4] if self.block.lower().endswith(".txt") else self.block
        return f"{name} · scan {self.number}"


def _is_pointing_on(spectrum: Mapping[str, Any]) -> bool:
    """True for an ON file taken during a pointing scan (SPPOINT == 1); science ON files have SPPOINT == 0."""
    try:
        return int(float(spectrum.get("pointing"))) == 1
    except (TypeError, ValueError):
        return False


def _is_pointing_off(spectrum: Mapping[str, Any]) -> bool:
    """True for an OFF file taken during a pointing scan (SPPOINT == 1)."""
    return str(spectrum.get("position", "")).strip().upper() == "OFF" and _is_pointing_on(spectrum)


def _role_of(spectrum: Optional[Mapping[str, Any]]) -> Optional[str]:
    """Compass role of a loaded spectrum, or None if it is not part of a pointing scan."""
    if not spectrum:
        return None
    position = str(spectrum.get("position", "")).strip().upper()
    if position in _POSITION_TO_ROLE:
        return _POSITION_TO_ROLE[position]
    if position == "ON" and _is_pointing_on(spectrum):
        return "Centre"
    return None


def find_pointing_scans(
    blocks: Mapping[str, Sequence[str]],
    lookup: Callable[[str], Optional[Mapping[str, Any]]],
) -> List[PointingScan]:
    """Find the complete pointing scans in File_check's observation blocks.

    Args:
        blocks: block file name -> FITS filenames in observation order (pipeline_data["01_source_browser"]).
        lookup: filename -> loaded spectrum dict (needs "position" and "pointing"), or None if not loaded.

    Returns:
        Complete scans only (all five roles present), in block-name order.

    A scan is built by walking a block in order and starting a new one whenever a role repeats, so several scans in
    one block (one observing day) are separated correctly regardless of the order the files were taken in.
    """
    scans: List[PointingScan] = []
    for block_name in sorted(blocks):
        pending: List[Tuple[Dict[str, str], Optional[Tuple[str, str]]]] = []
        current: Dict[str, str] = {}
        reference: Optional[Tuple[str, str]] = None
        for filename in blocks[block_name]:
            spectrum = lookup(filename)
            role = _role_of(spectrum)
            if role is None:
                if reference is None and spectrum and _is_pointing_off(spectrum):
                    reference = (filename, "OFF")  # position switch: the pointing OFF file
                continue
            if role == "Centre" and "Centre" in current and len(current) == len(ROLES) and reference is None:
                reference = (filename, "ON")  # frequency switch: the scan's second on-source file
                continue
            if role in current:  # same direction again => the previous scan is finished
                pending.append((current, reference))
                current, reference = {}, None
            current[role] = filename
        if current:
            pending.append((current, reference))
        for number, (files, ref) in enumerate(pending, start=1):
            if len(files) == len(ROLES):
                scans.append(PointingScan(block=block_name, number=number, files=files,
                                          reference=ref[0] if ref else None,
                                          reference_position=ref[1] if ref else ""))
    return scans


# ---------------------------------------------------------------------------
# Picking the peak ("black point") on a compass panel
# ---------------------------------------------------------------------------

def average_spectrum(lcp: Any, rcp: Any) -> np.ndarray:
    """Channel-by-channel mean of LCP and RCP."""
    return (np.asarray(lcp, dtype=float) + np.asarray(rcp, dtype=float)) / 2.0


def default_peak_index(vlsr: Any, lcp: Any, rcp: Any) -> int:
    """Channel of the strongest LCP/RCP-average value -- the starting position of the black point."""
    average = average_spectrum(lcp, rcp)
    if average.size == 0 or np.all(np.isnan(average)):
        return 0
    return int(np.nanargmax(average))


def nearest_channel(vlsr: Any, velocity: float) -> int:
    """Index of the channel whose velocity is closest to `velocity` (km/s)."""
    axis = np.asarray(vlsr, dtype=float)
    return int(np.nanargmin(np.abs(axis - float(velocity))))


def power_at_channel(lcp: Any, rcp: Any, index: int) -> float:
    """The single power value pointcor() needs: mean of LCP and RCP at the picked channel."""
    return float(average_spectrum(lcp, rcp)[index])


# ---------------------------------------------------------------------------
# Calling clc.Point_cor.pointcor() safely
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PointingUncertainties:
    """1-sigma fit uncertainties for the pointing results (FR-12). Any member may be None (not available)."""

    ns_sigma_deg: Optional[float] = None
    ew_sigma_deg: Optional[float] = None
    pc_sigma: Optional[float] = None


@dataclass(frozen=True)
class PointingResult:
    """What pointcor() returned, with the inputs that produced it.

    ``uncertainties`` come from the two curve_fit calls inside pointcor() (captured by compute_pointing(), see
    there); None if they could not be captured.
    """

    correction_factor: float
    ns_offset_deg: float
    ew_offset_deg: float
    hpbw_deg: float
    powers: Dict[str, float]
    uncertainties: Optional[PointingUncertainties] = None
    # axis name -> {"x", "y" (the fitted Gaussian from Point_cor.gaussf), "centre", "amplitude"}; display only
    fit_curves: Optional[Dict[str, Dict[str, Any]]] = None
    # sqrt(mean((measured - fitted)^2)) over the six measured points, in power units; None if not computable.
    # TODO: confirm against design -- computed here (pointcor() returns none); owners may instead drop the row.
    rms_residual: Optional[float] = None


class _PyplotProxy:
    """Stands in for `plt` inside Point_cor only: everything delegates to pyplot except savefig()."""

    def __init__(self, real: Any, savefig: Callable[..., Any]) -> None:
        self._real = real
        self.savefig = savefig

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def _redirected_savefig(real_plt: Any, plot_dir: Optional[Path]) -> Callable[..., Any]:
    """savefig() replacement: write the file's basename into plot_dir, or skip saving if plot_dir is None."""

    def savefig(fname: Any, *args: Any, **kwargs: Any) -> Any:
        if plot_dir is None:
            return None
        Path(plot_dir).mkdir(parents=True, exist_ok=True)
        return real_plt.savefig(str(Path(plot_dir) / Path(str(fname)).name), *args, **kwargs)

    return savefig


def _import_pointcor() -> Any:
    """Import clc.Point_cor lazily (keeps this module importable/testable without clc and without a display)."""
    import matplotlib

    matplotlib.use("Agg")  # server-side rendering only; pointcor() builds figures it never shows
    try:
        from clc import Point_cor
    except ImportError:
        # clc/ modules use flat sibling imports (original CLI style); make that work too.
        clc_dir = Path(__file__).resolve().parent.parent / "clc"
        if str(clc_dir) not in sys.path:
            sys.path.append(str(clc_dir))
        import Point_cor  # type: ignore
    return Point_cor


# pointcor() fits north-south first, then east-west (verified against clc/Point_cor.py); each fit is A, mu.
FIT_PANELS = (
    ("North-South", ("South", "Centre", "North")),
    ("East-West", ("West", "Centre", "East")),
)


# Display names used in FIT_PANELS / messages -> the role codes used for powers and page panels.
PANEL_ROLE = {"North": "N", "South": "S", "East": "E", "West": "W", "Centre": "Centre"}


class PointingFitError(RuntimeError):
    """A pointcor() Gaussian fit did not converge; names the compass panels that fit used (Use Case UC-08).

    ``partial_curves`` holds the fitted curves of any fit that completed before the failure (pointcor() stops at the
    first one), so the page can still draw them.
    """

    def __init__(self, axis: str, panels: Tuple[str, ...], original: Exception,
                 partial_curves: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        self.axis = axis
        self.panels = tuple(panels)
        self.partial_curves = partial_curves or {}
        super().__init__(f"the {axis} fit ({', '.join(panels)} panels) did not converge: {original}")


def measured_points(powers: Mapping[str, float], hpbw_deg: float) -> Dict[str, Dict[str, Any]]:
    """The three measured points of each pointcor() fit: x = -h/2, 0, +h/2 (deg), y = the panel powers."""
    half = float(hpbw_deg) / 2.0
    return {
        axis: {"panels": panels, "x": [-half, 0.0, half], "y": [float(powers[PANEL_ROLE[name]]) for name in panels]}
        for axis, panels in FIT_PANELS
    }


def _fit_curves(module: Any, fits: Sequence[Tuple[np.ndarray, np.ndarray]], hpbw_deg: float,
                ) -> Dict[str, Dict[str, Any]]:
    """Fitted curves from Point_cor's own gaussf (same range as its PDF). Call inside _POINTCOR_LOCK: gaussf reads
    the module-level ``hp`` that pointcor() has just set."""
    curves: Dict[str, Dict[str, Any]] = {}
    half = float(hpbw_deg) / 2.0
    smooth = np.linspace(-4 * half, 4 * half, 100)
    for (axis, _panels), (popt, _pcov) in zip(FIT_PANELS, fits):
        try:
            values = np.asarray(module.gaussf(smooth, *popt), dtype=float)
        except Exception:  # noqa: BLE001 -- display only; never let a plot break the calculation
            continue
        curves[axis] = {"x": smooth, "y": values, "centre": float(popt[1]), "amplitude": float(popt[0])}
    return curves


def _rms_residual(module: Any, fits: Sequence[Tuple[np.ndarray, np.ndarray]], powers: Mapping[str, float],
                  hpbw_deg: float) -> Optional[float]:
    """Pooled RMS of (measured - fitted) at the NS and EW measured points. Call inside _POINTCOR_LOCK (gaussf uses
    the module-level ``hp``). Display only: never feeds pointcor() or the verdict."""
    if len(fits) != len(FIT_PANELS):
        return None
    measured = measured_points(powers, hpbw_deg)
    residuals: List[float] = []
    try:
        for (axis, _panels), (popt, _pcov) in zip(FIT_PANELS, fits):
            x = np.asarray(measured[axis]["x"], dtype=float)
            y = np.asarray(measured[axis]["y"], dtype=float)
            residuals.extend(y - np.asarray(module.gaussf(x, *popt), dtype=float))
        value = float(np.sqrt(np.mean(np.square(residuals))))
    except Exception:  # noqa: BLE001 -- display only
        return None
    return value if math.isfinite(value) else None


def _recording_curve_fit(real: Callable[..., Any], fits: List[Tuple[np.ndarray, np.ndarray]],
                         failure: Dict[str, Optional[int]]) -> Callable[..., Any]:
    """curve_fit stand-in used inside Point_cor only: records (popt, pcov) per call and which call failed."""

    def spy(*args: Any, **kwargs: Any) -> Any:
        try:
            popt, pcov = real(*args, **kwargs)
        except Exception:
            failure["index"] = len(fits)
            raise
        fits.append((np.asarray(popt, dtype=float), np.asarray(pcov, dtype=float)))
        return popt, pcov

    return spy


def _uncertainties_from_fits(
    fits: Sequence[Tuple[np.ndarray, np.ndarray]], factor: float, hpbw_deg: float,
) -> Optional[PointingUncertainties]:
    """1-sigma on the NS / EW centres (sqrt of the mu variance) and first-order propagation onto pc.

    pc = exp(ln2 (ns^2 + ew^2) / h^2), h = hpbw / 2, so
    sigma_pc = pc * (2 ln2 / h^2) * sqrt((ns sigma_ns)^2 + (ew sigma_ew)^2), treating the two fits as independent.
    # TODO: confirm against design -- the pc propagation is our derivation, not a clc/ output.
    """
    if len(fits) != len(FIT_PANELS):
        return None
    sigmas: List[Optional[float]] = []
    centres: List[float] = []
    for popt, pcov in fits:
        if popt.shape != (2,) or pcov.shape != (2, 2):
            return None
        variance = float(pcov[1, 1])
        sigmas.append(math.sqrt(variance) if math.isfinite(variance) and variance >= 0 else None)
        centres.append(float(popt[1]))
    pc_sigma: Optional[float] = None
    if sigmas[0] is not None and sigmas[1] is not None and math.isfinite(factor):
        half = hpbw_deg / 2.0
        pc_sigma = factor * (2.0 * math.log(2.0) / half ** 2) * math.hypot(centres[0] * sigmas[0],
                                                                           centres[1] * sigmas[1])
    return PointingUncertainties(ns_sigma_deg=sigmas[0], ew_sigma_deg=sigmas[1], pc_sigma=pc_sigma)


def compute_pointing(
    powers: Mapping[str, float],
    hpbw_deg: float,
    dirname: str,
    plot_dir: Optional[Path] = None,
) -> PointingResult:
    """Run clc.Point_cor.pointcor() on the five picked powers.

    Args:
        powers: power at the half-power points and on source, keyed by ROLES ("N", "S", "E", "W", "Centre").
        hpbw_deg: half-power beam width in degrees (from the FITS header, or typed in).
        dirname: pointcor() names its PDF "Point_Offset_for_<dirname[0:8]>.pdf" -- pass the scan's date prefix.
        plot_dir: folder for that PDF; None skips saving it.

    Raises:
        ValueError: a power is missing/non-finite/non-positive, or the beam width is not positive.
        Whatever pointcor()/curve_fit raise (e.g. RuntimeError if the fit fails to converge).
    """
    for role in ROLES:
        value = powers.get(role)
        if value is None or not math.isfinite(value) or value <= 0:
            raise ValueError(f"The {role} power must be a positive number (got {value!r}).")
    if hpbw_deg is None or not math.isfinite(hpbw_deg) or hpbw_deg <= 0:
        raise ValueError(f"The half-power beam width must be a positive number of degrees (got {hpbw_deg!r}).")

    pointcor_module = _import_pointcor()
    arguments = {_POINTCOR_ARGUMENT[role]: float(powers[role]) for role in ROLES}
    fits: List[Tuple[np.ndarray, np.ndarray]] = []
    failure: Dict[str, Optional[int]] = {"index": None}
    with _POINTCOR_LOCK:
        original_plt = pointcor_module.plt
        original_fit = getattr(pointcor_module, "curve_fit", None)
        pointcor_module.plt = _PyplotProxy(original_plt, _redirected_savefig(original_plt, plot_dir))
        if original_fit is not None:
            pointcor_module.curve_fit = _recording_curve_fit(original_fit, fits, failure)
        try:
            factor, ns_offset, ew_offset = pointcor_module.pointcor(
                hpbw=float(hpbw_deg), dirname=dirname, **arguments
            )
            curves = _fit_curves(pointcor_module, fits, hpbw_deg)
            rms_residual = _rms_residual(pointcor_module, fits, powers, hpbw_deg)
        except Exception as exc:
            if failure["index"] is not None and failure["index"] < len(FIT_PANELS):
                axis, panels = FIT_PANELS[failure["index"]]
                raise PointingFitError(axis, panels, exc, _fit_curves(pointcor_module, fits, hpbw_deg)) from exc
            raise
        finally:
            pointcor_module.plt = original_plt
            if original_fit is not None:
                pointcor_module.curve_fit = original_fit

    return PointingResult(
        correction_factor=float(factor),
        ns_offset_deg=float(ns_offset),
        ew_offset_deg=float(ew_offset),
        hpbw_deg=float(hpbw_deg),
        powers={role: float(powers[role]) for role in ROLES},
        uncertainties=_uncertainties_from_fits(fits, float(factor), float(hpbw_deg)),
        fit_curves=curves,
        rms_residual=rms_residual,
    )


# ---------------------------------------------------------------------------
# FR-13: Go / No-Go quality check (pure -- no Streamlit)
#   Condition A: |NS offset| < 2.5 x sigma_NS (fit uncertainty of the NS Gaussian centre)
#   Condition B: clc Stats_manager.Sig_point -> "Yes" (every one of the five pointings peaks >= 2.5 x baseline rms)
# ---------------------------------------------------------------------------

THRESHOLD_SIGMA = 2.5
SIG_POINT_THRESHOLD = 2.5  # hard-coded inside Stats_manager.Sig_point; used for messages only
VERDICT_GO = "Go"
VERDICT_NO_GO = "No-Go"


@dataclass(frozen=True)
class SignalToNoiseCheck:
    """Condition B. ``sig_point`` is Sig_point's raw answer: "Yes" (all five >= 2.5), "No" (all below) or "" (mixed).

    ``panel_snr`` (peak / baseline rms per panel) is informational; the verdict comes from Sig_point itself.
    """

    evaluated: bool
    passed: bool
    sig_point: str = ""
    reason: str = ""
    peak_velocity_kms: Optional[float] = None
    panel_snr: Tuple[Tuple[str, float], ...] = ()
    resampled: Tuple[str, ...] = ()  # spectra interpolated onto the Centre grid for this check, with the detail


@dataclass(frozen=True)
class PointingCheck:
    """Outcome of the pointing quality check.

    ``evaluated`` is True only when both conditions could be run. Anything not evaluated or failed is a No-Go.
    ``overridable`` is False for a non-converging fit (UC-08 exception flow): there is no correction factor to apply,
    so RULE-05 does not apply. ``failed_panels`` names the panels of the failed fit.
    """

    verdict: str
    threshold_sigma: float
    reasons: Tuple[str, ...]
    evaluated: bool
    overridable: bool
    ns_ratio: Optional[float] = None
    failed_panels: Tuple[str, ...] = ()
    snr: Optional[SignalToNoiseCheck] = None
    snr_skipped: bool = False  # condition B not applicable (manual entry: there are no spectra)


def _usable_sigma(value: Any) -> Optional[float]:
    """A finite, strictly positive sigma, or None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _finite_or_none(value: Any) -> Optional[float]:
    """JSON-safe float (NaN / inf / non-numbers become None)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _import_stats_manager() -> Any:
    """Import clc.Stats_manager lazily (heavy flat imports; keeps this module importable without clc)."""
    try:
        from clc import Stats_manager
    except ImportError:
        clc_dir = Path(__file__).resolve().parent.parent / "clc"
        if str(clc_dir) not in sys.path:
            sys.path.append(str(clc_dir))
        import Stats_manager  # type: ignore
    return Stats_manager


def _align_amplitude(role: str, grid: np.ndarray, amplitude: np.ndarray, reference: np.ndarray,
                     ) -> Tuple[np.ndarray, Optional[str]]:
    """Put one spectrum on the reference (Centre) velocity grid; returns (amplitude, note or None).

    The five scans are separate observations, so their Vlsr axes differ (LSR correction), sometimes by more than a
    channel, and may differ in length, while Sig_point looks every spectrum up on ONE axis. An identical grid is used
    untouched; otherwise the spectrum is linearly interpolated onto the reference grid, with NaN where it does not
    reach (the caller then leaves those channels out of the noise estimate). This feeds only the signal-to-noise
    gate -- never the powers given to pointcor() nor any exported spectrum.
    # TODO: confirm against design -- the CLC flow may assume the five scans already share one grid.
    """
    if grid.shape == reference.shape and np.allclose(grid, reference):
        return amplitude, None
    if grid.ndim != 1 or grid.size < 2 or amplitude.shape != grid.shape or not np.all(np.isfinite(grid)):
        raise ValueError(f"the {role} spectrum has an unusable velocity axis")
    order = np.argsort(grid)
    axis = grid[order]
    if np.any(np.diff(axis) <= 0):
        raise ValueError(f"the {role} velocity axis has repeated values")
    aligned = np.interp(reference, axis, amplitude[order], left=np.nan, right=np.nan)
    if grid.shape == reference.shape:
        detail = f"max shift {float(np.max(np.abs(grid - reference))):.4f} km/s"
    else:
        detail = f"{grid.size} vs {reference.size} channels"
    missing = int(np.count_nonzero(np.isnan(aligned)))
    if missing:
        detail += f", {missing} channels outside its range left out of the noise"
    return aligned, f"{role} ({detail})"


def _snr_from_answer(answer: str, amplitudes: Sequence[np.ndarray], reference: np.ndarray, mask: np.ndarray,
                     peak_vel: float, resampled: Sequence[str]) -> SignalToNoiseCheck:
    """Condition B result from Sig_point's raw answer; per-panel peak / baseline-rms is informational."""
    panel_snr = []
    try:
        for role, amplitude in zip(ROLES, amplitudes):
            rms = float(np.sqrt(np.ma.mean(np.ma.array(amplitude, mask=mask) ** 2)))
            peak = float(np.max(amplitude[reference == peak_vel]))
            if math.isfinite(rms) and rms > 0 and math.isfinite(peak):
                panel_snr.append((role, peak / rms))
    except Exception:  # noqa: BLE001 -- informational only
        panel_snr = []
    if answer == "Yes":
        reason = ""
    elif answer == "No":
        reason = (f"Sig_point: none of the five pointings reaches {SIG_POINT_THRESHOLD:g}σ above the baseline noise "
                  f"at {peak_vel:.2f} km/s.")
    else:
        reason = (f"Sig_point: not every one of the five pointings reaches {SIG_POINT_THRESHOLD:g}σ above the "
                  f"baseline noise at {peak_vel:.2f} km/s.")
    return SignalToNoiseCheck(True, answer == "Yes", answer, reason, peak_vel, tuple(panel_snr),
                              tuple(resampled))


def evaluate_signal_to_noise(
    spectra: Mapping[str, Mapping[str, Any]], blocks: Sequence[Mapping[str, Any]], peak_velocity: float,
    sig_point: Optional[Callable[..., Any]] = None,
) -> SignalToNoiseCheck:
    """Run the unmodified Stats_manager.Sig_point on the five pointing spectra (Condition B).

    Args:
        spectra: role (ROLES) -> loaded spectrum with Vlsr / LCP / RCP; all five must share one velocity grid.
        blocks: committed Page 04 baseline regions; they define Sig_point's noise mask (0 = used for the rms).
        peak_velocity: line velocity (km/s) -- the Centre panel's pick; snapped to a real channel.
        sig_point: injectable for tests; defaults to clc Stats_manager.Sig_point.

    Each pointing is the LCP/RCP mean, as for the powers handed to pointcor(). Never raises: anything that stops
    Sig_point from running gives ``evaluated=False`` (a No-Go with the reason), never a silent pass.
    # TODO: confirm against design -- the spectra are the loaded (raw) ones the peaks are picked on; whether the CLC
    # flow baseline-flattens the pointing scans before Sig_point is not visible from the supplied files.
    """

    def unavailable(reason: str) -> SignalToNoiseCheck:
        return SignalToNoiseCheck(evaluated=False, passed=False, reason=reason)

    try:
        if not blocks:
            return unavailable("The baseline regions from Page 04 are not available, so the noise level cannot be "
                               "measured for the Sig_point signal-to-noise check.")
        reference = np.asarray(spectra["Centre"]["Vlsr"], dtype=float)
        amplitudes = []
        resampled: List[str] = []
        for role in ROLES:
            spectrum = spectra[role]
            aligned, note = _align_amplitude(
                role, np.asarray(spectrum["Vlsr"], dtype=float),
                average_spectrum(spectrum["LCP"], spectrum["RCP"]), reference,
            )
            amplitudes.append(aligned)
            if note:
                resampled.append(note)
        from utils.baseline_polynomial_adapter import build_clc_masks
        mask = np.array(build_clc_masks(reference, [{"start": b["start"], "end": b["end"]} for b in blocks])[0])
        peak_index = nearest_channel(reference, peak_velocity)
        peak_vel = float(reference[peak_index])
        uncovered = np.zeros(reference.shape, dtype=bool)
        for amplitude in amplitudes:
            uncovered |= np.isnan(amplitude)
        if uncovered[peak_index]:
            return unavailable(f"A pointing spectrum does not reach the peak velocity {peak_vel:.2f} km/s, so "
                               "Sig_point cannot compare them.")
        mask[uncovered] = 1  # shared noise mask: only channels every one of the five spectra covers
        amplitudes = [np.nan_to_num(amplitude, nan=0.0) for amplitude in amplitudes]
        if not np.any(mask == 0):
            return unavailable("No baseline channel is covered by all five pointing spectra, so the noise cannot be "
                               "measured.")
        function = sig_point or _import_stats_manager().Sig_point
        answer = str(function(*amplitudes, reference, mask, peak_vel))
    except Exception as exc:  # noqa: BLE001 -- legacy code / malformed input: report, never crash the page
        return unavailable(f"Sig_point could not be run: {exc}")

    return _snr_from_answer(answer, amplitudes, reference, mask, peak_vel, resampled)


def evaluate_pointing_check(
    result: Any, snr: Optional[SignalToNoiseCheck] = None, threshold_sigma: float = THRESHOLD_SIGMA,
    *, snr_required: bool = True,
) -> PointingCheck:
    """Go only if A (|NS offset| < threshold x sigma_NS, strict) AND B (Sig_point says "Yes") both pass.

    ``snr_required=False`` skips B entirely (manual entry has no spectra for Sig_point); A alone then decides.

    The EW offset is shown with its uncertainty but does not affect the verdict (Technical Specification).
    A condition that could not be evaluated is a No-Go with its reason -- never a silent Go.
    """
    reasons: List[str] = []
    uncertainties = getattr(result, "uncertainties", None)
    ns_sigma = _usable_sigma(getattr(uncertainties, "ns_sigma_deg", None))
    ratio: Optional[float] = None
    a_evaluated = ns_sigma is not None
    if ns_sigma is None:
        reasons.append("The NS fit uncertainty needed for the %gσ check is not available, so the offset cannot be "
                       "verified." % threshold_sigma)
    else:
        offset = abs(float(result.ns_offset_deg))
        ratio = offset / ns_sigma
        if not ratio < threshold_sigma:  # strict; NaN falls through to No-Go
            reasons.append(f"|NS offset| = {offset:.4f}° is {ratio:.2f}σ, not below {threshold_sigma:g}σ.")
    if snr_required:
        if snr is None:
            reasons.append("The Sig_point signal-to-noise check was not run.")
        elif not (snr.evaluated and snr.passed):
            reasons.append(snr.reason or "The Sig_point signal-to-noise check did not pass.")
    b_evaluated = (not snr_required) or bool(snr is not None and snr.evaluated)
    return PointingCheck(
        VERDICT_GO if not reasons else VERDICT_NO_GO, threshold_sigma, tuple(reasons),
        evaluated=a_evaluated and b_evaluated, overridable=True, ns_ratio=ratio,
        snr=snr if snr_required else None, snr_skipped=not snr_required,
    )


def failed_fit_check(
    message: str, panels: Sequence[str] = (), threshold_sigma: float = THRESHOLD_SIGMA,
) -> PointingCheck:
    """No-Go for a fit that did not converge. Not overridable: there is no correction factor to apply."""
    return PointingCheck(
        VERDICT_NO_GO, threshold_sigma, (f"The pointing fit did not converge: {message}",),
        evaluated=False, overridable=False, failed_panels=tuple(panels),
    )


# ---------------------------------------------------------------------------------------------------------------
# FR-12 on PROCESSED spectra: the unmodified clc Cal_point_check.py
#   Cal_point_check.calculate_pointing_corr_freq / _pos load the six pointing files, bandpass-correct them
#   (freq_switch / pos_switch), flatten the baseline with the Page 04 masks (Flat_base), average LCP/RCP, run
#   Sig_point, fit the peaks (fit_max) and call pointcor(). This wrapper changes none of that; it only
#     * redirects the plots the module saves to "../plots/" and keeps pyplot headless / non-blocking (Full_YN="Yes"),
#     * records what the module computes internally but does not return (processed spectra, fit_max peak powers, the
#       curve_fit covariances, Sig_point's raw answer), and
#     * lets the module go on to compute pc / offsets when Sig_point says "" (mixed) -- as it already does for "No" --
#       so the GUI can show the numbers and make the Go / No-Go decision itself (FR-13).
#   Cal_point_cor.py differs only in returning pc = 1.0 for a "No"; use it by changing CAL_POINT_MODULE.
#   # TODO: confirm against design -- Cal_point_check.py's pyplot/time usage and ../plots/ path are mitigated here, not
#   # fixed in clc/.
# ---------------------------------------------------------------------------------------------------------------
CAL_POINT_MODULE = "Cal_point_check"
MODE_FUNCTIONS = {"Frequency Switch": "calculate_pointing_corr_freq", "Position Switch": "calculate_pointing_corr_pos"}
REFERENCE_POSITION = {"Frequency Switch": "ON", "Position Switch": "OFF"}
HALF_WIDTH_MIN = 2  # fit_max() fits an order-3 polynomial over 2 * half_width channels
_SCAN_FILE_ORDER = (("N", "HPN"), ("S", "HPS"), ("E", "HPE"), ("W", "HPW"), ("Centre", "ON"))
_POINTCOR_NAMES = ("north", "south", "east", "west", "cen", "hpbw", "dirname")


class PointingProcessingError(RuntimeError):
    """Cal_point_check.py could not process the scan (not a Gaussian non-convergence). Carries what was computed."""

    def __init__(self, message: str, spectra: Optional[Dict[str, Dict[str, np.ndarray]]] = None,
                 powers: Optional[Dict[str, float]] = None) -> None:
        super().__init__(message)
        self.spectra = spectra or {}
        self.powers = powers or {}


@dataclass(frozen=True)
class ProcessedPointing:
    """pointcor() result plus the corrected spectra it was derived from and the real Sig_point check (condition B)."""

    result: PointingResult
    spectra: Dict[str, Dict[str, np.ndarray]]  # role -> {"Vlsr", "ave_pol"}: bandpass-corrected, flattened, averaged
    snr: SignalToNoiseCheck
    mode: str
    peak_velocity_kms: float
    half_width_channels: int


def _import_cal_point_check() -> Any:
    """Import clc's Cal_point_check lazily, as a flat module (it does ``import Point_cor as Pc`` etc.)."""
    import matplotlib

    matplotlib.use("Agg")
    clc_dir = Path(__file__).resolve().parent.parent / "clc"
    if str(clc_dir) not in sys.path:
        sys.path.append(str(clc_dir))
    return importlib.import_module(CAL_POINT_MODULE)


@contextmanager
def _swapped(module: Any, **replacements: Any) -> Any:
    """Temporarily replace module attributes (only the module object named is affected), always restoring them."""
    originals = {name: getattr(module, name) for name in replacements}
    for name, value in replacements.items():
        setattr(module, name, value)
    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(module, name, value)


def _processed_spectra(record: Mapping[str, Any]) -> Dict[str, Dict[str, np.ndarray]]:
    sig = record.get("sig")
    if not sig:
        return {}
    return {role: {"Vlsr": sig["vlsr"], "ave_pol": amplitude} for role, amplitude in zip(ROLES, sig["amps"])}


def compute_pointing_from_scan(
    scan_paths: Mapping[str, str], reference_path: str, mode: str, blocks: Sequence[Mapping[str, Any]],
    baseline_vlsr: Any, peak_vel: float, half_width: int, dirname: str, plot_dir: Optional[Path] = None,
) -> ProcessedPointing:
    """Run Cal_point_check.py on one pointing scan using the bandpass mode and baseline regions of Pages 03/04.

    Args:
        scan_paths: ROLES (N, S, E, W, Centre) -> FITS path of the scan's HPN / HPS / HPE / HPW / on-source file.
        reference_path: the scan's second on-source file (Frequency Switch) or pointing OFF file (Position Switch).
        mode: Page 03's mode, "Frequency Switch" or "Position Switch" -- selects calculate_pointing_corr_freq / _pos.
        blocks: committed Page 04 flat baseline regions (their masks are what Flat_base flattens with).
        baseline_vlsr: the Page 03 corrected velocity axis those regions were selected on.
        peak_vel: line velocity (km/s) -- must be a channel of the corrected axis (Sig_point compares Vlsr == peak_vel).
        half_width: channels either side of the peak that fit_max() fits.
        dirname: names the PDFs the module saves (first 8 characters = the observation date).
        plot_dir: folder for those PDFs; None skips saving them.

    Raises:
        ValueError: missing inputs. PointingFitError: a Gaussian fit did not converge (carries partial curves).
        PointingProcessingError: anything else going wrong inside the clc module (carries the spectra computed so far).
    """
    if mode not in MODE_FUNCTIONS:
        raise ValueError(f"Unknown bandpass mode {mode!r}; expected one of {list(MODE_FUNCTIONS)}.")
    for role in ROLES:
        if not scan_paths.get(role):
            raise ValueError(f"The {role} file of the pointing scan is missing.")
    if not reference_path:
        raise ValueError(f"The {REFERENCE_POSITION[mode]} reference file of the pointing scan is missing.")
    if peak_vel is None or not math.isfinite(float(peak_vel)):
        raise ValueError("The peak velocity must be a finite number (km/s).")
    if isinstance(half_width, bool) or int(half_width) != half_width or int(half_width) < HALF_WIDTH_MIN:
        raise ValueError(f"The peak-fit half-width must be a whole number of channels, at least {HALF_WIDTH_MIN}.")
    from utils.baseline_polynomial_adapter import build_clc_masks

    mask, mask2, vll, vrl = build_clc_masks(baseline_vlsr, [{"start": b["start"], "end": b["end"]} for b in blocks])
    ordered = [str(scan_paths[role]) for role, _position in _SCAN_FILE_ORDER] + [str(reference_path)]
    positions = [position for _role, position in _SCAN_FILE_ORDER] + [REFERENCE_POSITION[mode]]
    # The three arrays Cal_point_check indexes: pointing flags, POSITION tags and file paths (ON first, then the
    # reference -- position-switch code reads file_list3[4], [5]; frequency-switch code selects ON with pointing == 1).
    file_list = {"pointing": np.ones(len(ordered), dtype=int)}
    file_list2, file_list3 = np.array(positions), np.array(ordered)

    cpc = _import_cal_point_check()
    function = getattr(cpc, MODE_FUNCTIONS[mode])
    stats, point = cpc.St, cpc.Pc
    sig_record: Dict[str, Any] = {}
    call_record: Dict[str, Any] = {}
    fits: List[Tuple[np.ndarray, np.ndarray]] = []
    failure: Dict[str, Optional[int]] = {"index": None}

    with _POINTCOR_LOCK:
        real_sig, real_pointcor = stats.Sig_point, point.pointcor

        def sig_spy(*args: Any) -> Any:
            answer = str(real_sig(*args))
            sig_record["sig"] = {
                "answer": answer, "amps": [np.array(a, dtype=float) for a in args[:5]],
                "vlsr": np.array(args[5], dtype=float), "mask": np.array(args[6]).copy(), "peak": float(args[7]),
            }
            return "Yes" if answer == "" else answer  # let the module compute the numbers; the GUI decides Go / No-Go

        def pointcor_spy(*args: Any, **kwargs: Any) -> Any:
            call_record["pointcor"] = {**dict(zip(_POINTCOR_NAMES, args)), **kwargs}
            return real_pointcor(*args, **kwargs)

        import matplotlib.pyplot as pyplot

        # Any clc module (Baseline.py, Flat_base.py, ...) may save its own PDF to the hard-coded "../plots/": redirect
        # pyplot.savefig itself for the duration of the call, whichever name a module imported pyplot under.
        swaps = (
            _swapped(stats, Sig_point=sig_spy),
            _swapped(point, pointcor=pointcor_spy,
                     plt=_PyplotProxy(point.plt, _redirected_savefig(point.plt, plot_dir)),
                     curve_fit=_recording_curve_fit(point.curve_fit, fits, failure)),
            _swapped(cpc, plt=_PyplotProxy(cpc.plt, _redirected_savefig(cpc.plt, plot_dir))),
            _swapped(pyplot, savefig=_redirected_savefig(SimpleNamespace(savefig=pyplot.savefig), plot_dir)),
        )
        with swaps[0], swaps[1], swaps[2], swaps[3]:
            try:
                factor, ns_offset, ew_offset = function(
                    file_list, file_list2, file_list3, mask, mask2, float(peak_vel), int(half_width),
                    vll, vrl, dirname, "Yes",  # Full_YN="Yes": close figures, no pause / sleep
                )
                if "sig" not in sig_record or "pointcor" not in call_record:
                    raise PointingProcessingError(
                        f"{CAL_POINT_MODULE}.py finished without reaching Sig_point / pointcor().",
                        _processed_spectra(sig_record),
                    )
                bound = call_record["pointcor"]
                powers = {role: float(bound[name]) for role, name in
                          zip(ROLES, ("north", "south", "east", "west", "cen"))}
                hpbw = float(bound["hpbw"])
                curves = _fit_curves(point, fits, hpbw)
                result = PointingResult(
                    correction_factor=float(factor), ns_offset_deg=float(ns_offset), ew_offset_deg=float(ew_offset),
                    hpbw_deg=hpbw, powers=powers, uncertainties=_uncertainties_from_fits(fits, float(factor), hpbw),
                    fit_curves=curves, rms_residual=_rms_residual(point, fits, powers, hpbw),
                )
            except PointingProcessingError:
                raise
            except Exception as exc:
                spectra = _processed_spectra(sig_record)
                bound = call_record.get("pointcor") or {}
                powers = {role: float(bound[name]) for role, name in
                          zip(ROLES, ("north", "south", "east", "west", "cen")) if name in bound}
                if failure["index"] is not None and failure["index"] < len(FIT_PANELS) and "hpbw" in bound:
                    axis, panels = FIT_PANELS[failure["index"]]
                    error = PointingFitError(axis, panels, exc, _fit_curves(point, fits, float(bound["hpbw"])))
                    error.spectra, error.powers = spectra, powers
                    raise error from exc
                raise PointingProcessingError(f"{type(exc).__name__}: {exc}", spectra, powers) from exc

    sig = sig_record["sig"]
    snr = _snr_from_answer(sig["answer"], sig["amps"], sig["vlsr"], sig["mask"], sig["peak"], ())
    return ProcessedPointing(result, _processed_spectra(sig_record), snr, mode, sig["peak"], int(half_width))


def signature_id(signature: Any) -> str:
    """Short stable identifier of one set of pointing inputs (scan, picked powers, beam width)."""
    return hashlib.sha256(repr(signature).encode("utf-8")).hexdigest()[:16]


def check_record(
    check: PointingCheck, result: Any, *, signature: str, accepted: bool,
    override_note: str = "", override_justification: str = "",
) -> Dict[str, Any]:
    """JSON-safe audit record stored in pipeline_data["06_pointing_correction"]["pointing_check"] (RULE-05).

    The override text is kept only for an accepted No-Go, so a Go never carries stale override wording.
    """
    uncertainties = getattr(result, "uncertainties", None) if result is not None else None
    overridden = bool(accepted and check.verdict == VERDICT_NO_GO)
    snr = check.snr
    return {
        "verdict": check.verdict,
        "threshold_sigma": check.threshold_sigma,
        "evaluated": check.evaluated,
        "overridable": check.overridable,
        "reasons": list(check.reasons),
        "failed_panels": list(check.failed_panels),
        "signature": signature,
        "accepted": bool(accepted),
        "overridden": overridden,
        "override_note": override_note if overridden else "",
        "override_justification": override_justification if overridden else "",
        "correction_factor": _finite_or_none(getattr(result, "correction_factor", None)),
        "ns_offset_deg": _finite_or_none(getattr(result, "ns_offset_deg", None)),
        "ew_offset_deg": _finite_or_none(getattr(result, "ew_offset_deg", None)),
        "ns_sigma_deg": _finite_or_none(getattr(uncertainties, "ns_sigma_deg", None)),
        "ew_sigma_deg": _finite_or_none(getattr(uncertainties, "ew_sigma_deg", None)),
        "pc_sigma": _finite_or_none(getattr(uncertainties, "pc_sigma", None)),
        "ns_ratio": _finite_or_none(check.ns_ratio),
        "snr_skipped": check.snr_skipped,
        "snr_check": None if snr is None else {
            "evaluated": snr.evaluated, "passed": snr.passed, "sig_point": snr.sig_point,
            "peak_velocity_kms": _finite_or_none(snr.peak_velocity_kms),
            "panel_snr": {role: _finite_or_none(value) for role, value in snr.panel_snr},
            "resampled": list(snr.resampled),
        },
    }
