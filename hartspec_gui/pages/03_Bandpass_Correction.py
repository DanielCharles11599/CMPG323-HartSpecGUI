# 03_Bandpass_Correction.py — FR-04/19: verified multi-pair bandpass correction and replay.
# Preserves JC's display/readability and FR-19 fingerprint replay alongside verified pair-selection safeguards.
# Requires the entry-pair API in the supplied utils/bandpass_correction_logic.py.
# Scientific subtraction and velocity-channel selection remain in that unchanged helper.
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from astropy.io import fits
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from utils import baseline_editor_bridge, fits_ingest, session_store, sidebar, styles
from utils.bandpass_correction_logic import (
    MODE_OPTIONS,
    THIS_STAGE_KEY,
    build_bandpass_result,
    get_full_integration_pairs,
    stage_summary,
    suggest_mode,
)
from utils.file_loader_logic import eligible_loaded_entries, publish_validated_handoff, restore_saved_quarantine
from utils.stage_invalidation import invalidate_baseline_dependents

PAGE_STAGE_KEY = THIS_STAGE_KEY
CURRENT_STAGE = 3
PAGE_TITLE = "Bandpass Correction"
PAGE_SUBTITLE = "Pair and mode selection + before/after spectra"
UPSTREAM_STAGE_KEYS = ("01_source_browser", "file_loader")
DOWNSTREAM_STAGE_KEYS = (
    "04_baseline_editor", "05_calibration_dashboard", "06_pointing_correction",
    "07_spectral_fitting", "08_export_and_session",
)
_REQUIRED_ARRAY_KEYS = ("Vlsr", "LCP", "RCP")
_DOWNSTREAM_PREFIXES = ("baseline_", "calibration_", "pointing_", "fit_", "spectral_fitting_", "export_")
Pair = tuple[dict[str, Any], dict[str, Any]]


def _completed_upstream_count() -> int:
    """Count only Pages 1 and 2 in Page 3's progress header."""
    return sum(key in st.session_state["completed_stages"] for key in UPSTREAM_STAGE_KEYS)


def _upstream_complete() -> bool:
    """Require both source selection and File Loader completion before processing."""
    return all(key in st.session_state["completed_stages"] for key in UPSTREAM_STAGE_KEYS)


def _target_filenames() -> list[str]:
    """Read the current File Loader targets, preserving their order."""
    selection = st.session_state.get("pipeline_data", {}).get("01_source_browser", {})
    selection = selection if isinstance(selection, Mapping) else {}
    selected = selection.get("selected_files") or st.session_state.get("file_loader_target_filenames") or []
    return list(dict.fromkeys(str(name) for name in selected))


def _pointing_value(value: Any) -> int | None:
    """Accept integer SPPOINT values, never truncate a fractional value into zero."""
    try:
        number = float(value)
        return int(number) if np.isfinite(number) and number.is_integer() else None
    except (ValueError, TypeError, OverflowError):
        return None


@st.cache_data(show_spinner=False)
def _read_observation_metadata(path_string: str, mtime_ns: int | None) -> tuple[int | None, str]:
    """Read metadata absent from the loader; modification time scopes the header cache.

    This reads headers only. It is not a substitute for File Loader verification.
    """
    try:
        with fits.open(Path(path_string)) as hdul:
            pointing = hdul[0].header.get("SPPOINT") if len(hdul) else None
            position = hdul[2].header.get("POSITION", "") if len(hdul) > 2 else ""
        return _pointing_value(pointing), str(position or "").strip().upper()
    except (OSError, ValueError, TypeError, IndexError, KeyError):
        return None, ""


def _quarantine_metadata() -> Mapping[str, Any]:
    """SPPOINT/POSITION that Page 02 recorded for files it moved to Flagged/ (they are gone from their old path)."""
    loader = st.session_state.get("pipeline_data", {}).get("file_loader", {})
    meta = loader.get("quarantined_meta") if isinstance(loader, Mapping) else None
    return meta if isinstance(meta, Mapping) else {}


