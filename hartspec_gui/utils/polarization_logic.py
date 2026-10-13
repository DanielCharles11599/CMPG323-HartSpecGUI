# polarization_logic.py — FR-09: non-mutating Pols.py adapter and display settings.
"""Build LCP/RCP/mean/Stokes I overlays without changing pipeline spectra.

Pols.ave_pols supplies the mean. Pols.add_pols supplies the default smoothed
Stokes I (window 7, order 3). Its hard-coded filter has no off/custom-window
argument, so those two new display paths use the same sum and SciPy filter
explicitly here, never by patching CLC globals or filtering its output again.
Time/integration averaging (Pols.ave_spec) is deliberately not performed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import numpy as np
from scipy.signal import savgol_filter

DEFAULT_WINDOW = 7
POLYORDER = 3
MIN_WINDOW = 5
SETTINGS_KEY = "polarization_display"
ARRAY_KEYS = ("Vlsr", "LCP", "RCP")
CLC_DIR = Path(__file__).resolve().parents[1] / "clc"


class PolarizationIntegrationError(RuntimeError):
    """The real CLC polarization module is missing or returned invalid output."""


@dataclass(frozen=True)
class PolarizationOverlay:
    """Owned display arrays; none are written back to a pipeline handoff."""

    vlsr: np.ndarray
    lcp: np.ndarray
    rcp: np.ndarray
    mean: np.ndarray
    stokes_i: np.ndarray
    smoothing_enabled: bool
    window_length: int


@lru_cache(maxsize=1)
def _load_pols() -> ModuleType:
    """Import the exact deployed clc/Pols.py lazily, without changing sys.path.

    Returns:
        The original module, cached per process. No scientific function is
        replaced. CLC's unused pyplot import is kept headless on first load.
    """
    path = CLC_DIR / "Pols.py"
    if not path.is_file():
        raise PolarizationIntegrationError(f"FR-09 requires the original CLC module: {path}")
    try:
        import matplotlib

        if "matplotlib.pyplot" not in sys.modules:
            matplotlib.use("Agg")
        spec = importlib.util.spec_from_file_location("_hartspec_fr09_pols", path)
        if spec is None or spec.loader is None:
            raise ImportError("No Python module loader is available.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except (ImportError, OSError, SyntaxError) as exc:
        raise PolarizationIntegrationError(f"Cannot import clc/Pols.py: {exc}") from exc
    if not all(callable(getattr(module, name, None)) for name in ("ave_pols", "add_pols")):
        raise PolarizationIntegrationError("clc/Pols.py must expose ave_pols() and add_pols().")
    return module


def validated_spectrum(spectrum: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """Copy finite, aligned 1-D arrays; reject rather than repair invalid inputs.

    Args:
        spectrum: A Vlsr/LCP/RCP mapping from the existing pipeline.
    Returns:
        Three independent float64 arrays, preserving channel order and length.
    Raises:
        ValueError: Missing, empty, masked, complex, non-finite or misaligned data.
    """
    if not isinstance(spectrum, Mapping):
        raise ValueError("A Vlsr/LCP/RCP spectrum mapping is required.")
    arrays = {}
    for key in ARRAY_KEYS:
        if key not in spectrum:
            raise ValueError(f"Spectrum is missing {key}.")
        value = spectrum[key]
        if np.ma.isMaskedArray(value) and np.any(np.ma.getmaskarray(value)):
            raise ValueError(f"{key} contains masked channels; masks cannot be discarded.")
        if np.iscomplexobj(value):
            raise ValueError(f"{key} must contain real values.")
        try:
            array = np.asarray(value, dtype=float)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{key} must contain numeric values.") from exc
        if array.ndim != 1 or array.size == 0:
            raise ValueError(f"{key} must be a non-empty one-dimensional array.")
        if not np.all(np.isfinite(array)):
            raise ValueError(f"{key} contains NaN or infinite values.")
        arrays[key] = array.copy()
    if len({array.size for array in arrays.values()}) != 1:
        raise ValueError("Vlsr, LCP and RCP must have the same channel count.")
    return arrays


def validate_window(window_length: int, n_channels: int, *, smoothing_enabled: bool) -> int:
    """Validate a centered odd window for the fixed CLC order-3 filter.

    A retained setting may exceed the data length only while smoothing is off.
    Even windows are disallowed by this GUI's centered-window convention.
    """
    if isinstance(window_length, bool) or not isinstance(window_length, (int, np.integer)):
        raise ValueError("Smoothing window length must be an integer.")
    window = int(window_length)
    if window < MIN_WINDOW or window % 2 == 0:
        raise ValueError("Smoothing window length must be odd and at least 5 (polynomial order 3).")
    if smoothing_enabled and window > n_channels:
        raise ValueError(f"Smoothing window {window} exceeds the {n_channels} available channels.")
    return window


def build_polarization_overlay(
    spectrum: Mapping[str, Any], *, smoothing_enabled: bool = False, window_length: int = DEFAULT_WINDOW,
) -> PolarizationOverlay:
    """Calculate the four FR-09 display traces on independent copies.

    Args:
        spectrum: Current baseline or calibrated Vlsr/LCP/RCP arrays.
        smoothing_enabled: Apply SG once to Stokes I only; other traces remain
            unsmoothed references, matching Pols.ave_pols/add_pols semantics.
        window_length: Odd channel count, at least 5; default 7 from Pols.py.
    Returns:
        LCP, RCP, the per-channel mean and I = LCP + RCP (optionally smoothed).
    """
    if not isinstance(smoothing_enabled, bool):
        raise ValueError("Smoothing enabled must be a boolean.")
    arrays = validated_spectrum(spectrum)
    window = validate_window(window_length, arrays["Vlsr"].size, smoothing_enabled=smoothing_enabled)
    pols = _load_pols()
    work = {key: value.copy() for key, value in arrays.items()}
    try:
        with np.errstate(over="raise", invalid="raise"):
            averaged = pols.ave_pols(work)
            mean = np.asarray(averaged["ave_pol"], dtype=float).copy()
            if smoothing_enabled and window == DEFAULT_WINDOW:
                # add_pols already filters I: never feed its result to SG again.
                stokes_i = np.asarray(pols.add_pols(work)["I"], dtype=float).copy()
            else:
                stokes_i = arrays["RCP"] + arrays["LCP"]
                if smoothing_enabled:
                    stokes_i = savgol_filter(stokes_i, window, POLYORDER, mode="interp")
    except (KeyError, TypeError, ValueError, FloatingPointError, OverflowError) as exc:
        raise PolarizationIntegrationError(f"Polarization calculation failed: {exc}") from exc
    for name, array in (("Mean", mean), ("Stokes I", stokes_i)):
        if array.shape != arrays["Vlsr"].shape or not np.all(np.isfinite(array)):
            raise PolarizationIntegrationError(f"{name} returned invalid or misaligned display values.")
    return PolarizationOverlay(
        arrays["Vlsr"], arrays["LCP"], arrays["RCP"], mean, stokes_i, smoothing_enabled, window,
    )


def spectrum_identity(spectrum: Mapping[str, Any]) -> str:
    """Fingerprint all three display inputs; no metadata or array cache is stored."""
    digest = hashlib.sha256()
    for key, array in validated_spectrum(spectrum).items():
        digest.update(key.encode("ascii"))
        digest.update(array.size.to_bytes(8, "little"))
        digest.update(array.astype("<f8", copy=False).tobytes())
    return digest.hexdigest()


def restore_display_settings(saved: Any, n_channels: int) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Read JSON view preferences and report every correction to invalid settings.

    Args:
        saved: The optional polarization_display object from a Stage 05 record.
        n_channels: Current spectrum length; short spectra remain viewable.
    Returns:
        Valid toggle/window settings plus notices for malformed or changed input.
        Smoothing defaults off and is never enabled by a truthy string.
    """
    notes = []
    if saved is None:
        saved = {}
    elif not isinstance(saved, Mapping):
        notes.append("Invalid saved polarization settings were reset.")
        saved = {}
    if saved and (saved.get("schema_version") != 1 or saved.get("polyorder") != POLYORDER):
        notes.append("Unsupported saved polarization settings were reset.")
        saved = {}
    enabled = saved.get("smoothing_enabled", False)
    if not isinstance(enabled, bool):
        notes.append("Invalid saved smoothing toggle was reset to off.")
        enabled = False
    maximum = n_channels if n_channels % 2 else n_channels - 1
    default = min(DEFAULT_WINDOW, maximum) if maximum >= MIN_WINDOW else MIN_WINDOW
    window = saved.get("window_length", default)
    try:
        window = validate_window(window, n_channels, smoothing_enabled=False)
    except ValueError:
        notes.append("Invalid saved window length was reset for the current spectrum.")
        window = default
    if n_channels < MIN_WINDOW:
        if enabled:
            notes.append("Smoothing was turned off: at least 5 channels are required.")
        enabled, window = False, MIN_WINDOW
    elif window > maximum:
        notes.append(f"Saved window {window} exceeds this spectrum; reset to {default} channels.")
        window = default
    return {"smoothing_enabled": enabled, "window_length": int(window)}, tuple(notes)


def display_record(
    settings: Mapping[str, Any], *, source_key: str, fingerprint: str, intensity_unit: str,
) -> dict[str, Any]:
    """Build JSON-safe view metadata, never a ninth stage or a derived spectrum."""
    return {
        "schema_version": 1,
        "smoothing_enabled": bool(settings["smoothing_enabled"]),
        "window_length": int(settings["window_length"]),
        "polyorder": POLYORDER,
        "smoothing_target": "Stokes I",
        "display_only": True,
        "source_key": source_key,
        "source_fingerprint": fingerprint,
        "intensity_unit": intensity_unit,
        "mean_formula": "(LCP + RCP) / 2",
        "stokes_i_formula": "LCP + RCP",
    }
