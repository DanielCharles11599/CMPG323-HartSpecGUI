# export_preview_logic.py — FR-18: source-faithful RMS/peak statistics for the Page 08 preview.
#
# The legacy CLC computes its final RMS on Stokes I, not independently on LCP/RCP:
#   1. baseline-selected channels define mask/mask3/vll/vrl (Blocks.py),
#   2. the LCP baseline mask is sigma-clipped with Stats_manager.Add_Remove_feature,
#   3. LCP/RCP are multiplied by pointing correction and their own PSS values,
#   4. Stokes I = Savitzky-Golay(LCP + RCP, window=7, order=3) (Pols.py),
#   5. Stats_manager.rms_stn applies Add_Remove_feature again and reports RMS plus
#      the maximum Stokes-I value inside mask3 == 0.
#
# This module extracts that numeric path without calling the plotting/file-writing
# side effects in Stats_manager.rms_stn. It never mutates session/bridge arrays.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

import numpy as np
from scipy.signal import savgol_filter

from utils.baseline_polynomial_adapter import build_clc_masks


BASELINE_STAGE_KEY = "04_baseline_editor"
PSS_STAGE_KEY = "05_calibration_dashboard"
POINTING_STAGE_KEY = "06_pointing_correction"
_REQUIRED_KEYS = ("Vlsr", "LCP", "RCP")
_EXPECTED_SELECTION_SEMANTICS = "flat_baseline_fit_regions_v2"


class ExportPreviewUnavailable(ValueError):
    """Raised when the current reduction does not contain safe inputs for FR-18 statistics."""


@dataclass(frozen=True)
class ExportPreviewStats:
    """Numerical values rendered by the FR-18 calibrated preview."""

    vlsr: np.ndarray
    lcp_jy: np.ndarray
    rcp_jy: np.ndarray
    stokes_i_jy: np.ndarray
    rms_jy: float
    peak_jy: float
    peak_velocity_kms: float
    vll: float
    vrl: float
    baseline_channel_count: int
    final_noise_channel_count: int


@dataclass(frozen=True)
class ExportPreviewResult:
    """Success/error wrapper used by Page 08 so unavailable statistics never crash export."""

    stats: Optional[ExportPreviewStats]
    reason: str = ""

    @property
    def available(self) -> bool:
        """True when a complete preview was calculated."""
        return self.stats is not None


def _finite_1d(values: Any, name: str) -> np.ndarray:
    """Return a finite, non-empty one-dimensional float copy."""
    try:
        array = np.asarray(values, dtype=float).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise ExportPreviewUnavailable(f"{name} is not numeric.") from exc
    if array.size == 0 or not np.all(np.isfinite(array)):
        raise ExportPreviewUnavailable(f"{name} must contain finite spectrum values.")
    return array.copy()