def _candidate_pairs() -> tuple[list[Pair], list[str]]:
    """Use JC's observation ordering, but permit only verified pairs to run.

    Keep excluded files as metadata-only pairing slots before filtering whole
    pairs. Removing a failed full integration first would shift [A,B],[C,D]
    into [A,C] when B failed. Unknown SPPOINT blocks that observation directory
    rather than guessing whether the unreadable file occupied a science slot.
    No excluded spectrum is ever passed to build_bandpass_result().
    """
    filenames = _target_filenames()
    eligible = {entry["filename"]: entry for entry in eligible_loaded_entries(st.session_state, filenames)}
    entries: list[dict[str, Any]] = []
    unknown_directories: set[str] = set()
    notes: list[str] = []
    quarantine_meta = _quarantine_metadata()
    for filename in filenames:
        ingest = st.session_state.get(f"file_loader_ingest_result::{filename}")
        raw = getattr(ingest, "spectrum", None)
        spectrum = raw if isinstance(raw, Mapping) else {}
        path = Path(getattr(ingest, "path", None) or (fits_ingest.get_archive_root() / filename)).expanduser()
        path = path.absolute()
        pointing = _pointing_value(spectrum.get("pointing", spectrum.get("SPPOINT")))
        position = str(spectrum.get("position", spectrum.get("POSITION", "")) or "").strip().upper()
        saved = quarantine_meta.get(filename)
        if (pointing is None or not position) and isinstance(saved, Mapping):
            # Quarantined files were moved away: use the metadata recorded before the move, so the file still
            # holds its pairing slot (and its pair is dropped) instead of blocking the whole observation.
            pointing = _pointing_value(saved.get("pointing")) if pointing is None else pointing
            position = position or str(saved.get("position") or "").strip().upper()
        if pointing is None or not position:
            try:
                mtime = path.stat().st_mtime_ns
            except OSError:
                mtime = None
            header_pointing, header_position = _read_observation_metadata(str(path), mtime)
            pointing = header_pointing if pointing is None else pointing
            position = position or header_position
        observation_dir = os.path.normcase(str(path.parent))
        if pointing is None:
            unknown_directories.add(observation_dir)
            notes.append(f"Cannot determine SPPOINT for {filename}; its observation is not paired automatically.")
        entries.append({
            "filename": filename,
            "spectrum": eligible[filename]["spectrum"] if filename in eligible else {},
            "pointing": pointing, "position": position, "observation_dir": observation_dir,
            "input_path": os.path.normcase(str(path)),
        })

    # Always pass entries explicitly: the helper's no-argument path has a
    # legacy loaded_spectra fallback which has no per-file validation evidence.
    candidates = get_full_integration_pairs(
        [entry for entry in entries if entry["observation_dir"] not in unknown_directories]
    )
    pairs = [pair for pair in candidates if all(entry["filename"] in eligible for entry in pair)]
    skipped = len(candidates) - len(pairs)
    if skipped:
        notes.append(
            f"{skipped} pair(s) excluded because a member failed loading/verification or was quarantined. "
            "The next file is not substituted for a rejected pair member."
        )
    return pairs, notes


def _pair_paths(pair: Pair) -> list[str]:
    """Return ordered full paths, not basenames or a changeable dropdown index."""
    return [str(entry["input_path"]) for entry in pair]


def _pair_signature(pair: Pair) -> str:
    """Stable identity for the selected ordered pair, independent of UI position."""
    return json.dumps(_pair_paths(pair), ensure_ascii=True, separators=(",", ":"))


def _normalise_spectrum(spectrum: Mapping[str, Any], label: str) -> dict[str, np.ndarray]:
    """Validate one-dimensional finite arrays; do not resample, shift or align them."""
    if not isinstance(spectrum, Mapping):
        raise ValueError(f"{label} is not a spectrum mapping.")
    arrays: dict[str, np.ndarray] = {}
    for key in _REQUIRED_ARRAY_KEYS:
        if key not in spectrum:
            raise ValueError(f"{label} is missing required field: {key}.")
        try:
            array = np.asarray(spectrum[key], dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} field {key} is not numeric.") from exc
        if array.ndim != 1 or array.size == 0:
            raise ValueError(f"{label} field {key} must be a non-empty one-dimensional array.")
        if not np.all(np.isfinite(array)):
            raise ValueError(f"{label} field {key} contains NaN or infinite values.")
        arrays[key] = array.copy()
    if len({array.size for array in arrays.values()}) != 1:
        raise ValueError(f"{label} arrays have inconsistent lengths.")
    return arrays


def _spectra_equal(left: Any, right: Any) -> bool:
    """Compare scientific handoff arrays without comparing NumPy-containing dicts."""
    try:
        return all(np.array_equal(left[key], right[key]) for key in _REQUIRED_ARRAY_KEYS)
    except (KeyError, TypeError, ValueError):
        return False


