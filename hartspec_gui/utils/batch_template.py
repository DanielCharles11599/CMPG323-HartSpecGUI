# batch_template.py — FR-21: snapshot validated reference-session settings for campaign jobs.
"""Pin *settings*, not results or an operator's earlier scientific approval.

Only manual FR-19 JSON saves in SESSIONS_PATH can supply a template. The
frozen settings remain in the batch manifest even if the manual save changes;
raw spectra, previous correction factors and previous Go/No-Go decisions are
never inherited by a new observation block.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

from utils.batch_queue import BatchQueueError

TEMPLATE_VERSION = 1
TEMPLATE_MAX_BYTES = 4 * 1024 * 1024
SUPPORTED_FIT_TYPES = frozenset({"1D Gaussian", "Polynomial Peak"})


def _finite_number(value: Any) -> float:
    """Validate a JSON numeric setting without treating booleans as numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BatchQueueError("The template has a non-finite or invalid numeric setting.")
    return float(value)


def _settings(payload: Mapping[str, Any], *, source: str, frequency: float) -> dict[str, Any]:
    """Accept only a complete, compatible manual reduction and known controls."""
    stages = payload.get("pipeline_data")
    completed = payload.get("completed_stages")
    if not isinstance(stages, Mapping) or not isinstance(completed, list):
        raise BatchQueueError("Reference session has no valid pipeline stages/completion record.")
    required = {"01_source_browser", "03_bandpass_correction", "04_baseline_editor", "07_spectral_fitting"}
    if not required.issubset(set(completed)):
        raise BatchQueueError("Save a reference session after completing source, bandpass, baseline and fit stages.")
    selected = stages.get("01_source_browser")
    bandpass = stages.get("03_bandpass_correction")
    baseline = stages.get("04_baseline_editor")
    fitting = stages.get("07_spectral_fitting")
    pointing = stages.get("06_pointing_correction", {})
    if any(not isinstance(item, Mapping) for item in (selected, bandpass, baseline, fitting, pointing)):
        raise BatchQueueError("Reference session contains malformed source or processing stages.")
    if str(selected.get("source_name", "")).strip() != source:
        raise BatchQueueError("Reference session belongs to a different source. Create a source-matched template.")
    saved_frequency = _finite_number(selected.get("frequency_mhz"))
    if not math.isclose(saved_frequency, frequency, rel_tol=0.0, abs_tol=0.001):
        raise BatchQueueError("Reference session has a different observing frequency (MHz).")
    mode = bandpass.get("mode")
    if mode not in ("Frequency Switch", "Position Switch"):
        raise BatchQueueError("Save a reference session with an explicit bandpass mode.")
    blocks = baseline.get("blocks")
    if baseline.get("fit_provider") != "clc" or not baseline.get("complete"):
        raise BatchQueueError("Reference baseline must be a completed CLC-backed polynomial fit.")
    if not isinstance(blocks, list) or not blocks or len(blocks) > 100:
        raise BatchQueueError("Reference baseline requires 1–100 saved velocity blocks.")
    ranges = []
    for block in blocks:
        if not isinstance(block, Mapping):
            raise BatchQueueError("Malformed reference baseline block.")
        start, end = _finite_number(block.get("start")), _finite_number(block.get("end"))
        if start >= end:
            raise BatchQueueError("Reference baseline contains an inverted or empty velocity block.")
        ranges.append({"start": start, "end": end})
    raw_orders = baseline.get("selected_orders")
    if not isinstance(raw_orders, Mapping) or any(type(raw_orders.get(pol)) is not int or
                                                  raw_orders[pol] not in (3, 4, 5)
                                                  for pol in ("LCP", "RCP")):
        raise BatchQueueError("Reference baseline needs an LCP and RCP order of 3, 4 or 5.")
    fit_type = fitting.get("fit_type_requested", fitting.get("fit_type"))
    if fit_type not in SUPPORTED_FIT_TYPES:
        raise BatchQueueError(
            "Batch processing currently supports reference fits of 1D Gaussian or Polynomial Peak; "
            "2D and multi-component batch adapters are not validated."
        )
    # A saved peak/half-width is reusable as a starting selection, never as a cached
    # pointing calculation. If missing, the worker selects the strongest peak.
    peak = pointing.get("peak_velocity_kms")
    if peak is not None:
        peak = _finite_number(peak)
    width = pointing.get("half_width_channels", 4)
    if type(width) is not int or not 2 <= width <= 100:
        raise BatchQueueError("Saved pointing half-width must be an integer from 2 to 100 channels.")
    return {
        "bandpass_mode": mode,
        "baseline_blocks": ranges,
        "polynomial_orders": {pol: raw_orders[pol] for pol in ("LCP", "RCP")},
        "fit_type": fit_type,
        "pointing_peak_velocity_kms": peak,
        "pointing_half_width_channels": width,
    }


def load_template(path: str | Path, sessions_root: str | Path, *, source: str,
                  frequency: float) -> dict[str, Any]:
    """Read a user-selected saved session from the sessions root and freeze its controls.

    Arbitrary JSON files and files outside the sessions folder cannot be used.
    The source manual save is read once. Subsequent batch jobs only use the
    frozen settings and SHA256 recorded in their manifest.
    """
    root = Path(sessions_root).expanduser().resolve()
    requested = Path(path).expanduser().resolve()
    if requested.parent != root or requested.suffix != ".json" or "." in requested.stem:
        raise BatchQueueError("Choose a manual session JSON from the configured sessions directory.")
    try:
        if requested.stat().st_size > TEMPLATE_MAX_BYTES:
            raise BatchQueueError("Reference session JSON is too large.")
        raw = requested.read_bytes()
    except OSError as exc:
        raise BatchQueueError(f"Cannot open reference session: {exc}") from exc
    try:
        payload = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (ValueError, UnicodeError) as exc:
        raise BatchQueueError(f"Reference session JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("session_id"), str):
        raise BatchQueueError("Reference session is missing its session identity.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", payload["session_id"]):
        raise BatchQueueError("Reference session identity is not valid.")
    settings = _settings(payload, source=source, frequency=frequency)
    return {
        "version": TEMPLATE_VERSION,
        "session_id": payload["session_id"],
        "source_file": requested.name,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "settings": settings,
    }


def signature(template: Mapping[str, Any]) -> str:
    """Identify precisely the immutable selected settings, independent of JSON ordering."""
    return hashlib.sha256(json.dumps(template, sort_keys=True, allow_nan=False).encode()).hexdigest()
