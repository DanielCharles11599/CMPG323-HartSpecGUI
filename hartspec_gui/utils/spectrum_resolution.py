# spectrum_resolution.py — one answer to "which spectrum is current?" for Pages 07 and 08.
#
# Replaces the two page-local copies of _resolve_spectrum() (they had already begun to drift: different
# synthetic placeholders, and neither checked whether the Page 4 bridge still matched the current spectrum).
#
# Pure: takes a mapping (st.session_state in the app, a plain dict in tests) and two injected callables
# (baseline_editor_bridge.read_bridge / .spectrum_fingerprint), so it needs no Streamlit runtime.
#
# Fallback chain, most-processed source first:
#   1. session_state["calibrated_spectrum"] -- written by Page 05
#      (calibration_logic.apply_calibration_to_spectrum)
#   2. Page 4 bridge "flattened_spectrum" (baseline-flattened, not calibrated) -- REJECTED if its fingerprint
#      no longer matches the current Page 3 spectrum
#   3. first entry of session_state["loaded_spectra"] (raw, Page 02)
#   4. synthetic placeholder -- development only; callers must refuse to save/export it (is_placeholder)
#
# TODO: confirm against design
#   * Units. The active loader (clc/File_check.py) does not expose the FITS TUNIT2 unit (only a commented-out
#     variant did), so "K" for pre-calibration spectra rests on the Build Spec's sample values ("8.42 K").
#   * "Jy" for calibrated spectra follows the flux convention assumed in
#     calibration_logic.apply_calibration_to_spectrum() (ATcor x PSS, PSS in Jy/K per the Technical Spec
#     glossary). That convention is itself unconfirmed against clc/Calibrate_PSS_PWR.py. If it changes, change
#     CALIBRATED_UNIT here at the same time -- this is the only place the label lives.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import numpy as np

POLARIZATIONS = ("LCP", "RCP")
_REQUIRED_KEYS = ("Vlsr", "LCP", "RCP")

SOURCE_CALIBRATED = "calibrated"
SOURCE_BASELINE = "baseline"
SOURCE_RAW = "raw"
SOURCE_PLACEHOLDER = "placeholder"

UNCALIBRATED_UNIT = "K"
CALIBRATED_UNIT = "Jy"


@dataclass(frozen=True)
class ResolvedSpectrum:
    """The spectrum a page should use, and where it came from."""

    vlsr: np.ndarray
    channels: dict[str, np.ndarray]
    source_key: str
    source_label: str
    intensity_unit: str
    notes: tuple[str, ...] = ()

    @property
    def is_placeholder(self) -> bool:
        """True for the synthetic development spectrum -- never save or export it."""
        return self.source_key == SOURCE_PLACEHOLDER

    @property
    def is_calibrated(self) -> bool:
        """True only when the Page 05 calibrated spectrum is in use."""
        return self.source_key == SOURCE_CALIBRATED


def _coerce(spectrum: Any) -> tuple[np.ndarray, dict[str, np.ndarray]] | None:
    """Return (Vlsr, {"LCP", "RCP"}) as equal-length non-empty 1-D float arrays, or None if unusable."""
    if not isinstance(spectrum, Mapping) or not all(key in spectrum for key in _REQUIRED_KEYS):
        return None
    try:
        arrays = {key: np.asarray(spectrum[key], dtype=float).reshape(-1) for key in _REQUIRED_KEYS}
    except (TypeError, ValueError):
        return None
    sizes = {a.size for a in arrays.values()}
    if len(sizes) != 1 or 0 in sizes:
        return None
    return arrays["Vlsr"], {pol: arrays[pol] for pol in POLARIZATIONS}


