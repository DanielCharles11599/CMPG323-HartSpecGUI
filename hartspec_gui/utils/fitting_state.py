# fitting_state.py — FR-14–19: JSON-safe, per-mode Stage 7 state and content-addressed fit caches.
"""Pure state helpers. No widgets, optimizer calls, filesystem access or global caches."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict, is_dataclass
from typing import Any, MutableMapping

import numpy as np

from utils import fitting_helpers as fh

STAGE_KEY = "07_spectral_fitting"
MODE_IDS = dict(zip(fh.FIT_TYPES, ("1d", "poly", "2d", "multicomp")))


def json_safe(value: Any) -> Any:
    """Preserve float precision; encode missing/non-finite uncertainties as JSON null."""
    if is_dataclass(value):
        return json_safe(asdict(value))
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def signature(*arrays: Any, context: Any = None) -> str:
    """Hash complete numeric inputs, shapes and metadata; never identify data by sum/length."""
    digest = hashlib.sha256()
    digest.update(json.dumps(json_safe(context), sort_keys=True, allow_nan=False).encode())
    for values in arrays:
        arr = np.ascontiguousarray(values, dtype="<f8")
        digest.update(str(arr.shape).encode())
        digest.update(arr.tobytes())
    return digest.hexdigest()


def request_key(input_signature: str, options: dict[str, Any]) -> str:
    """A fit request changes on data OR parameter changes, but not theme/font reruns."""
    return signature(context={"input": input_signature, "options": options})


def ensure_stage(pipeline: MutableMapping[str, Any]) -> dict[str, Any]:
    """Initialize active state, migrating older committed summaries without discarding them."""
    stage = pipeline.setdefault(STAGE_KEY, {})
    if not isinstance(stage, dict):
        stage = pipeline[STAGE_KEY] = {}
    mode = stage.get("fit_type_requested", stage.get("fit_type", fh.FIT_TYPES[0]))
    mode = "Multi-Component" if mode == "Multi-component" else mode
    if mode not in fh.FIT_TYPES:
        mode = fh.FIT_TYPES[0]
    stage.setdefault("modes", {})
    if not isinstance(stage["modes"], dict):
        stage["modes"] = {}
    if not stage["modes"] and stage.get("fit_options"):
        options = copy.deepcopy(stage["fit_options"])
        if mode == "2D Gaussian":
            options = {"p0": options.get("initial_guess", [])}
        stage["modes"][mode] = {"options": options}
    block = stage.get("multi_component")
    if block and "Multi-Component" not in stage["modes"]:
        stage["modes"]["Multi-Component"] = {
            "options": {"components": fh.restore_from_block(block), "auto": False,
                        "max_components": 10, "rms_cutoff": 5.0, "chi2_threshold": 0.01}}
    stage.update(schema_version=2, fit_type=mode, fit_type_requested=mode)
    return stage


def mode_state(stage: dict[str, Any], mode: str, input_signature: str) -> dict[str, Any]:
    """Get a mode's draft/cache; discard an old result when its observation/map changes."""
    entry = stage["modes"].setdefault(mode, {"options": {}})
    if not isinstance(entry, dict):
        entry = stage["modes"][mode] = {"options": {}}
    previous = entry.get("input_signature")
    if previous is not None and previous != input_signature:
        # Guesses remain editable, but an old observation's model/covariance cannot reappear.
        options = entry.get("options", {})
        entry.clear()
        entry["options"] = options
    entry["input_signature"] = input_signature
    entry.setdefault("options", {})
    return entry


def save_result(entry: dict[str, Any], request: str, result: Any) -> None:
    """Record a successful result and its precise request; serialization survives session reload."""
    packed = json_safe(result)
    if is_dataclass(result):
        packed["ok"] = bool(result.ok)
    entry.update(result=packed, result_request=request, last_attempt=request)
    entry.pop("error", None)
    entry.pop("failed_request", None)


def save_failure(entry: dict[str, Any], request: str, message: str) -> None:
    """Keep the last good model visible, but prohibit committing it as this failed request."""
    entry.update(error=str(message), failed_request=request, last_attempt=request)


def result_is_current(entry: dict[str, Any], request: str) -> bool:
    """True only for a successful cached fit of the currently displayed controls and data."""
    return bool(entry.get("result", {}).get("ok") and entry.get("result_request") == request
                and entry.get("failed_request") != request)


def invalidate_commit(state: MutableMapping[str, Any], stage: dict[str, Any], request: str) -> None:
    """Do not export a formerly committed fit after changing its data, controls or mode."""
    if stage.get("committed_request") == request:
        return
    state.pop("latest_fit", None)
    completed = state.get("completed_stages", set())
    for key in (STAGE_KEY, "08_export_and_session"):
        if hasattr(completed, "discard"):
            completed.discard(key)
        elif isinstance(completed, list) and key in completed:
            completed.remove(key)
    state.get("pipeline_data", {}).pop("08_export_and_session", None)
    stage.pop("committed_request", None)
    # These fields describe a committed result, not the newly selected draft mode.
    # Cached per-mode results remain available under modes, with their own provenance.
    for key in ("parameters", "fit_options", "converged", "notes", "covariance", "covariance_parameters",
                "multi_component", "spectrum_source", "intensity_unit"):
        stage.pop(key, None)