def _input_fingerprint(pair: Pair) -> str:
    """Track pair identity, metadata and loaded arrays so stale results cannot match by mode alone."""
    parts = []
    for entry in pair:
        _normalise_spectrum(entry["spectrum"], entry["filename"])
        parts.append({
            "path": entry["input_path"], "pointing": entry["pointing"], "position": entry["position"],
            "spectrum": baseline_editor_bridge.spectrum_fingerprint(entry["spectrum"]),
        })
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()


def _legacy_output_fingerprint(spectrum: Mapping[str, Any]) -> str:
    """Check saved outputs from JC's Page 03, which used its own SHA-256 format.

    The newer baseline-editor bridge fingerprint has a different serialization.
    Neither changes any scientific data.
    """
    digest = hashlib.sha256()
    for key in _REQUIRED_ARRAY_KEYS:
        array = np.asarray(spectrum[key], dtype="<f8").reshape(-1)
        digest.update(key.encode("ascii"))
        digest.update(array.size.to_bytes(8, byteorder="little", signed=False))
        digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def _replay_mismatch(saved: Mapping[str, Any], pair: Pair, mode: str,
                     input_fingerprint: str, result: Mapping[str, Any]) -> str | None:
    """Refuse silent replay if saved identity/verified output contradict current data.

    This supports both the older filename-only saved records and newer exact
    path/input fingerprints, plus both generations of output hash.
    """
    if not isinstance(saved, Mapping) or saved.get("mode") != mode:
        return "The saved bandpass mode is missing or differs from the selected mode."
    if _saved_pair_index(saved, [pair]) != 0 and any(
        name in saved for name in ("pair_paths", "filename1", "filename2")
    ):
        return "The saved bandpass pair no longer matches the available observation pair."
    if saved.get("input_fingerprint") and saved["input_fingerprint"] != input_fingerprint:
        return "The selected FITS inputs or observation metadata differ from the saved session."
    corrected = _normalise_spectrum(result["corrected"], "Replayed bandpass spectrum")
    if saved.get("corrected_fingerprint") and (
        saved["corrected_fingerprint"] != baseline_editor_bridge.spectrum_fingerprint(corrected)
    ):
        return "The recalculated bandpass output differs from the saved session."
    if saved.get("output_fingerprint") and (
        saved["output_fingerprint"] != _legacy_output_fingerprint(corrected)
    ):
        return "The recalculated bandpass output differs from the saved session."
    return None


def _saved_pair_index(saved: Mapping[str, Any], pairs: list[Pair]) -> int | None:
    """Match new path-based records or JC's older filename1/filename2 records."""
    paths = saved.get("pair_paths")
    if isinstance(paths, list) and len(paths) == 2 and all(isinstance(path, str) for path in paths):
        return next((i for i, pair in enumerate(pairs) if _pair_paths(pair) == paths), None)
    names = (saved.get("filename1"), saved.get("filename2"))
    if all(isinstance(name, str) and name for name in names):
        matches = [i for i, pair in enumerate(pairs) if tuple(entry["filename"] for entry in pair) == names]
        return matches[0] if len(matches) == 1 else None
    return None


def _clear_stage3_and_downstream(reason: str = "Bandpass result invalidated") -> None:
    """Clear derived results while retaining source/loader evidence and UI controls.

    A changed pair or mode may coincidentally produce identical numbers. Use a
    fresh reduction ID when old results exist, preserving the old bridge file
    and isolating even a delayed Dash write. Do not delete saved reductions.
    """
    state = st.session_state
    completed = state["completed_stages"]
    pipeline = state["pipeline_data"]
    stages = (PAGE_STAGE_KEY,) + DOWNSTREAM_STAGE_KEYS
    previous_id = state["session_id"]
    has_old = any(key in pipeline or key in completed for key in stages)
    has_old = has_old or any(state.get(key) is not None for key in (
        "bandpass_display_result", "bandpass_corrected_spectrum", "baseline_corrected_spectrum",
        "calibrated_spectrum", "latest_fit",
    )) or bool(baseline_editor_bridge.read_bridge(previous_id))
    for key in stages:
        completed.discard(key)
        pipeline.pop(key, None)
    invalidate_baseline_dependents(state)
    for key in list(state):
        if isinstance(key, str) and key.startswith(_DOWNSTREAM_PREFIXES):
            state.pop(key, None)
    for key in (
        "bandpass_corrected_spectrum", "bandpass_display_result", "bandpass_applied_mode",
        "bandpass_error", "bandpass_failed_request", "bandpass_replay_pending",
        "calibrated_spectrum", "latest_fit",
    ):
        state.pop(key, None)
    if has_old:
        state["session_id"] = uuid.uuid4().hex
        session_store.log_event(
            f"{reason} — downstream results cleared (reduction {previous_id} → {state['session_id']})"
        )
    # Pair/mode controls are mounted on this page; never overwrite them here.
    state["bandpass_controls_session_id"] = state["session_id"]
    session_store.checkpoint_session(reason)


