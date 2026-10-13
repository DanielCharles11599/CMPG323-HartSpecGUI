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
import math
import sys
import threading
from dataclasses import dataclass
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
        pending: List[Dict[str, str]] = []
        current: Dict[str, str] = {}
        for filename in blocks[block_name]:
            role = _role_of(lookup(filename))
            if role is None:
                continue
            if role in current:  # same direction again => the previous scan is finished
                pending.append(current)
                current = {}
            current[role] = filename
        if current:
            pending.append(current)
        for number, files in enumerate(pending, start=1):
            if len(files) == len(ROLES):
                scans.append(PointingScan(block=block_name, number=number, files=files))
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

    ``uncertainties`` stays None until they can be sourced: pointcor() returns only (factor, ns, ew), so the fit
    covariance is not visible to the wrapper.
    # TODO: confirm against design -- needs clc/Point_cor.py's fit code to extract the uncertainties safely.
    """

    correction_factor: float
    ns_offset_deg: float
    ew_offset_deg: float
    hpbw_deg: float
    powers: Dict[str, float]
    uncertainties: Optional[PointingUncertainties] = None


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
    with _POINTCOR_LOCK:
        original_plt = pointcor_module.plt
        pointcor_module.plt = _PyplotProxy(original_plt, _redirected_savefig(original_plt, plot_dir))
        try:
            factor, ns_offset, ew_offset = pointcor_module.pointcor(
                hpbw=float(hpbw_deg), dirname=dirname, **arguments
            )
        finally:
            pointcor_module.plt = original_plt

    return PointingResult(
        correction_factor=float(factor),
        ns_offset_deg=float(ns_offset),
        ew_offset_deg=float(ew_offset),
        hpbw_deg=float(hpbw_deg),
        powers={role: float(powers[role]) for role in ROLES},
    )


# ---------------------------------------------------------------------------
# FR-13: 2.5-sigma Go / No-Go quality check (pure -- no Streamlit)
# ---------------------------------------------------------------------------

THRESHOLD_SIGMA = 2.5
VERDICT_GO = "Go"
VERDICT_NO_GO = "No-Go"


@dataclass(frozen=True)
class PointingCheck:
    """Outcome of the pointing quality check.

    ``evaluated`` is False when the 2.5-sigma test could not run (no usable uncertainties, or the fit failed); the
    verdict is then No-Go. ``overridable`` is False only when there is no correction factor to apply at all.
    """

    verdict: str
    threshold_sigma: float
    reasons: Tuple[str, ...]
    evaluated: bool
    overridable: bool
    ns_ratio: Optional[float] = None
    ew_ratio: Optional[float] = None


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


def evaluate_pointing_check(result: Any, threshold_sigma: float = THRESHOLD_SIGMA) -> PointingCheck:
    """Go only if both |NS offset| and |EW offset| are strictly below ``threshold_sigma`` x their sigma.

    # TODO: confirm against design -- the requirement text names |NS_off| only; EW is tested the same way here, and
    # the exact sigma definition belongs to Stats_manager.Sig_point (not available in this session).
    Missing / unusable uncertainties give a No-Go (cannot verify), never a silent Go.
    """
    uncertainties = getattr(result, "uncertainties", None)
    ns_sigma = _usable_sigma(getattr(uncertainties, "ns_sigma_deg", None))
    ew_sigma = _usable_sigma(getattr(uncertainties, "ew_sigma_deg", None))
    if ns_sigma is None or ew_sigma is None:
        return PointingCheck(
            VERDICT_NO_GO, threshold_sigma,
            ("The fit uncertainties needed for the %gσ check are not available, so the offsets cannot be "
             "verified." % threshold_sigma,),
            evaluated=False, overridable=True,
        )
    reasons: List[str] = []
    ratios: Dict[str, float] = {}
    for label, offset, sigma in (("NS", result.ns_offset_deg, ns_sigma), ("EW", result.ew_offset_deg, ew_sigma)):
        ratio = abs(float(offset)) / sigma
        ratios[label] = ratio
        if not ratio < threshold_sigma:  # also catches NaN
            reasons.append(f"|{label} offset| = {abs(float(offset)):.4f}° is {ratio:.2f}σ, "
                           f"not below {threshold_sigma:g}σ.")
    return PointingCheck(
        VERDICT_GO if not reasons else VERDICT_NO_GO, threshold_sigma, tuple(reasons),
        evaluated=True, overridable=True, ns_ratio=ratios["NS"], ew_ratio=ratios["EW"],
    )


def failed_fit_check(message: str, threshold_sigma: float = THRESHOLD_SIGMA) -> PointingCheck:
    """No-Go for a fit that did not converge. Not overridable: there is no correction factor to apply."""
    return PointingCheck(
        VERDICT_NO_GO, threshold_sigma, (f"The pointing fit did not converge: {message}",),
        evaluated=False, overridable=False,
    )


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
    return {
        "verdict": check.verdict,
        "threshold_sigma": check.threshold_sigma,
        "evaluated": check.evaluated,
        "overridable": check.overridable,
        "reasons": list(check.reasons),
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
        "ew_ratio": _finite_or_none(check.ew_ratio),
    }
