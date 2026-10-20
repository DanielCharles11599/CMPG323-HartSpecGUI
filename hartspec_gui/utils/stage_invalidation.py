# stage_invalidation.py — FR-01/19: confirmed-input isolation and baseline invalidation.
"""Invalidate derived state at two different dependency boundaries.

A baseline edit clears only baseline-dependent stages. A confirmed change to
source/frequency/ordered input files clears Pages 2–8 and uses a fresh session
ID: existing bridge readers then cannot restore the previous observation's
baseline, even when an old Dash callback writes to its old bridge later.
No files are written or removed by these mapping helpers.

Several pages derive their results from the baseline-flattened spectrum:

  05_calibration_dashboard  -> st.session_state["calibrated_spectrum"]
  07_spectral_fitting       -> st.session_state["latest_fit"]
  08_export_and_session     -> export-complete marker

If the spectrum upstream of them changes (bandpass mode changed on Page 3, or
the baseline blocks / polynomial orders were edited on Page 4), those results
are stale. Each page recomputes its own state when *visited*, but Pages 7/8
can be reached directly from the sidebar without revisiting Page 5 -- so
without an explicit invalidation step, a user could fit or export against a
calibrated spectrum computed from a baseline that no longer exists.

Standalone mapping/path helpers (st.session_state in the app, plain dicts and
temporary directories in tests), with no Streamlit runtime dependency.

Page 06 (Pointing Correction) is deliberately NOT a baseline dependency: its inputs are the
half-power-point scan readings, not the baseline-flattened spectrum, so a
baseline change does not make its result stale.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Mapping, MutableMapping

BASELINE_DEPENDENT_STAGE_KEYS = (
    "05_calibration_dashboard",
    "07_spectral_fitting",
    "08_export_and_session",
)

BASELINE_DEPENDENT_SESSION_KEYS = (
    "calibrated_spectrum",
    "latest_fit",
)


def invalidate_baseline_dependents(session_state: MutableMapping[str, Any]) -> None:
    """Drop completion flags, saved summaries and derived arrays for every
    stage downstream of the Page 4 baseline.

    Safe to call repeatedly and on a partially-initialised session: missing
    keys are ignored rather than raising.
    """
    completed = session_state.get("completed_stages")
    pipeline_data = session_state.get("pipeline_data")

    for stage_key in BASELINE_DEPENDENT_STAGE_KEYS:
        if completed is not None:
            completed.discard(stage_key)
        if pipeline_data is not None:
            pipeline_data.pop(stage_key, None)

    for key in BASELINE_DEPENDENT_SESSION_KEYS:
        session_state.pop(key, None)


# Keep the narrow baseline dependency above separate: a new observation also
# invalidates pointing, whereas a baseline-only edit deliberately does not.
SOURCE_STAGE_KEY = "01_source_browser"
SOURCE_DEPENDENT_STAGE_KEYS = (
    "file_loader",
    "03_bandpass_correction",
    "04_baseline_editor",
    "05_calibration_dashboard",
    "06_pointing_correction",
    "07_spectral_fitting",
    "08_export_and_session",
)
SOURCE_DEPENDENT_SESSION_PREFIXES = (
    "file_loader_", "manual_map_", "bandpass_", "baseline_", "calibration_",
    "pointing_", "fit_", "spectral_fitting_", "export_",
)
SOURCE_DEPENDENT_SESSION_KEYS = frozenset({
    "loaded_spectrum", "loaded_spectra", "calibrated_spectrum", "latest_fit", "map_2d_data",
})
_SOURCE_CONTROL_DEFAULTS = {
    "file_loader_mapping_mode": "Auto",
    "file_loader_field_search": "",
    "file_loader_show_only_flagged": False,
    "file_loader_manual_filenames_input": "",
    "bandpass_mode": "Frequency Switch",
    "fit_type": "1D Gaussian",
    "fit_polarization": "LCP",
}


def _normalised_path(value: str | Path, root: Path | None = None) -> str:
    """Resolve one path using the host OS's case rules, without reading FITS data."""
    path = Path(value).expanduser()
    if root is not None and not path.is_absolute():
        path = root / path
    return os.path.normcase(str(path.resolve()))