def _prepare_controls(pairs: list[Pair]) -> None:
    """Restore saved pair/mode once, before mounting the corresponding widgets."""
    state = st.session_state
    pair_options = [_pair_signature(pair) for pair in pairs]
    if (
        state.get("bandpass_controls_session_id") == state["session_id"]
        and state.get("bandpass_pair_signature")
        and "bandpass_pair_index" in state
        and state.get("bandpass_mode") in MODE_OPTIONS
    ):
        old_options = state.get("bandpass_pair_options")
        if old_options is not None and old_options != pair_options:
            previous_pair = state["bandpass_pair_signature"]
            if previous_pair in pair_options:
                state["bandpass_pair_index"] = pair_options.index(previous_pair)
            else:
                _clear_stage3_and_downstream("Selected pair is no longer available")
                state["bandpass_pair_index"] = 0
                state["bandpass_selection_warning"] = "The selected pair is unavailable. Choose a pair and click Apply."
                state["bandpass_require_apply"] = True
        index = state.get("bandpass_pair_index", 0)
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(pairs):
            state["bandpass_pair_index"] = 0
        state["bandpass_pair_options"] = pair_options
        return
    saved = state["pipeline_data"].get(PAGE_STAGE_KEY, {})
    saved = dict(saved) if isinstance(saved, Mapping) else {}
    has_saved = PAGE_STAGE_KEY in state["completed_stages"] and bool(saved)
    index = _saved_pair_index(saved, pairs) if has_saved else None
    warning = None
    if has_saved and index is None:
        has_identity = any(key in saved for key in ("pair_paths", "filename1", "filename2"))
        if not has_identity and len(pairs) == 1:
            index = 0  # old Step 3 saved only the mode; a single candidate is unambiguous
        else:
            warning = (
                "The saved pair is unavailable or ambiguous. Choose a verified pair and click Apply; "
                "a different pair will not be replayed silently."
            )
    if has_saved and saved.get("mode") not in MODE_OPTIONS:
        warning = "The saved bandpass mode is invalid. Choose a mode and click Apply."
    index = index if index is not None else 0
    suggested, _ = suggest_mode(pairs[index])
    mode = saved.get("mode") if has_saved and saved.get("mode") in MODE_OPTIONS else suggested
    mode = mode if mode in MODE_OPTIONS else MODE_OPTIONS[0]
    if warning:
        _clear_stage3_and_downstream("Saved bandpass selection could not be restored")
    state["bandpass_pair_index"] = index
    state["bandpass_pair_options"] = pair_options
    state["bandpass_pair_signature"] = _pair_signature(pairs[index])
    state["bandpass_mode"] = mode
    state["bandpass_require_apply"] = bool(warning) or (not has_saved and suggested is None)
    state["bandpass_selection_warning"] = warning
    state["bandpass_replay_pending"] = has_saved and not warning
    state["bandpass_controls_session_id"] = state["session_id"]


def _on_mode_change() -> None:
    """A user-selected mode supersedes the applied one and permits automatic calculation."""
    applied = st.session_state.get("bandpass_applied_mode")
    if applied and applied != st.session_state.get("bandpass_mode"):
        _clear_stage3_and_downstream("Bandpass mode changed")
    st.session_state.pop("bandpass_failed_request", None)
    st.session_state.pop("bandpass_error", None)
    if not st.session_state.get("bandpass_selection_warning"):
        st.session_state["bandpass_require_apply"] = False