def _spectrum_arrays(spectrum: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Validate the Vlsr/LCP/RCP arrays required by the legacy CLC path."""
    if not isinstance(spectrum, Mapping):
        raise ExportPreviewUnavailable("The baseline-flattened spectrum is unavailable.")
    missing = [key for key in _REQUIRED_KEYS if key not in spectrum]
    if missing:
        raise ExportPreviewUnavailable("The baseline-flattened spectrum is missing: " + ", ".join(missing))
    vlsr = _finite_1d(spectrum["Vlsr"], "Vlsr")
    lcp = _finite_1d(spectrum["LCP"], "LCP")
    rcp = _finite_1d(spectrum["RCP"], "RCP")
    if len({vlsr.size, lcp.size, rcp.size}) != 1:
        raise ExportPreviewUnavailable("Vlsr, LCP and RCP must contain the same number of channels.")
    if vlsr.size < 7:
        raise ExportPreviewUnavailable("The CLC Stokes-I smoothing step requires at least seven channels.")
    if np.any(np.diff(vlsr) < 0):
        raise ExportPreviewUnavailable("The CLC RMS routine requires an ascending Vlsr grid.")
    return vlsr, lcp, rcp


def _finite_positive(value: Any, label: str) -> float:
    """Return a finite positive scalar used by the CLC final-calibration path."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExportPreviewUnavailable(f"{label} is not recorded.") from exc
    if not np.isfinite(number) or number <= 0:
        raise ExportPreviewUnavailable(f"{label} must be finite and positive.")
    return number


def _clc_mask3(vlsr: np.ndarray, vll: float, vrl: float) -> np.ndarray:
    """Reproduce Blocks.py's full signal-envelope mask (0 inside vll..vrl, 1 outside)."""
    mask3 = np.ones(vlsr.size, dtype=int)
    inside = np.logical_and(vlsr >= vll, vlsr <= vrl)
    mask3[np.where(inside)] = 0
    if not np.any(mask3 == 0):
        raise ExportPreviewUnavailable("No channels fall inside the recorded CLC baseline envelope.")
    return mask3


def _clc_bounds(vlsr: np.ndarray, mask3: np.ndarray, vll: float, vrl: float) -> tuple[int, int]:
    """Reproduce the boundary search in Stats_manager.Add_Remove_feature, with explicit validation."""
    vl: Optional[int] = None
    vr: Optional[int] = None
    for index in range(0, len(mask3) - 1, 1):
        if vlsr[index] <= vll and vlsr[index + 1] >= vll:
            vl = index
        if vlsr[index] <= vrl and vlsr[index + 1] >= vrl and vrl < vlsr[len(mask3) - 1]:
            vr = index
        if vlsr[len(mask3) - 1] < vrl:
            vr = len(mask3) - 2
    if vl is None or vr is None or vr <= vl:
        raise ExportPreviewUnavailable("Recorded baseline limits do not map onto the current Vlsr grid.")
    return vl, vr


def clc_add_remove_feature(
    amplitude: Any,
    vlsr: Any,
    mask: Any,
    mask3: Any,
    vll: float,
    vrl: float,
) -> tuple[float, np.ma.MaskedArray, np.ndarray]:
    """GUI-safe numerical extraction of Stats_manager.Add_Remove_feature.

    The legacy function mutates ``mask`` in place. This adapter always copies it
    first, preserving Page 04/session state while retaining the same two-pass
    thresholds and final RMS definition.
    """
    amp = _finite_1d(amplitude, "Amplitude")
    velocity = _finite_1d(vlsr, "Vlsr")
    current_mask = np.asarray(mask, dtype=int).reshape(-1).copy()
    envelope_mask = np.asarray(mask3, dtype=int).reshape(-1).copy()
    if not (amp.size == velocity.size == current_mask.size == envelope_mask.size):
        raise ExportPreviewUnavailable("CLC RMS arrays and masks must have identical channel counts.")
    if not np.any(current_mask == 0):
        raise ExportPreviewUnavailable("No recorded baseline channels are available for RMS estimation.")

    initial_noise = np.ma.array(amp, mask=current_mask)
    initial_rms = float(np.sqrt(np.ma.mean(initial_noise**2)))
    if not np.isfinite(initial_rms):
        raise ExportPreviewUnavailable("The recorded baseline channels do not produce a finite RMS value.")
    vl, vr = _clc_bounds(velocity, envelope_mask, float(vll), float(vrl))

    # Stats_manager.Add_Remove_feature performs the same threshold pass twice,
    # both times using the original RMS value calculated above.
    for _ in range(2):
        for index in range(vl, vr, 1):
            if current_mask[index] == 0 and abs(amp[index]) >= 2.5 * initial_rms:
                current_mask[index] = 1
            elif envelope_mask[index] == 1 and abs(amp[index]) <= 1.2 * initial_rms:
                current_mask[index] = 0

    noise = np.ma.array(amp, mask=current_mask)
    rms = float(np.sqrt(np.ma.mean(noise**2)))
    if not np.isfinite(rms):
        raise ExportPreviewUnavailable("CLC feature masking left no finite channels for RMS estimation.")
    return rms, noise, current_mask


def build_clc_export_preview(
    spectrum: Mapping[str, Any],
    blocks: Sequence[Mapping[str, Any]],
    *,
    pss_lcp_jy_per_k: Any,
    pss_rcp_jy_per_k: Any,
    pointing_factor: Any,
) -> ExportPreviewStats:
    """Calculate the FR-18 RMS/peak preview following HartSpec.py's final-spectrum path.

    ``spectrum`` must be the Page 04 baseline-flattened LCP/RCP spectrum in K.
    The output LCP/RCP/Stokes-I arrays are preview-only Jy arrays; the input is
    never changed and no scientific export/session data is written.
    """
    vlsr, lcp_k, rcp_k = _spectrum_arrays(spectrum)
    pss_lcp = _finite_positive(pss_lcp_jy_per_k, "LCP PSS")
    pss_rcp = _finite_positive(pss_rcp_jy_per_k, "RCP PSS")
    pc = _finite_positive(pointing_factor, "Pointing correction factor")

    try:
        initial_mask, _rcp_mask, vll, vrl = build_clc_masks(vlsr, blocks)
    except Exception as exc:  # adapter uses its own integration exception type
        raise ExportPreviewUnavailable(f"Recorded baseline regions are not usable: {exc}") from exc
    mask3 = _clc_mask3(vlsr, vll, vrl)

    # Blocks.py sigma-clips the flattened LCP mask before HartSpec.py later reuses
    # that same mask in rms_stn(). RCP has its own mask, but rms_stn receives the
    # LCP mask specifically.
    _lcp_rms_k, _lcp_noise, lcp_feature_mask = clc_add_remove_feature(
        lcp_k, vlsr, initial_mask, mask3, vll, vrl
    )

    # HartSpec.py: LCP/RCP * pointing correction, then their own PSS values.
    lcp_jy = lcp_k * pc * pss_lcp
    rcp_jy = rcp_k * pc * pss_rcp

    # Pols.add_pols(): I = RCP + LCP, then savgol_filter(I, 7, 3).
    stokes_i = savgol_filter(rcp_jy + lcp_jy, 7, 3)

    rms_jy, _noise, final_mask = clc_add_remove_feature(
        stokes_i, vlsr, lcp_feature_mask, mask3, vll, vrl
    )

    eligible = np.flatnonzero(mask3 == 0)
    if eligible.size == 0:
        raise ExportPreviewUnavailable("No channels are available for the CLC peak calculation.")
    local = int(np.argmax(stokes_i[eligible]))
    peak_index = int(eligible[local])
    peak_jy = float(stokes_i[peak_index])
    peak_velocity = float(vlsr[peak_index])

    return ExportPreviewStats(
        vlsr=vlsr.copy(),
        lcp_jy=lcp_jy.copy(),
        rcp_jy=rcp_jy.copy(),
        stokes_i_jy=np.asarray(stokes_i, dtype=float).copy(),
        rms_jy=float(rms_jy),
        peak_jy=peak_jy,
        peak_velocity_kms=peak_velocity,
        vll=float(vll),
        vrl=float(vrl),
        baseline_channel_count=int(np.count_nonzero(initial_mask == 0)),
        final_noise_channel_count=int(np.count_nonzero(final_mask == 0)),
    )


def baseline_spectrum_for_preview(
    state: Mapping[str, Any],
    *,
    read_bridge: Callable[[str], Mapping[str, Any] | None],
    fingerprint: Callable[[Mapping[str, Any]], str],
) -> tuple[Optional[Mapping[str, Any]], str]:
    """Return the current Page 04 flattened spectrum, rejecting a stale bridge."""
    session_id = str(state.get("session_id", ""))
    bridge = read_bridge(session_id) or {}
    if not isinstance(bridge, Mapping):
        return None, "The Page 04 baseline bridge is unreadable; revisit Baseline Block Editor."
    flattened = bridge.get("flattened_spectrum")
    if not isinstance(flattened, Mapping):
        return None, "Complete the Page 04 baseline fit before RMS/peak statistics are available."

    current_bandpass = state.get("bandpass_corrected_spectrum")
    if isinstance(current_bandpass, Mapping):
        try:
            if bridge.get("spectrum_fingerprint") != fingerprint(current_bandpass):
                return None, "The saved Page 04 baseline result no longer matches the current bandpass spectrum."
        except (KeyError, TypeError, ValueError):
            return None, "The Page 04 baseline result could not be verified against the current bandpass spectrum."
    return flattened, ""


def preview_from_pipeline(
    state: Mapping[str, Any],
    *,
    read_bridge: Callable[[str], Mapping[str, Any] | None],
    fingerprint: Callable[[Mapping[str, Any]], str],
) -> ExportPreviewResult:
    """Build a source-faithful preview from committed Pages 04–06 data, or explain why it is unavailable."""
    pipeline = state.get("pipeline_data") or {}
    if not isinstance(pipeline, Mapping):
        return ExportPreviewResult(None, "Pipeline parameters are unavailable.")

    baseline = pipeline.get(BASELINE_STAGE_KEY) or {}
    if not isinstance(baseline, Mapping):
        return ExportPreviewResult(None, "Page 04 baseline parameters are unavailable.")
    if baseline.get("selection_semantics") != _EXPECTED_SELECTION_SEMANTICS:
        return ExportPreviewResult(
            None,
            "The saved baseline selection semantics are missing or legacy; revisit Page 04 before calculating CLC RMS.",
        )
    blocks = baseline.get("blocks") or []
    if not isinstance(blocks, Sequence) or isinstance(blocks, (str, bytes)) or not blocks:
        return ExportPreviewResult(None, "No committed Page 04 baseline regions are available.")

    pss_stage = pipeline.get(PSS_STAGE_KEY) or {}
    pss = pss_stage.get("pss") if isinstance(pss_stage, Mapping) else None
    if not isinstance(pss, Mapping):
        return ExportPreviewResult(None, "Page 05 LCP/RCP PSS values are required for the calibrated preview.")

    pointing = pipeline.get(POINTING_STAGE_KEY) or {}
    if not isinstance(pointing, Mapping) or str(pointing.get("input_source", "")).upper().startswith("MOCK"):
        return ExportPreviewResult(
            None, "A real Page 06 pointing correction is required for the calibrated preview."
        )

    flattened, reason = baseline_spectrum_for_preview(state, read_bridge=read_bridge, fingerprint=fingerprint)
    if flattened is None:
        return ExportPreviewResult(None, reason)

    try:
        stats = build_clc_export_preview(
            flattened,
            blocks,
            pss_lcp_jy_per_k=pss.get("lcp_window_mean"),
            pss_rcp_jy_per_k=pss.get("rcp_window_mean"),
            pointing_factor=pointing.get("correction_factor"),
        )
    except ExportPreviewUnavailable as exc:
        return ExportPreviewResult(None, str(exc))
    return ExportPreviewResult(stats, "")