def _bridge_is_stale(
    bridge: Mapping[str, Any],
    current_bandpass: Any,
    fingerprint: Callable[[Mapping[str, Any]], str],
) -> bool:
    """True when the bridge was built from a different Page 3 spectrum than the current one.

    With no current Page 3 spectrum to compare against (e.g. straight after a session load) there is nothing
    to disprove the bridge, so it is not called stale. If the current spectrum exists but cannot be
    fingerprinted, the bridge cannot be verified and is treated as stale.
    """
    if _coerce(current_bandpass) is None:
        return False
    try:
        return bridge.get("spectrum_fingerprint") != fingerprint(current_bandpass)
    except (KeyError, TypeError, ValueError):
        return True


def synthetic_placeholder() -> ResolvedSpectrum:
    """Deterministic single-line spectrum so pages stay runnable standalone during development."""
    vlsr = np.linspace(-20, 20, 1024)
    rng = np.random.default_rng(42)
    line = 8.42 * np.exp(-0.5 * ((vlsr + 4.2) / (2.31 / 2.3548)) ** 2)
    return ResolvedSpectrum(
        vlsr=vlsr,
        channels={
            "LCP": line + rng.normal(0, 0.15, vlsr.size),
            "RCP": line * 0.96 + rng.normal(0, 0.15, vlsr.size),
        },
        source_key=SOURCE_PLACEHOLDER,
        source_label="Synthetic placeholder spectrum — no real session data available",
        intensity_unit=UNCALIBRATED_UNIT,
    )


def resolve_spectrum(
    session_state: Mapping[str, Any],
    *,
    read_bridge: Callable[[str], Mapping[str, Any] | None],
    fingerprint: Callable[[Mapping[str, Any]], str],
) -> ResolvedSpectrum:
    """Pick the most-processed valid spectrum available for this session (see module header for the chain).

    Args:
        session_state: st.session_state (or any mapping with the same keys).
        read_bridge: baseline_editor_bridge.read_bridge -- called with the session id.
        fingerprint: baseline_editor_bridge.spectrum_fingerprint -- hashes a Vlsr/LCP/RCP mapping.

    Returns:
        A ResolvedSpectrum. ``notes`` lists anything skipped on the way (stale bridge, malformed arrays) so the
        page can tell the user why a less-processed source is showing.
    """
    notes: list[str] = []

    calibrated_raw = session_state.get("calibrated_spectrum")
    calibrated = _coerce(calibrated_raw)
    if calibrated is not None:
        return ResolvedSpectrum(
            calibrated[0], calibrated[1], SOURCE_CALIBRATED,
            "Calibrated spectrum (Stage 05 output)", CALIBRATED_UNIT, tuple(notes),
        )
    if calibrated_raw:
        notes.append("The calibrated spectrum in this session is malformed and was ignored.")

    bridge = read_bridge(str(session_state.get("session_id", ""))) or {}
    flattened_raw = bridge.get("flattened_spectrum")
    flattened = _coerce(flattened_raw)
    if flattened is not None:
        if _bridge_is_stale(bridge, session_state.get("bandpass_corrected_spectrum"), fingerprint):
            notes.append(
                "The saved Page 4 baseline result was ignored because it no longer matches the current "
                "Page 3 spectrum. Revisit Page 4."
            )
        else:
            return ResolvedSpectrum(
                flattened[0], flattened[1], SOURCE_BASELINE,
                "Baseline-flattened spectrum (Page 4 bridge — calibration not yet applied)",
                UNCALIBRATED_UNIT, tuple(notes),
            )
    elif flattened_raw:
        notes.append("The saved Page 4 baseline result is malformed and was ignored.")

    loaded = session_state.get("loaded_spectra") or []
    raw = _coerce(loaded[0]) if loaded else None
    if raw is not None:
        return ResolvedSpectrum(
            raw[0], raw[1], SOURCE_RAW,
            "Raw loaded spectrum (Page 02 — no bandpass/baseline correction applied yet)",
            UNCALIBRATED_UNIT, tuple(notes),
        )

    placeholder = synthetic_placeholder()
    return ResolvedSpectrum(
        placeholder.vlsr, placeholder.channels, placeholder.source_key, placeholder.source_label,
        placeholder.intensity_unit, tuple(notes),
    )