def _result_matches(pair: Pair, mode: str, fingerprint: str) -> bool:
    """Reuse only a result belonging to these exact inputs and the displayed mode."""
    result = st.session_state.get("bandpass_display_result")
    if not isinstance(result, Mapping):
        return False
    try:
        _normalise_spectrum(result.get("corrected"), "Stored bandpass spectrum")
        saved = st.session_state["pipeline_data"].get(PAGE_STAGE_KEY, {})
        if not isinstance(saved, Mapping):
            return False
        if baseline_editor_bridge.spectrum_fingerprint(result["corrected"]) != saved.get("corrected_fingerprint"):
            return False
    except (ValueError, TypeError, KeyError):
        return False
    return (
        PAGE_STAGE_KEY in st.session_state["completed_stages"]
        and result.get("mode") == mode == st.session_state.get("bandpass_applied_mode")
        and result.get("pair_paths") == _pair_paths(pair)
        and result.get("input_fingerprint") == fingerprint
        and _spectra_equal(result.get("corrected"), st.session_state.get("bandpass_corrected_spectrum"))
    )


def _commit_result(mode: str, result: Mapping[str, Any], pair: Pair, fingerprint: str) -> None:
    """Validate everything before publishing the arrays and JSON-safe pair/mode record."""
    corrected = _normalise_spectrum(result["corrected"], "Bandpass-corrected spectrum")
    raw1 = _normalise_spectrum(result["raw_spec1"], "Input spectrum 1")
    raw2 = _normalise_spectrum(result["raw_spec2"], "Input spectrum 2")
    if result.get("mode") != mode or any(
        result.get(f"filename{i}") != entry["filename"] for i, entry in enumerate(pair, start=1)
    ):
        raise ValueError("The correction helper returned a different pair or mode than the displayed selection.")
    extent = list(result.get("common_velocity_range_kms") or [])
    if extent and (len(extent) != 2 or not np.all(np.isfinite(extent)) or extent[0] > extent[1]):
        raise ValueError("The correction helper returned an invalid common velocity range.")
    output_fingerprint = baseline_editor_bridge.spectrum_fingerprint(corrected)
    summary = dict(stage_summary(mode, corrected))
    position1 = str(pair[0].get("position", "") or "")
    position2 = str(pair[1].get("position", "") or "")
    summary.update({
        "filename1": pair[0]["filename"], "filename2": pair[1]["filename"],
        "position1": position1, "position2": position2,
        "pair_pattern": f"{position1} → {position2}",
        "pair_paths": _pair_paths(pair), "common_velocity_range_kms": extent,
        "input_fingerprint": fingerprint, "corrected_fingerprint": output_fingerprint,
        "output_fingerprint": _legacy_output_fingerprint(corrected),
    })
    state = st.session_state
    previous = state.get("bandpass_corrected_spectrum")
    saved = state["pipeline_data"].get(PAGE_STAGE_KEY, {})
    saved = saved if isinstance(saved, Mapping) else {}
    replay = bool(state.get("bandpass_replay_pending"))
    bridge_document = baseline_editor_bridge.read_bridge(state["session_id"])
    bridge = bridge_document if isinstance(bridge_document, Mapping) else {}
    changed = bridge_document is not None and not isinstance(bridge_document, Mapping)
    changed = changed or (previous is not None and not _spectra_equal(previous, corrected))
    changed = changed or (bool(saved) and saved.get("mode") != mode)
    changed = changed or ("pair_paths" in saved and saved["pair_paths"] != _pair_paths(pair))
    changed = changed or ("input_fingerprint" in saved and saved["input_fingerprint"] != fingerprint)
    changed = changed or ("corrected_fingerprint" in saved and saved["corrected_fingerprint"] != output_fingerprint)
    changed = changed or (
        "output_fingerprint" in saved and saved["output_fingerprint"] != summary["output_fingerprint"]
    )
    changed = changed or (bool(bridge) and bridge.get("spectrum_fingerprint") != output_fingerprint)
    has_downstream = any(
        key in state["pipeline_data"] or key in state["completed_stages"] for key in DOWNSTREAM_STAGE_KEYS
    )
    has_downstream = has_downstream or state.get("calibrated_spectrum") is not None
    has_downstream = has_downstream or state.get("latest_fit") is not None or bool(bridge)
    if not saved and has_downstream:
        changed = True  # orphaned downstream results have no recorded bandpass provenance
    if changed:
        _clear_stage3_and_downstream("Bandpass pair, input or output changed")
        if replay:
            st.warning("Replayed inputs/output differ from the saved result. Revisit the downstream stages.")
    state["bandpass_corrected_spectrum"] = corrected
    state["bandpass_display_result"] = {
        "mode": mode, "raw_spec1": raw1, "raw_spec2": raw2, "corrected": corrected,
        **{key: summary[key] for key in (
            "filename1", "filename2", "pair_paths", "input_fingerprint", "common_velocity_range_kms",
        )},
    }
    state["bandpass_applied_mode"] = mode
    state["pipeline_data"][PAGE_STAGE_KEY] = summary
    state["bandpass_replay_pending"] = False
    state["bandpass_require_apply"] = False
    state.pop("bandpass_selection_warning", None)
    state.pop("bandpass_failed_request", None)
    state.pop("bandpass_error", None)
    session_store.mark_stage_complete(PAGE_STAGE_KEY)
    action = "replayed from saved session" if replay and not changed else "applied"
    session_store.log_event(
        f"Bandpass correction {action} — {mode}: {pair[0]['filename']} + {pair[1]['filename']} "
        f"({corrected['Vlsr'].size} channels)"
    )


