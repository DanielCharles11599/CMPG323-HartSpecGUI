# fitting_inputs.py — FR-14–17 / FR-18: pure helpers for the Page 07 graphs and the Page 08 export.
#
# Holds the arithmetic the system owners specified, in one place so Pages 06, 07 and 08 cannot drift apart:
#   * pair average            -- for every LCP/RCP pair of points, (LCP + RCP) / 2, plus the overall mean of those.
#   * Graph 3                 -- [(LCP + RCP) * PSS] + Pointing Correction   (formula exactly as given by the owner)
#   * pointing product        -- (LCP + RCP) * Pointing Correction           (Page 06 graph)
#
# Where the inputs come from:
#   * PSS: Page 05 stores the +/-15-day window means of the LCP and RCP PSS (Jy/K) in
#     pipeline_data["05_calibration_dashboard"]["pss"]. Graph 3 needs ONE number, so PSS = mean of those two.
#     # TODO: confirm against design -- single PSS = mean(LCP window mean, RCP window mean) is our reading of
#     # "* PSS"; the alternative is LCP*PSS_lcp + RCP*PSS_rcp.
#   * Pointing Correction: Page 06 stores the pointcor() correction factor in
#     pipeline_data["06_pointing_correction"]["correction_factor"].
#   # TODO: confirm against design -- pointcor() returns a multiplicative factor (>= 1, "corrective factor for peak
#   # amplitude"). Graph 3 ADDS it, exactly as the system owner wrote the formula, which shifts the whole spectrum by
#   # a constant ~1 Jy instead of rescaling it. Implemented as specified; flagged for the owners.
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

import numpy as np

PSS_STAGE_KEY = "05_calibration_dashboard"
POINTING_STAGE_KEY = "06_pointing_correction"
GRAPH3_UNIT = "Jy"  # K (pre-calibration LCP/RCP) x Jy/K (PSS)
GRAPH3_FORMULA = "[(LCP + RCP) * PSS] + Pointing Correction"


@dataclass(frozen=True)
class PssValue:
    """The single PSS value used for Graph 3, and the Page 05 numbers it was built from."""

    value: float
    lcp_mean: float
    rcp_mean: float
    frequency: str
    window_days: int


def _finite_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def pss_from_pipeline(pipeline_data: Optional[Mapping[str, Any]]) -> Optional[PssValue]:
    """PSS for Graph 3 from Page 05's saved result, or None if Page 05 has no usable LCP *and* RCP window mean."""
    stage = (pipeline_data or {}).get(PSS_STAGE_KEY) or {}
    pss = stage.get("pss") if isinstance(stage, Mapping) else None
    if not isinstance(pss, Mapping):
        return None
    lcp_mean = _finite_float(pss.get("lcp_window_mean"))
    rcp_mean = _finite_float(pss.get("rcp_window_mean"))
    if lcp_mean is None or rcp_mean is None:
        return None
    return PssValue(
        value=(lcp_mean + rcp_mean) / 2.0,
        lcp_mean=lcp_mean,
        rcp_mean=rcp_mean,
        frequency=str(pss.get("frequency", "")),
        window_days=int(pss.get("window_days", 15) or 15),
    )


def pointing_factor_from_pipeline(pipeline_data: Optional[Mapping[str, Any]]) -> Optional[float]:
    """Pointing correction factor saved by Page 06, or None.

    Sessions saved before Page 06 used real scans carry only display strings and an "input_source" starting with
    "MOCK"; those are deliberately ignored so mock numbers can never reach a graph or an export.
    """
    stage = (pipeline_data or {}).get(POINTING_STAGE_KEY) or {}
    if not isinstance(stage, Mapping) or str(stage.get("input_source", "")).upper().startswith("MOCK"):
        return None
    return _finite_float(stage.get("correction_factor"))


def pair_average(lcp: Any, rcp: Any) -> Tuple[np.ndarray, float]:
    """(LCP + RCP) / 2 for every pair of points, and the overall mean of those averages (NaN channels ignored)."""
    lcp_array = np.asarray(lcp, dtype=float)
    rcp_array = np.asarray(rcp, dtype=float)
    average = (lcp_array + rcp_array) / 2.0
    overall = float(np.nanmean(average)) if average.size and not np.all(np.isnan(average)) else float("nan")
    return average, overall


def graph3(lcp: Any, rcp: Any, pss: float, pointing_correction: float) -> np.ndarray:
    """Graph 3, exactly as specified by the system owner: [(LCP + RCP) * PSS] + Pointing Correction."""
    return (np.asarray(lcp, dtype=float) + np.asarray(rcp, dtype=float)) * pss + pointing_correction


def pointing_product(lcp: Any, rcp: Any, pointing_correction: float) -> np.ndarray:
    """Page 06 graph: (LCP + RCP) * Pointing Correction."""
    return (np.asarray(lcp, dtype=float) + np.asarray(rcp, dtype=float)) * pointing_correction


def graph3_source_key(spectrum_source_key: str, pss: float, pointing_correction: float) -> str:
    """Identity of the Graph 3 curve. A saved fit is only valid for the exact spectrum + PSS + correction it used."""
    return f"{spectrum_source_key}|graph3|pss={pss:.6g}|pc={pointing_correction:.6g}"