def source_selection_signature(selection: Mapping[str, Any], archive_root: str | Path) -> str:
    """Identify the confirmed source, frequency and ordered effective input paths.

    Args:
        selection: Page 1's JSON-safe handoff. New handoffs record archive_root;
            older handoffs may contain selected_files and/or fits_file_paths.
        archive_root: The current fits_ingest.get_archive_root(), used only
            when an older handoff has no persisted absolute-path information.

    Returns:
        A deterministic identity string. File order is significant because
        Page 3 pairs integrations in input order. Browser search text, folder
        labels, sort errors and workspace locations are not processing inputs.

    Raises:
        ValueError: A handoff is malformed or has no usable file list.

    This compares selection identity, not file contents. It does not reread or
    hash large FITS files. An archive edited in place needs a fresh reduction.
    """
    if not isinstance(selection, Mapping):
        raise ValueError("The source selection must be an object.")
    source = selection.get("source_name")
    if source is not None and not isinstance(source, str):
        raise ValueError("The source name must be text or null.")
    frequency = selection.get("frequency_mhz")
    if frequency is not None:
        if isinstance(frequency, bool) or not isinstance(frequency, (int, float, str)):
            raise ValueError("The selected frequency must be numeric.")
        try:
            frequency = float(frequency)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("The selected frequency must be numeric.") from exc
        if not math.isfinite(frequency) or frequency <= 0:
            raise ValueError("The selected frequency must be finite and positive.")

    selected = selection.get("selected_files")
    original_paths = selection.get("fits_file_paths")
    for name, values in (("selected_files", selected), ("fits_file_paths", original_paths)):
        if values is not None and (
            not isinstance(values, (list, tuple))
            or any(not isinstance(value, str) or not value.strip() or "\x00" in value for value in values)
        ):
            raise ValueError(f"{name} must be a list of non-empty file paths.")
    if not selected and not original_paths:
        raise ValueError("Select at least one FITS file before loading the pipeline.")
    if selected and original_paths and len(selected) != len(original_paths):
        raise ValueError("The selected-file and original-path lists have different lengths.")

    saved_root = selection.get("archive_root")
    if saved_root is not None and (not isinstance(saved_root, str) or not saved_root.strip()):
        raise ValueError("The saved archive root must be a non-empty path.")
    root = Path(saved_root or archive_root).expanduser().resolve()
    # Legacy Page 1 saved actual scanned paths before it saved archive_root.
    # Use those to avoid interpreting yesterday's relative names under today's
    # different archive directory. New records use Page 2's actual load paths.
    if selected and (saved_root is not None or not original_paths):
        paths = [_normalised_path(value, root) for value in selected]
    else:
        paths = [_normalised_path(value) for value in original_paths]
    identity = {
        "source_name": source.strip() if source is not None else None,
        "frequency_mhz": frequency,
        "paths": paths,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def source_selection_changed(
    state: Mapping[str, Any], selection: Mapping[str, Any], archive_root: str | Path,
) -> bool:
    """Compare a proposed handoff to committed inputs; never change live state.

    An unconfirmed or malformed old record is not evidence that downstream
    results are reusable. Invalid new input raises before any cleanup occurs.
    """
    proposed = source_selection_signature(selection, archive_root)
    pipeline = state.get("pipeline_data", {})
    completed = state.get("completed_stages", set())
    if not isinstance(pipeline, Mapping) or not isinstance(completed, set) or SOURCE_STAGE_KEY not in completed:
        return True
    previous = pipeline.get(SOURCE_STAGE_KEY)
    # A legacy fits_file_paths-only record did not feed Page 2's actual loader.
    # Reconfirm it rather than preserving its possibly unrelated fallback data.
    if not isinstance(previous, Mapping) or not previous.get("selected_files"):
        return True
    try:
        return proposed != source_selection_signature(previous, archive_root)
    except (ValueError, TypeError, OSError, RuntimeError):
        return True


def invalidate_source_dependents(state: MutableMapping[str, Any]) -> None:
    """Clear Pages 2–8 for a changed observation, keeping Page 1 and preferences.

    Args:
        state: Streamlit session state, or a plain mapping in regression tests.

    Call on Page 1 before navigation, or in a callback before downstream
    widgets render. Dynamic per-file caches, pending quarantine intent and
    manual mapping controls are included. No process-wide cache is cleared.
    The caller must also change session_id before exposing the new selection,
    so an old file-backed Dash result is outside the new reduction's scope.
    """
    completed = state.get("completed_stages")
    pipeline = state.get("pipeline_data")
    for stage in SOURCE_DEPENDENT_STAGE_KEYS:
        if completed is not None:
            completed.discard(stage)
        if pipeline is not None:
            pipeline.pop(stage, None)
    for key in list(state):
        if isinstance(key, str) and (
            key in SOURCE_DEPENDENT_SESSION_KEYS or key.startswith(SOURCE_DEPENDENT_SESSION_PREFIXES)
        ):
            del state[key]
    # Page 1 controls already rendered on this run; do not overwrite them.
    # Downstream controls have not rendered yet, so safe defaults cannot be
    # overwritten by the previous reduction's frontend widget values.
    state.update(_SOURCE_CONTROL_DEFAULTS)


def commit_source_selection(
    state: MutableMapping[str, Any], selection: Mapping[str, Any], *,
    archive_root: str | Path, new_session_id: str,
) -> bool:
    """Commit changed Page 1 inputs, or leave an unchanged reduction intact.

    Args:
        state: The active session mapping.
        selection: Complete Page 1 payload, including any File_check results.
        archive_root: Same archive root used to build the selected_files list.
        new_session_id: A fresh ID reserved by the page before sorting. This
            isolates the new bridge and workspace without deleting old ones.

    Returns:
        True when a new selection was committed; False for unchanged inputs.

    Raises:
        ValueError: Invalid input, active-state shape or replacement ID. All
            validation/copying happens before the previous reduction is cleared.

    Audit logging and navigation belong to the page. The existing audit list,
    browser controls, theme/authentication and unknown extension data survive.
    Only known downstream stage parameters and runtime results are invalidated.
    """
    changed = source_selection_changed(state, selection, archive_root)
    if not changed:
        return False
    if (
        not isinstance(new_session_id, str)
        or re.fullmatch(r"[A-Za-z0-9_-]+", new_session_id) is None
        or new_session_id == state.get("session_id")
    ):
        raise ValueError("A changed selection requires a fresh, filename-safe session ID.")
    pipeline = state.get("pipeline_data", {})
    completed = state.get("completed_stages", set())
    if not isinstance(pipeline, dict) or not isinstance(completed, set):
        raise ValueError("The active session has invalid pipeline data or completion flags.")
    payload = copy.deepcopy(dict(selection))
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("The source selection must contain only JSON-safe metadata.") from exc

    state.setdefault("pipeline_data", {})
    state.setdefault("completed_stages", set())
    invalidate_source_dependents(state)
    state["session_id"] = new_session_id
    state["pipeline_data"][SOURCE_STAGE_KEY] = payload
    state["completed_stages"].add(SOURCE_STAGE_KEY)
    return True


# Validation/quarantine can change the usable files without changing Page 1's
# selection. Retain the selection, loader evidence and its visible controls;
# only stages consuming those files must be recomputed (including pointing).
LOADED_INPUT_DEPENDENT_STAGE_KEYS = SOURCE_DEPENDENT_STAGE_KEYS[1:]
LOADED_INPUT_DEPENDENT_PREFIXES = (
    "bandpass_", "baseline_", "calibration_", "pointing_", "fit_", "spectral_fitting_", "export_",
)


def invalidate_loaded_input_dependents(state: MutableMapping[str, Any], *, new_session_id: str) -> None:
    """Invalidate Pages 3–8 after the validated input set changes.

    Args:
        state: Streamlit session state or a plain mapping in tests.
        new_session_id: A fresh filename-safe reduction ID. The old Dash
            bridge is retained, but its output is outside the new reduction.

    Raises:
        ValueError: Invalid replacement ID or malformed persistent state;
            validation happens before any state is changed.

    Unlike a new Page 1 selection, this retains per-file validation evidence,
    quarantine records, header mappings and all current Page 2 controls. No
    raw data, saved JSON, workspace or bridge file is deleted or modified.
    """
    if (
        not isinstance(new_session_id, str)
        or re.fullmatch(r"[A-Za-z0-9_-]+", new_session_id) is None
        or new_session_id == state.get("session_id")
    ):
        raise ValueError("Changed validated inputs require a fresh, filename-safe session ID.")
    pipeline = state.get("pipeline_data", {})
    completed = state.get("completed_stages", set())
    if not isinstance(pipeline, dict) or not isinstance(completed, set):
        raise ValueError("The active session has invalid pipeline data or completion flags.")

    for stage in LOADED_INPUT_DEPENDENT_STAGE_KEYS:
        completed.discard(stage)
        pipeline.pop(stage, None)
    for key in list(state):
        if isinstance(key, str) and (
            key in ("calibrated_spectrum", "latest_fit", "map_2d_data")
            or key.startswith(LOADED_INPUT_DEPENDENT_PREFIXES)
        ):
            del state[key]
    # These controls belong to later pages, not the currently mounted loader.
    state.update({"bandpass_mode": "Frequency Switch", "fit_type": "1D Gaussian", "fit_polarization": "LCP"})
    state["session_id"] = new_session_id