def _apply_selected_pair(pair: Pair, *, force: bool = False) -> None:
    """One computation path for automatic application, replay, and explicit Apply/Reapply."""
    state = st.session_state
    mode = state["bandpass_mode"]
    request = _pair_signature(pair) + mode
    try:
        fingerprint = _input_fingerprint(pair)
        request += fingerprint
        if not force and _result_matches(pair, mode, fingerprint):
            state["bandpass_replay_pending"] = False
            return
        if not force and (state.get("bandpass_require_apply") or state.get("bandpass_failed_request") == request):
            return
        # The helper requires the metadata entries, NOT [entry1['spectrum'], entry2['spectrum']].
        result = build_bandpass_result(mode, pair)
        if state.get("bandpass_replay_pending") and not force:
            saved = state["pipeline_data"].get(PAGE_STAGE_KEY, {})
            mismatch = _replay_mismatch(saved, pair, mode, fingerprint, result)
            if mismatch:
                _clear_stage3_and_downstream("Saved bandpass replay did not match")
                state["bandpass_require_apply"] = True
                state["bandpass_failed_request"] = request
                state["bandpass_selection_warning"] = (
                    "Saved bandpass data failed verification. Choose the intended pair and mode, "
                    "then click Apply to start a new result."
                )
                state["bandpass_error"] = mismatch
                return
            if not (saved.get("corrected_fingerprint") or saved.get("output_fingerprint")):
                st.warning(
                    "This saved session predates output fingerprints. The pair and mode were restored, "
                    "but the previous numeric output cannot be verified."
                )
        _commit_result(mode, result, pair, fingerprint)
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        _clear_stage3_and_downstream("Bandpass correction failed")
        state["bandpass_failed_request"] = request
        state["bandpass_error"] = f"Bandpass correction failed: {exc}"


def _render_pair_info(pair: Pair, pair_number: int, total_pairs: int) -> None:
    """Show the real filenames and the helper's suggestion without hiding the mode toggle."""
    suggested, reason = suggest_mode(pair)
    st.markdown('<div class="hs-eyebrow">Detected full-integration pair</div>', unsafe_allow_html=True)
    with st.container(border=True):
        cols = st.columns([1, 1, 1.25])
        for column, entry, label in zip(cols[:2], pair, ("File 1", "File 2")):
            with column:
                st.markdown(f"**{label}**")
                st.caption(entry["filename"])
        with cols[2]:
            st.markdown("**Mode suggestion from metadata**")
            st.caption(f"{suggested or 'Unable to determine automatically'} — {reason}")
        first_position = str(pair[0].get("position", "?") or "?").strip().upper()
        second_position = str(pair[1].get("position", "?") or "?").strip().upper()
        st.caption(f"Observed POSITION sequence: {first_position} → {second_position}")
        st.caption(
            f"Pair {pair_number} of {total_pairs}. SPPOINT = 0 integrations are paired within each observation, "
            "using observation_list.txt ordering when available. Both files passed loading and structural validation."
        )


def _add_before_after(
    fig: go.Figure, column: int, raw: Mapping[str, Any], corrected: Mapping[str, Any], label: str, color: str,
) -> None:
    """Add unchanged before/after data for one polarisation to JC's two-panel chart."""
    for spectrum, prefix, width, dash, opacity in (
        (raw, "Before", 2.0, "dot", 0.85), (corrected, "After", 2.4, "solid", 1.0),
    ):
        fig.add_trace(go.Scatter(
            x=spectrum["Vlsr"], y=spectrum[label], mode="lines", name=f"{prefix} {label}",
            legendgroup=label, line=dict(color=color, width=width, dash=dash), opacity=opacity,
            hovertemplate=f"{prefix} {label}<br>Vlsr=%{{x:.2f}} km/s<br>T=%{{y:.3f}} K<extra></extra>",
        ), row=1, col=column)


