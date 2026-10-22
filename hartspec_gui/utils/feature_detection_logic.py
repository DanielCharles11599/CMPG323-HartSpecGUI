# feature_detection_logic.py — FR-08: side-effect-free CLC Add_Remove_feature feature detection.
"""Pure feature-detection helpers for the Page 04 FR-08 review panel.

The supplied ``Stats_manager.Add_Remove_feature`` routine mutates its mask in
place and emits logging warnings. This module reproduces that numerical core
literally on private copies so rendering the GUI cannot alter saved baseline
blocks, bridge state, or downstream spectra. Regression tests compare this
implementation directly with the supplied CLC function.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from utils.baseline_polynomial_adapter import CLCBaselineIntegrationUnavailable, build_clc_masks

POLARIZATIONS = ("LCP", "RCP")


class FeatureDetectionError(RuntimeError):
    """Raised when FR-08 cannot safely reproduce the CLC detection contract."""


@dataclass(frozen=True)
class FeatureEvent:
    """One contiguous set of channels whose CLC mask classification changed."""

    polarization: str
    change: str
    start_velocity: float
    end_velocity: float
    peak_velocity: float
    peak_amplitude: float
    channel_count: int


@dataclass(frozen=True)
class PolarizationDetection:
    """CLC mask changes and RMS values for one polarization."""

    polarization: str
    initial_rms: float
    final_rms: float
    initial_mask: np.ndarray
    final_mask: np.ndarray
    appeared_indices: np.ndarray
    disappeared_indices: np.ndarray
    events: tuple[FeatureEvent, ...]


@dataclass(frozen=True)
class FeatureDetectionResult:
    """Complete FR-08 result for a baseline-flattened LCP/RCP spectrum."""

    vlsr: np.ndarray
    channels: dict[str, np.ndarray]
    vll: float
    vrl: float
    mask3: np.ndarray
    detections: dict[str, PolarizationDetection]

    @property
    def events(self) -> tuple[FeatureEvent, ...]:
        """Return all LCP/RCP events in stable polarization/range order."""
        return tuple(event for pol in POLARIZATIONS for event in self.detections[pol].events)


def _finite_1d(values: Any, name: str) -> np.ndarray:
    """Return a finite, non-empty, one-dimensional float array."""
    try:
        array = np.asarray(values, dtype=float).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise FeatureDetectionError(f"{name} is not a numeric array.") from exc
    if array.size == 0:
        raise FeatureDetectionError(f"{name} is empty.")
    if not np.all(np.isfinite(array)):
        raise FeatureDetectionError(f"{name} contains NaN or infinite values.")
    return array


def _masked_rms(amplitude: np.ndarray, mask: np.ndarray) -> float:
    """Use the exact CLC RMS expression and reject an empty/masked result cleanly."""
    noise = np.ma.array(amplitude, mask=mask)
    value = np.sqrt(np.ma.mean(noise**2))
    if np.ma.is_masked(value):
        raise FeatureDetectionError("The selected baseline regions contain no usable channels for RMS calculation.")
    number = float(value)
    if not np.isfinite(number):
        raise FeatureDetectionError("The CLC RMS calculation produced a non-finite value.")
    return number


def _boundary_indices(vlsr: np.ndarray, mask3: np.ndarray, vll: float, vrl: float) -> tuple[int, int]:
    """Reproduce the index search used inside ``Stats_manager.Add_Remove_feature``."""
    vl: int | None = None
    vr: int | None = None
    for index in range(0, len(vlsr) - 1, 1):
        if vlsr[index] <= vll and vlsr[index + 1] >= vll:
            vl = index
        if vlsr[index] <= vrl and vlsr[index + 1] >= vrl and vrl < vlsr[len(mask3) - 1]:
            vr = index
        if vlsr[len(vlsr) - 1] < vrl:
            vr = len(mask3) - 2
    if vl is None or vr is None:
        raise FeatureDetectionError(
            "The baseline envelope cannot be mapped onto the ascending velocity grid required by the CLC detector."
        )
    return vl, vr


def _add_remove_feature(
    amplitude: np.ndarray,
    vlsr: np.ndarray,
    mask: np.ndarray,
    mask3: np.ndarray,
    vll: float,
    vrl: float,
) -> tuple[float, np.ndarray]:
    """Literal, side-effect-free numerical core of ``Stats_manager.Add_Remove_feature``.

    The supplied CLC routine performs two passes with thresholds based on the
    *initial* RMS. It changes 0 -> 1 at >= 2.5 RMS and 1 -> 0 at <= 1.2 RMS
    when the supplied ``mask3`` permits it, then returns RMS from the final
    mask. These details are intentionally preserved rather than reinterpreted.
    """
    working = np.asarray(mask, dtype=int).copy()
    envelope = np.asarray(mask3, dtype=int).copy()
    initial_rms = _masked_rms(amplitude, working)
    vl, vr = _boundary_indices(vlsr, envelope, vll, vrl)

    for _ in range(2):
        for index in range(vl, vr, 1):
            if working[index] == 0 and np.abs(amplitude[index]) >= 2.5 * initial_rms:
                working[index] = 1
            elif envelope[index] == 1 and np.abs(amplitude[index]) <= 1.2 * initial_rms:
                working[index] = 0

    return _masked_rms(amplitude, working), working


def _groups(indices: np.ndarray) -> list[np.ndarray]:
    """Split sorted changed-channel indices into contiguous channel groups."""
    if indices.size == 0:
        return []
    split_at = np.where(np.diff(indices) != 1)[0] + 1
    return [part for part in np.split(indices, split_at) if part.size]


def _events_for_change(
    polarization: str,
    change: str,
    indices: np.ndarray,
    vlsr: np.ndarray,
    amplitude: np.ndarray,
) -> tuple[FeatureEvent, ...]:
    """Summarize exact changed channels into human-readable contiguous groups."""
    events: list[FeatureEvent] = []
    for group in _groups(indices):
        local = group[int(np.argmax(np.abs(amplitude[group])))]
        events.append(
            FeatureEvent(
                polarization=polarization,
                change=change,
                start_velocity=float(vlsr[group[0]]),
                end_velocity=float(vlsr[group[-1]]),
                peak_velocity=float(vlsr[local]),
                peak_amplitude=float(amplitude[local]),
                channel_count=int(group.size),
            )
        )
    return tuple(events)


def detect_features(
    spectrum: Mapping[str, Any],
    blocks: Sequence[Mapping[str, float]],
) -> FeatureDetectionResult:
    """Run FR-08 on the first baseline-flattened spectrum without mutating inputs.

    Args:
        spectrum: Mapping containing equal-length ``Vlsr``, ``LCP`` and ``RCP``
            arrays. Page 04 passes its committed baseline-flattened output.
        blocks: The committed flat baseline regions in their recorded table order.

    Returns:
        Per-polarization mask changes, RMS values and grouped feature records.

    Raises:
        FeatureDetectionError: Inputs cannot satisfy the supplied CLC contract.
    """
    if not isinstance(spectrum, Mapping):
        raise FeatureDetectionError("Feature detection requires a spectrum mapping.")
    arrays = {name: _finite_1d(spectrum.get(name), name) for name in ("Vlsr", "LCP", "RCP")}
    size = arrays["Vlsr"].size
    if arrays["LCP"].size != size or arrays["RCP"].size != size:
        raise FeatureDetectionError("Vlsr, LCP and RCP must contain the same number of channels.")
    if size < 2 or np.any(np.diff(arrays["Vlsr"]) < 0):
        raise FeatureDetectionError("The CLC detector requires an ascending velocity grid with at least two channels.")

    try:
        initial_mask, _rcp_mask, vll, vrl = build_clc_masks(arrays["Vlsr"], blocks)
    except (CLCBaselineIntegrationUnavailable, TypeError, ValueError) as exc:
        raise FeatureDetectionError(str(exc)) from exc

    mask3 = np.ones(size, dtype=int)
    mask3[np.logical_and(arrays["Vlsr"] >= vll, arrays["Vlsr"] <= vrl)] = 0
    detections: dict[str, PolarizationDetection] = {}

    for polarization in POLARIZATIONS:
        amplitude = arrays[polarization]
        before = np.asarray(initial_mask, dtype=int).copy()
        initial_rms = _masked_rms(amplitude, before)
        final_rms, after = _add_remove_feature(amplitude, arrays["Vlsr"], before, mask3, vll, vrl)
        appeared = np.flatnonzero(np.logical_and(before == 0, after == 1))
        disappeared = np.flatnonzero(np.logical_and(before == 1, after == 0))
        events = (
            _events_for_change(polarization, "Appeared", appeared, arrays["Vlsr"], amplitude)
            + _events_for_change(polarization, "Disappeared", disappeared, arrays["Vlsr"], amplitude)
        )
        detections[polarization] = PolarizationDetection(
            polarization=polarization,
            initial_rms=initial_rms,
            final_rms=final_rms,
            initial_mask=before.copy(),
            final_mask=after.copy(),
            appeared_indices=appeared.copy(),
            disappeared_indices=disappeared.copy(),
            events=events,
        )

    return FeatureDetectionResult(
        vlsr=arrays["Vlsr"].copy(),
        channels={pol: arrays[pol].copy() for pol in POLARIZATIONS},
        vll=float(vll),
        vrl=float(vrl),
        mask3=mask3.copy(),
        detections=detections,
    )


def event_rows(result: FeatureDetectionResult) -> list[dict[str, Any]]:
    """Convert grouped feature records into table-ready dictionaries."""
    return [
        {
            "Polarization": event.polarization,
            "Change": event.change,
            "Start Vlsr (km/s)": event.start_velocity,
            "End Vlsr (km/s)": event.end_velocity,
            "Strongest Vlsr (km/s)": event.peak_velocity,
            "Amplitude": event.peak_amplitude,
            "Channels": event.channel_count,
        }
        for event in result.events
    ]
