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

import math
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

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
class PointingResult:
    """What pointcor() returned, with the inputs that produced it."""

    correction_factor: float
    ns_offset_deg: float
    ew_offset_deg: float
    hpbw_deg: float
    powers: Dict[str, float]


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