def _render_before_after(result: Mapping[str, Any]) -> None:
    """Retain JC's LCP/RCP panels, common-range shading, filenames and theme tokens."""
    theme = styles.get_theme()
    raw, corrected = result["raw_spec1"], result["corrected"]
    common_range = result.get("common_velocity_range_kms") or []
    with st.container(border=True):
        st.markdown('<div class="hs-panel-title">Before / after bandpass correction</div>', unsafe_allow_html=True)
        # TODO: confirm against design — see build spec §3. Retain JC's requested two-panel layout.
        fig = make_subplots(rows=1, cols=2, subplot_titles=("LCP", "RCP"), horizontal_spacing=0.08)
        _add_before_after(fig, 1, raw, corrected, "LCP", styles.LCP_COLOR)
        _add_before_after(fig, 2, raw, corrected, "RCP", styles.RCP_COLOR)
        if len(common_range) == 2:
            for column in (1, 2):
                fig.add_vrect(
                    x0=common_range[0], x1=common_range[1], fillcolor=theme["accent"],
                    opacity=0.08, line_width=0, row=1, col=column,
                )
        layout = styles.plotly_layout_theme(theme)
        fig.update_layout(**layout)
        fig.update_layout(
            height=430, margin=dict(l=50, r=18, t=70, b=48), hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.12, xanchor="left", x=0),
        )
        # Apply shared axis tokens to BOTH subplot axes (update_layout alone affects only x/y, not x2/y2).
        fig.update_xaxes(**layout["xaxis"])
        fig.update_yaxes(**layout["yaxis"])
        x_values = np.concatenate((raw["Vlsr"], corrected["Vlsr"]))
        fig.update_xaxes(
            title_text="Vlsr (km/s)", showline=True,
            range=[float(x_values.min()), float(x_values.max())],
            color=theme["text-body"],
            title_font=dict(color=theme["text-body"], size=13),
            tickfont=dict(color=theme["text-body"], size=11),
        )
        fig.update_yaxes(
            title_text="Temperature (K)", showline=True, color=theme["text-body"],
            title_font=dict(color=theme["text-body"], size=13),
            tickfont=dict(color=theme["text-body"], size=11),
        )
        fig.update_annotations(font=dict(color=theme["text-body"]))
        styles.render_plotly_chart(fig, use_container_width=True, config={"displayModeBar": True}, theme=None)
        if len(common_range) == 2:
            st.caption(f"Highlighted common velocity range: {common_range[0]:.3f} to {common_range[1]:.3f} km/s.")
        else:
            st.caption("No exact common velocity channels to highlight. No display shift or interpolation is applied.")
        st.caption(f"Before = {result['filename1']} · reference = {result['filename2']} · mode = {result['mode']}")


# Page rendering remains at module level, matching both uploaded Streamlit pages.
st.set_page_config(page_title="HARTSPEC — Bandpass Correction", layout="wide", initial_sidebar_state="expanded")
session_store.init_session_state()
sidebar.render_sidebar(current_stage=CURRENT_STAGE)
styles.inject_base_css()

# Native Streamlit widget labels sometimes use the static browser theme rather
# than the sidebar's dynamically selected light/dark palette.
_theme = styles.get_theme()
st.markdown(
    f"""
    <style>
    /* Keep Page 03 widget theming inside the main content. Without this
       scope it overrides Load Session / Recover checkpoint in the sidebar. */
    [data-testid="stAppViewContainer"] [data-testid="stExpander"] summary,
    [data-testid="stAppViewContainer"] [data-testid="stExpander"] summary p,
    [data-testid="stAppViewContainer"] [data-testid="stWidgetLabel"] p,
    [data-testid="stAppViewContainer"] [data-testid="stAlert"] p,
    [data-testid="stAppViewContainer"] [data-testid="stAlert"] span {{
        color: {_theme['text-body']} !important;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

if not _upstream_complete():
    _clear_stage3_and_downstream("Upstream stages are incomplete")
    styles.render_page_header(PAGE_TITLE, PAGE_SUBTITLE, CURRENT_STAGE, _completed_upstream_count())
    st.error("Bandpass correction requires Source Browser and File Loader to be completed first.")
    if st.button("Return to File Loader", key="bandpass_return_loader"):
        st.switch_page("pages/02_File_Loader.py")
    st.stop()

# Reconcile eligibility before reading a saved result, including direct sidebar visits.
restore_saved_quarantine(st.session_state)
validated_handoff = publish_validated_handoff(st.session_state, _target_filenames(), fits_ingest.get_archive_root())
styles.render_page_header(PAGE_TITLE, PAGE_SUBTITLE, CURRENT_STAGE, _completed_upstream_count())
if validated_handoff.invalidated:
    session_store.log_event(
        "Bandpass input validation changed the usable file set — previous correction and downstream results cleared "
        f"(reduction {validated_handoff.previous_session_id} → {st.session_state['session_id']})"
    )
    st.warning("The usable input files changed. Previous results were cleared; only verified pairs can be applied.")

if len(st.session_state.get("loaded_spectra") or []) < 2:
    _clear_stage3_and_downstream("Not enough verified bandpass inputs")
    st.error("Bandpass correction requires at least two successfully loaded FITS spectra that also pass verification.")
    if st.button("Return to File Loader", key="bandpass_return_loader_pair"):
        st.switch_page("pages/02_File_Loader.py")
    st.stop()

pairs, pairing_notes = _candidate_pairs()
for note in pairing_notes:
    st.warning(note)
if not pairs:
    _clear_stage3_and_downstream("No complete verified full-integration pair")
    st.error(
        "No complete verified bandpass pair is available. Both SPPOINT = 0 members must belong to one observation."
    )
    if st.button("Return to File Loader", key="bandpass_return_loader_no_pair"):
        st.switch_page("pages/02_File_Loader.py")
    st.stop()

_prepare_controls(pairs)
pair_labels = [f"Pair {i + 1}: {pair[0]['filename']} ↔ {pair[1]['filename']}" for i, pair in enumerate(pairs)]
st.markdown('<div class="hs-eyebrow">Full-integration pair</div>', unsafe_allow_html=True)
pair_index = st.selectbox(
    "Full-integration pair", options=range(len(pairs)), format_func=lambda i: pair_labels[i],
    key="bandpass_pair_index", label_visibility="collapsed",
)
selected_pair = pairs[pair_index]
if st.session_state.get("bandpass_pair_signature") != _pair_signature(selected_pair):
    _clear_stage3_and_downstream("Bandpass pair changed")
    st.session_state["bandpass_pair_signature"] = _pair_signature(selected_pair)
    suggested_mode, _ = suggest_mode(selected_pair)
    st.session_state["bandpass_mode"] = suggested_mode or MODE_OPTIONS[0]
    st.session_state["bandpass_require_apply"] = (
        bool(st.session_state.get("bandpass_selection_warning")) or not suggested_mode
    )

_render_pair_info(selected_pair, pair_index + 1, len(pairs))
st.markdown('<div class="hs-eyebrow">Bandpass mode</div>', unsafe_allow_html=True)
st.radio(
    "Bandpass mode", options=MODE_OPTIONS, horizontal=True, key="bandpass_mode",
    label_visibility="collapsed", on_change=_on_mode_change,
)
st.caption(
    "Detected pairs apply automatically when a mode is available. You can override the mode or reapply below. "
    "Committed work is checkpointed automatically; Save Session keeps an additional manual snapshot."
)
if st.session_state.get("bandpass_selection_warning"):
    st.warning(st.session_state["bandpass_selection_warning"])
elif st.session_state.get("bandpass_require_apply"):
    st.info("POSITION metadata is unavailable. Choose the switching mode, then click Apply to confirm it.")

apply_clicked = st.button("Apply / Reapply Bandpass Correction", type="primary", key="apply_bandpass_correction")
_apply_selected_pair(selected_pair, force=apply_clicked)
session_store.checkpoint_session("Bandpass pair and mode recorded")
if st.session_state.get("bandpass_error"):
    st.error(st.session_state["bandpass_error"])
stored_result = st.session_state.get("bandpass_display_result")
if stored_result and stored_result.get("mode") == st.session_state["bandpass_mode"]:
    _render_before_after(stored_result)
    if st.button("Continue to Baseline Block Editor →", type="primary", key="continue_to_baseline"):
        st.switch_page("pages/04_Baseline_Editor.py")
