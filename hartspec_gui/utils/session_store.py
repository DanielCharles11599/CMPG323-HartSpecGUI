# session_store.py — FR-19/20/NFR-10: manual saves, automatic checkpoints and refresh recovery.
"""Minimal JSON-backed session persistence for the HARTSPEC GUI.

Session state (parameter selections + an audit trail) is written to
``/data/sessions/<session_id>.json`` -- no database, no server API, per the
mandated architecture (no SQL/NoSQL, no REST layer). See the code-generation
prompt sections 2 and 7, and FR-19 (session save/load) / FR-20 (observation
log).

Every page imports this module and calls ``init_session_state()`` before
touching ``st.session_state``, so the schema below is guaranteed to exist
regardless of which page the user lands on first.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping

import streamlit as st

from utils import checkpoint_store
from utils.accessibility import preferences, restore_preferences
from utils.env import load_dotenv_if_present

load_dotenv_if_present()  # same defense-in-depth reason fits_ingest.py does this


def _default_sessions_dir() -> Path:
    """Resolve the sessions directory.

    Mirrors utils/source_browser_logic.py's default_fits_directory(): prefer
    the documented SESSIONS_PATH env var (the name established across this
    project's own docs and .env conventions), else the Technical
    Specifications' production path ("/data/sessions") if it actually
    exists on this machine, else a relative local-testing fallback --
    "/data/sessions" isn't even a valid path on Windows.

    Previously this read HARTSPEC_SESSIONS_DIR (a name that appears nowhere
    in the project's Business Case / Functional / Technical Specifications)
    and defaulted to "hartspec_gui/data/sessions" -- *inside* the app
    directory, which the Technical Specifications' own directory-structure
    section explicitly keeps separate from the app root. baseline_editor_bridge.py
    imports SESSIONS_DIR directly, so this also fixes where the Page 4 Dash
    bridge files land.
    """
    env_value = os.environ.get("SESSIONS_PATH")
    if env_value:
        return Path(env_value)
    production_path = Path("/data/sessions")
    if production_path.is_dir():
        return production_path
    return Path("./data/sessions")


SESSIONS_DIR = _default_sessions_dir()


def _ensure_sessions_dir() -> None:
    """Create the sessions directory on first use."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def init_session_state() -> None:
    """Populate the session-state keys this module manages, if not already set.

    Safe to call on every page load / every rerun -- ``setdefault`` is a
    no-op once the keys exist.
    """
    st.session_state.setdefault("session_id", str(uuid.uuid4())[:8])
    st.session_state.setdefault("pipeline_data", {})
    st.session_state.setdefault("completed_stages", set())
    st.session_state.setdefault("audit_log", [])
    _bootstrap_recovery()


def log_event(message: str) -> None:
    """Append a timestamped entry to the observation log (FR-20)."""
    init_session_state()
    st.session_state["audit_log"].append(
        {"ts": datetime.now(timezone.utc).strftime("%H:%M:%S"), "message": message}
    )


def mark_stage_complete(stage_key: str) -> None:
    """Record that a pipeline stage's parameters have been committed.

    Drives the pipeline progress bar -- ``completed_count()`` reads this set
    directly rather than tracking a separate counter that could drift out of
    sync (per the code-gen prompt's explicit instruction on this point).
    """
    init_session_state()
    st.session_state["completed_stages"].add(stage_key)


def completed_count() -> int:
    """Number of stages completed so far, for the header progress bar."""
    init_session_state()
    return len(st.session_state["completed_stages"])


# Stage keys in pipeline order (index 0 = Page 1). These are the keys each page
# already passes to mark_stage_complete(); kept here so "how many stages come
# before page N" has one definition instead of a hand-maintained tuple per page.
STAGE_KEYS: tuple[str, ...] = (
    "01_source_browser",
    "file_loader",
    "03_bandpass_correction",
    "04_baseline_editor",
    "05_calibration_dashboard",
    "06_pointing_correction",
    "07_spectral_fitting",
    "08_export_and_session",
)


def completed_before(current_stage: int) -> int:
    """Number of completed stages strictly before ``current_stage`` (1-indexed).

    This is what the header progress bar should show: Build Spec section 6 /
    Style Guide section 4 define "completed" as stages strictly before the
    current page, with the current page counted as in-progress. Unlike
    ``completed_count()`` it never counts the current page or later pages, so
    Page 8 cannot read "8/8 complete" while it is still "Stage 8 of 8".
    """
    init_session_state()
    completed = st.session_state["completed_stages"]
    return sum(key in completed for key in STAGE_KEYS[: max(current_stage - 1, 0)])


def save_session() -> Path:
    """Create an immutable manual save, including a frozen matching Dash snapshot.

    Repeated saves append a new filename instead of overwriting an earlier save.
    Raw FITS files and full loader arrays are never serialized into session JSON.
    """
    init_session_state()
    if st.session_state.get("checkpoint_token"):
        sync_baseline_state()
    payload = _session_payload()
    bridge = _matching_live_bridge(payload) if st.session_state.get("checkpoint_token") else None
    path = checkpoint_store.write_manual(SESSIONS_DIR, payload, bridge)
    st.session_state["checkpoint_manual_saved_at"] = checkpoint_store.utc_now()
    checkpoint_session("Manual session saved")
    return path


def list_sessions() -> list[Path]:
    """Return saved session files, most recently modified first.

    Only real session files (``<session_id>.json``) are returned. This
    directory is shared with sidecar files -- notably the Page 4 Dash bridge's
    ``<session_id>.baseline_editor.json`` (utils/baseline_editor_bridge.py),
    which Dash rewrites constantly and which therefore sorted to the top of
    this list. Loading one of those replaced the whole session with an empty
    one (it has no ``pipeline_data`` / ``completed_stages``), and it filled
    Page 8's three-row session history with non-sessions. Session ids are
    dot-free (``uuid4()[:8]``), so a dotted stem identifies a sidecar.
    """
    _ensure_sessions_dir()
    sessions = [path for path in SESSIONS_DIR.glob("*.json") if "." not in path.stem]
    return sorted(sessions, key=lambda p: p.stat().st_mtime, reverse=True)


# These namespaces belong to the reduction, not to the browser's preferences or
# optional authentication. Do not use st.session_state.clear(): it would also
# remove theme/authentication/sidebar state owned by other components. Per-file
# ingest and verification caches use dynamic keys, so exact-key cleanup alone
# is insufficient. Add a namespace here when a new stage gains runtime state.
_REDUCTION_STATE_PREFIXES = (
    "source_browser_",
    "file_loader_",
    "manual_map_",
    "bandpass_",
    "baseline_",
    "calibration_",
    "pointing_",
    "fit_",
    "spectral_fitting_",
    "export_",
)
_REDUCTION_STATE_KEYS = frozenset({
    "loaded_spectrum",
    "loaded_spectra",
    "calibrated_spectrum",
    "latest_fit",
})

# Explicit defaults prevent still-mounted frontend controls from restoring the
# previous reduction's choices. In particular, Auto hides the manual-mapping
# form for the first render, so its old widget values cannot override new defaults.
# No button state is assigned here (Streamlit buttons are transient).
_DEFAULT_REDUCTION_CONTROLS = {
    "source_browser_filename_search": "",
    "file_loader_mapping_mode": "Auto",
    "file_loader_field_search": "",
    "file_loader_show_only_flagged": False,
    "file_loader_manual_filenames_input": "",
    "bandpass_mode": "Frequency Switch",
    "fit_type": "1D Gaussian",
    "fit_polarization": "LCP",
}


def _clear_reduction_runtime_state(state: MutableMapping[str, Any]) -> None:
    """Remove this reduction's transient state, without touching saved files.

    Args:
        state: Streamlit session state, or a plain mapping in regression tests.

    The four persistent session fields are replaced by the caller after this
    cleanup. Snapshot keys before deleting, because the mapping changes size.
    Process-wide caches and Dash sidecars are deliberately not cleared: other
    users and saved reductions may still need them.
    """
    for key in list(state):
        if isinstance(key, str) and (key in _REDUCTION_STATE_KEYS or key.startswith(_REDUCTION_STATE_PREFIXES)):
            del state[key]


def _validate_session_payload(data: Any) -> dict[str, Any]:
    """Validate the existing JSON envelope before changing the active session.

    Args:
        data: The decoded JSON object read from a saved session file.

    Returns:
        The original payload, unchanged; unknown stage metadata is preserved.

    Raises:
        ValueError: Not a session saved using the existing session-store schema.

    This is an envelope check, not scientific validation. Older saves do not
    need a new schema version. Dash sidecars lack this envelope and are rejected
    instead of being treated as an empty session.
    """
    if not isinstance(data, dict):
        raise ValueError("Invalid session JSON: the root must be an object. The current session was not changed.")

    required = {"session_id", "pipeline_data", "completed_stages", "audit_log"}
    missing = sorted(required.difference(data))
    if missing:
        raise ValueError(
            "Invalid session JSON: missing " + ", ".join(missing) + ". The current session was not changed."
        )

    session_id = data["session_id"]
    if not isinstance(session_id, str) or re.fullmatch(r"[A-Za-z0-9_-]+", session_id) is None:
        raise ValueError(
            "Invalid session ID: expected a non-empty, filename-safe ID. The current session was not changed."
        )
    if not isinstance(data["pipeline_data"], dict):
        raise ValueError("Invalid session JSON: pipeline_data must be an object. The current session was not changed.")
    completed = data["completed_stages"]
    if not isinstance(completed, list) or any(not isinstance(key, str) or not key for key in completed):
        raise ValueError("Invalid session JSON: completed_stages must be a list of stage names. Session unchanged.")
    audit = data["audit_log"]
    if not isinstance(audit, list) or any(
        not isinstance(entry, dict)
        or not isinstance(entry.get("ts"), str)
        or not isinstance(entry.get("message"), str)
        for entry in audit
    ):
        raise ValueError("Invalid session JSON: audit_log must contain timestamped messages. Session unchanged.")
    return data


def _seed_reduction_controls(state: MutableMapping[str, Any], pipeline_data: Mapping[str, Any]) -> None:
    """Reset controls, then seed only values with a known saved-parameter mapping.

    Args:
        state: The active session mapping, after old reduction state is cleared.
        pipeline_data: The restored stage parameters, or an empty dict on Reset.

    Call from a button callback or before the page's parameter widgets render.
    File Loader's manual input uses setdefault
    instead of a competing widget value argument (see Page 02).
    """
    state.update(_DEFAULT_REDUCTION_CONTROLS)
    source = pipeline_data.get("01_source_browser", {})
    if isinstance(source, Mapping):
        if isinstance(source.get("source_name"), str):
            state["source_browser_source_name"] = source["source_name"]
        frequency = source.get("frequency_mhz")
        if isinstance(frequency, (int, float)) and not isinstance(frequency, bool):
            state["source_browser_frequency_mhz"] = frequency

    bandpass = pipeline_data.get("03_bandpass_correction", {})
    if isinstance(bandpass, Mapping) and bandpass.get("mode") in ("Frequency Switch", "Position Switch"):
        state["bandpass_mode"] = bandpass["mode"]

    fitting = pipeline_data.get("07_spectral_fitting", {})
    if isinstance(fitting, Mapping):
        # Prefer the requested control value over a fallback model's result.
        fit_type = fitting.get("fit_type_requested", fitting.get("fit_type"))
        if fit_type in ("1D Gaussian", "2D Gaussian", "Polynomial Peak", "Multi-component"):
            state["fit_type"] = fit_type
        if fitting.get("polarization") in ("LCP", "RCP"):
            state["fit_polarization"] = fitting["polarization"]


def load_session(path: Path, *, navigate: bool = True) -> None:
    """Restore saved parameters without reusing another reduction's arrays.

    Args:
        path: A session JSON written by save_session(), not a Dash sidecar.
        navigate: For a UI action (default), log the load and open File Loader
            to rebuild raw spectra, or Source Browser when no file selection
            was saved. False is for headless callers managing replay themselves.

    Raises:
        OSError, UnicodeError, ValueError: The file cannot be read or its envelope
            is invalid. These checks happen before clearing any active state.

    This restores metadata and supported control values, not computed arrays.
    The existing processing pages remain responsible for re-execution. A saved
    completion flag must not be mistaken for an in-memory spectrum. The UI
    must not rerun an arbitrary later page with missing inputs: Pages 3/4 can
    otherwise discard the just-restored baseline parameters or bridge. Default
    navigation interrupts that run before its later processing can execute.
    """
    record = checkpoint_store.read_record(Path(path))
    data = _validate_session_payload(record.payload)
    _validate_optional_state(data)
    completed = set(data["completed_stages"])
    _clear_reduction_runtime_state(st.session_state)
    # A frozen baseline belongs to this save, not a mutable bridge shared with an old tab.
    isolate = record.bridge is not None or _query_params() is not None
    st.session_state["session_id"] = uuid.uuid4().hex if isolate else data["session_id"]
    st.session_state["pipeline_data"] = data["pipeline_data"]
    st.session_state["completed_stages"] = completed
    st.session_state["audit_log"] = data["audit_log"]
    _seed_reduction_controls(st.session_state, data["pipeline_data"])
    _restore_extra_controls(data)
    _new_checkpoint_stream()
    _install_snapshot(record.bridge)
    st.session_state["checkpoint_rebuild_required"] = True
    if navigate:
        log_event(f"Session loaded — {data['session_id']}")
        checkpoint_session("Session loaded")
        source = data["pipeline_data"].get("01_source_browser", {})
        selected = source.get("selected_files") if isinstance(source, Mapping) else None
        has_selection = isinstance(selected, list) and bool(selected) and all(
            isinstance(filename, str) and bool(filename) for filename in selected
        )
        st.switch_page("pages/02_File_Loader.py" if has_selection else "pages/01_Source_Browser.py")


def reset_session(*, navigate: bool = True) -> None:
    """Start an empty reduction without deleting saved sessions or source files.

    Clears reduction caches and controls, preserving theme and unrelated
    session state (including optional authentication). A new session ID keeps
    the previous reduction's on-disk Dash bridge outside the new session.
    Args:
        navigate: For a UI action (default), log the reset and open Source
            Browser. False leaves navigation and logging to a headless caller.

    As with load_session(), call before parameter widgets render or in an
    on_click callback. Default navigation stops the old page from immediately
    repopulating the new session. No scientific code is executed here.
    """
    new_session_id = str(uuid.uuid4())[:8]
    _clear_reduction_runtime_state(st.session_state)
    st.session_state["session_id"] = new_session_id
    st.session_state["pipeline_data"] = {}
    st.session_state["completed_stages"] = set()
    st.session_state["audit_log"] = []
    _seed_reduction_controls(st.session_state, {})
    _new_checkpoint_stream()
    if navigate:
        log_event("Session reset — new reduction started")
        checkpoint_session("Session reset", allow_empty=True)
        st.switch_page("pages/01_Source_Browser.py")


# Browser-only recovery is initialized before any page can use old completion
# markers with missing runtime arrays. Plain mapping/headless callers can still
# use Load/Reset without navigation or needing a browser query-parameter facade.
RECOVERY_PARAM = "hartspec_resume"


def _query_params() -> Any:
    """Return the pinned Streamlit dictionary-like URL facade when available."""
    query = getattr(st, "query_params", None)
    return query if hasattr(query, "get") and hasattr(query, "__setitem__") else None


def _set_recovery_query(*, force: bool = False) -> None:
    """Re-emit on every page: Streamlit clears URL parameters on page navigation."""
    query = _query_params()
    token = st.session_state.get("checkpoint_token")
    if query is not None and token and (force or query.get(RECOVERY_PARAM) != token):
        query[RECOVERY_PARAM] = token


def _new_checkpoint_stream() -> None:
    """Detach Load/Reset from old browser/Dash writers; retain their saved files."""
    for key in list(st.session_state):
        if isinstance(key, str) and key.startswith("checkpoint_"):
            st.session_state.pop(key, None)
    if _query_params() is not None:
        st.session_state["checkpoint_token"] = uuid.uuid4().hex
        st.session_state["checkpoint_initialized"] = True
        _set_recovery_query()


def _bootstrap_recovery() -> None:
    """Recover only this URL's checkpoint, never another observer's newest save."""
    query = _query_params()
    if query is None:
        return
    if st.session_state.get("checkpoint_initialized"):
        return
    st.session_state["checkpoint_initialized"] = True  # guard recursive log/init calls
    token = query.get(RECOVERY_PARAM)
    if token and not st.session_state.get("pipeline_data"):
        try:
            record = checkpoint_store.latest(SESSIONS_DIR, token, recover=True)
            if record is not None:
                recover_checkpoint(record.path, warning=record.warning)
                return
            warning = "No saved checkpoint exists for this address. Start a reduction or load a saved session."
        except (OSError, UnicodeError, ValueError) as exc:
            warning = f"The checkpoint could not be recovered: {exc}"
        _new_checkpoint_stream()
        st.session_state["checkpoint_notice"] = warning
    else:
        _new_checkpoint_stream()


def _session_payload() -> dict[str, Any]:
    """Capture committed stage metadata and applied mapping, not draft widgets/caches."""
    state = st.session_state
    applied_ui: dict[str, Any] = {}
    if "file_loader" in state.get("pipeline_data", {}):
        if "file_loader_manual_mapping_global" in state:
            applied_ui["file_loader_manual_mapping_global"] = state["file_loader_manual_mapping_global"]
        if state.get("file_loader_mapping_mode") in ("Auto", "Manual"):
            applied_ui["file_loader_mapping_mode"] = state["file_loader_mapping_mode"]
    return checkpoint_store.json_safe({
        "session_id": state["session_id"],
        "pipeline_data": state["pipeline_data"],
        "completed_stages": sorted(state["completed_stages"]),
        "audit_log": state["audit_log"],
        "ui_state": applied_ui,
        "baseline_event_ids": state.get("baseline_editor_seen_event_ids", []),
        "preferences": preferences(state),
    })


def _validate_optional_state(data: Mapping[str, Any]) -> None:
    """Check extra saved controls before clearing a live session; unknown keys are not restored."""
    if not isinstance(data.get("ui_state", {}), dict):
        raise ValueError("Invalid saved UI state; the active session was not changed.")
    ids = data.get("baseline_event_ids", [])
    if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
        raise ValueError("Invalid saved baseline event IDs; the active session was not changed.")
    ui = data.get("ui_state", {})
    mapping = ui.get("file_loader_manual_mapping_global", {})
    if not isinstance(mapping, dict) or any(
        not isinstance(key, str) or not (
            value is None or isinstance(value, str)
            or isinstance(value, list) and all(item is None or isinstance(item, str) for item in value)
        ) for key, value in mapping.items()
    ):
        raise ValueError("Invalid saved header mapping; the active session was not changed.")
    for key, value in mapping.items():
        if key == "LCP/RCP":
            valid = value is None or (isinstance(value, list) and len(value) == 2)
        else:
            valid = value is None or isinstance(value, str)
        if not valid:
            raise ValueError("Invalid saved header mapping; the active session was not changed.")


def _restore_extra_controls(data: Mapping[str, Any]) -> None:
    """Restore only explicitly supported, committed fields; never restore button/auth state."""
    state = st.session_state
    ui = data.get("ui_state", {})
    if "file_loader_manual_mapping_global" in ui:
        state["file_loader_manual_mapping_global"] = ui["file_loader_manual_mapping_global"]
    if ui.get("file_loader_mapping_mode") in ("Auto", "Manual"):
        state["file_loader_mapping_mode"] = ui["file_loader_mapping_mode"]
    if data.get("baseline_event_ids"):
        state["baseline_editor_seen_event_ids"] = list(data["baseline_event_ids"])
    pipeline = data["pipeline_data"]
    source = pipeline.get("01_source_browser", {})
    if isinstance(source, Mapping):
        directory = source.get("browser_directory")
        if isinstance(directory, str) and directory:
            state["source_browser_fits_dir"] = directory
        if isinstance(source.get("filename_search"), str):
            state["source_browser_filename_search"] = source["filename_search"]
    pointing = pipeline.get("06_pointing_correction", {})
    if isinstance(pointing, Mapping):
        scan_key = pointing.get("scan_key")
        if isinstance(scan_key, str) and scan_key:
            state["pointing_scan_key"] = scan_key
            velocities = pointing.get("picked_velocities")
            velocities = velocities if isinstance(velocities, Mapping) else {}
            for role, velocity in velocities.items():
                if role in ("N", "S", "E", "W", "Centre") and _finite_number(velocity):
                    state[f"pointing_pick::{scan_key}::{role}"] = float(velocity)
            if _finite_number(pointing.get("hpbw_deg")):
                state[f"pointing_hpbw::{scan_key}"] = float(pointing["hpbw_deg"])
            if _finite_number(pointing.get("half_width_channels")):
                state[f"pointing_half_width::{scan_key}"] = int(pointing["half_width_channels"])
        if pointing.get("input_source") == "manual entry":
            powers = pointing.get("peak_powers")
            powers = powers if isinstance(powers, Mapping) else {}
            for role, power in powers.items():
                if role in ("N", "S", "E", "W", "Centre") and _finite_number(power):
                    state[f"pointing_manual::{role}"] = float(power)
            if _finite_number(pointing.get("hpbw_deg")):
                state["pointing_manual::hpbw"] = float(pointing["hpbw_deg"])


def _finite_number(value: Any) -> bool:
    """Reject booleans/non-finite values before seeding a numeric widget."""
    import math
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _matching_live_bridge(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Freeze a matching working/pending snapshot without exposing it as verified runtime data."""
    current = st.session_state.get("bandpass_corrected_spectrum")
    bandpass = payload.get("pipeline_data", {}).get("03_bandpass_correction", {})
    if current is not None and (
        not isinstance(bandpass, Mapping)
        or checkpoint_store._spectrum_digest(current) != bandpass.get("corrected_fingerprint")
    ):
        return None
    pending = st.session_state.get("checkpoint_pending_bridge")
    if pending and pending["session_id"] == payload["session_id"]:
        return checkpoint_store.matching_bridge(payload, pending["bridge"])
    from utils import baseline_editor_bridge
    return checkpoint_store.matching_bridge(payload, baseline_editor_bridge.read_bridge(payload["session_id"]))


def _install_snapshot(bridge: Mapping[str, Any] | None) -> None:
    """Hold a frozen bridge until Page 3 revalidates/reproduces its input.

    It remains in the new recovery checkpoint, but Pages 07/08 cannot read it
    through the working bridge before FITS validation and bandpass replay.
    """
    if bridge is not None:
        st.session_state["checkpoint_pending_bridge"] = {
            "session_id": st.session_state["session_id"], "bridge": dict(bridge),
        }


def _activate_pending_snapshot() -> None:
    """Publish a restored baseline only after its bandpass input is rebuilt unchanged."""
    state = st.session_state
    pending = state.get("checkpoint_pending_bridge")
    if pending and pending["session_id"] != state["session_id"]:
        state.pop("checkpoint_pending_bridge", None)
        pending = None
    spectrum = state.get("bandpass_corrected_spectrum")
    if spectrum is None:
        return
    saved = state["pipeline_data"].get("03_bandpass_correction", {})
    if (not isinstance(saved, Mapping)
            or checkpoint_store._spectrum_digest(spectrum) != saved.get("corrected_fingerprint")):
        return
    if pending:
        bridge = checkpoint_store.matching_bridge(_session_payload(), pending["bridge"])
        if bridge is None:
            state.pop("checkpoint_pending_bridge", None)
            return
        from utils import baseline_editor_bridge
        bridge["theme"] = state.get("theme", "light")
        bridge["font_scale"] = preferences(state)["font_scale"]
        bridge["checkpoint_token"] = state.get("checkpoint_token")
        baseline_editor_bridge.write_bridge(state["session_id"], bridge)
        state.pop("checkpoint_pending_bridge", None)
    state["checkpoint_rebuild_required"] = False


def _discard_baseline_runtime() -> None:
    """Reject unprovable baseline provenance without deleting saved snapshots or bridge files."""
    from utils.stage_invalidation import invalidate_baseline_dependents
    state = st.session_state
    state["completed_stages"].discard("04_baseline_editor")
    state["pipeline_data"].pop("04_baseline_editor", None)
    state.pop("baseline_corrected_spectrum", None)
    state.pop("export_cache", None)
    invalidate_baseline_dependents(state)


def _apply_bridge(bridge: Mapping[str, Any]) -> None:
    """Synchronize Dash before any later page can fit/export an old calibrated spectrum."""
    state = st.session_state
    current_fingerprint = checkpoint_store._spectrum_digest(state.get("bandpass_corrected_spectrum"))
    if current_fingerprint != bridge.get("spectrum_fingerprint"):
        _discard_baseline_runtime()
        return
    payload, invalidated = checkpoint_store.merge_baseline(_session_payload(), bridge)
    state["pipeline_data"] = payload["pipeline_data"]
    state["completed_stages"] = set(payload["completed_stages"])
    state["audit_log"] = payload["audit_log"]
    state["baseline_editor_seen_event_ids"] = payload["baseline_event_ids"]
    if payload["pipeline_data"]["04_baseline_editor"]["complete"]:
        state["baseline_corrected_spectrum"] = bridge["flattened_spectrum"]
    else:
        state.pop("baseline_corrected_spectrum", None)
    if invalidated:
        # Do not remove mounted selector widgets; only computed runtime outputs.
        for key in ("calibrated_spectrum", "latest_fit", "export_cache"):
            state.pop(key, None)


def sync_baseline_state() -> None:
    """Pull committed bridge edits globally, including when Page 4 was skipped."""
    if not st.session_state.get("checkpoint_token") or st.session_state.get("bandpass_corrected_spectrum") is None:
        return
    _activate_pending_snapshot()
    payload = _session_payload()
    bridge = _matching_live_bridge(payload)
    if bridge is not None:
        _apply_bridge(bridge)
    else:
        from utils import baseline_editor_bridge
        current = st.session_state.get("bandpass_corrected_spectrum")
        saved = payload["pipeline_data"].get("03_bandpass_correction", {})
        expected = saved.get("corrected_fingerprint") if isinstance(saved, Mapping) else None
        if (checkpoint_store._spectrum_digest(current) != expected
                or baseline_editor_bridge.read_bridge(st.session_state["session_id"]) is not None):
            _discard_baseline_runtime()


def _record_status(record: Any) -> None:
    """Record successful persistence only after the immutable files were published."""
    state = st.session_state
    state["checkpoint_revision"] = record.revision
    state["checkpoint_saved_at"] = record.payload["saved_at"]
    state["checkpoint_saved_session_id"] = record.payload["session_id"]
    state["checkpoint_path"] = str(record.path)
    state.pop("checkpoint_error", None)


def _accept_dash_revision() -> None:
    """Acknowledge a Dash-only advance, not arbitrary stale state from another writer."""
    state = st.session_state
    record = checkpoint_store.latest(SESSIONS_DIR, state["checkpoint_token"])
    if record is None or record.revision == state.get("checkpoint_revision"):
        return
    if record.payload.get("checkpoint", {}).get("reason") != "Baseline editor updated" or record.bridge is None:
        raise checkpoint_store.CheckpointConflict("A newer checkpoint exists. Recover it before continuing.")
    owner = record.payload.get("session_id")
    if owner == state["session_id"]:
        if state.get("bandpass_corrected_spectrum") is not None:
            _apply_bridge(record.bridge)
    elif owner != state.get("checkpoint_saved_session_id"):
        raise checkpoint_store.CheckpointConflict("The recovery stream belongs to another reduction. Recover it first.")
    # On a deliberate ID change, acknowledge the old Dash save but do not copy
    # any of its baseline or downstream parameters into the new reduction.
    _record_status(record)


def checkpoint_session(reason: str = "Stage parameters committed", *, allow_empty: bool = False) -> Path | None:
    """Save a changed committed state, including invalidations; report failures without losing memory.

    Pages call this after their parameter/audit updates, not inside
    mark_stage_complete(). That helper is also called while merely rendering
    already-completed stages. A content hash suppresses ordinary-rerun writes.
    """
    state = st.session_state
    if not state.get("checkpoint_token") or (
        not state.get("pipeline_data") and not allow_empty and not state.get("checkpoint_revision")
    ):
        return None
    try:
        # Never hold the checkpoint lock while acquiring the bridge lock: Dash
        # publishes in bridge -> checkpoint order. CAS detects an intervening write.
        _accept_dash_revision()
        sync_baseline_state()
        payload = _session_payload()
        bridge = _matching_live_bridge(payload)
        record = checkpoint_store.write_checkpoint(
            SESSIONS_DIR, state["checkpoint_token"], payload, bridge, reason=reason,
            expected_revision=state.get("checkpoint_revision"),
        )
        _record_status(record)
        _set_recovery_query()
        render_checkpoint_status()
        return record.path
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        state["checkpoint_error"] = f"Checkpoint not saved: {exc} Current work remains in memory."
        render_checkpoint_status()
        return None


def recover_checkpoint(path: Path, *, navigate: bool = True, warning: str = "") -> None:
    """Resume a validated checkpoint in an isolated working reduction and browser stream.

    Runtime loader/calibration/fit caches are not restored. Re-enter at File
    Loader; existing pages reconstruct them. The exact baseline sidecar is
    cloned, so later edits or delayed old Dash callbacks cannot replace it.
    """
    record = checkpoint_store.read_record(Path(path))
    data = _validate_session_payload(record.payload)
    _validate_optional_state(data)
    _clear_reduction_runtime_state(st.session_state)
    state = st.session_state
    state["session_id"] = uuid.uuid4().hex
    state["pipeline_data"] = data["pipeline_data"]
    state["completed_stages"] = set(data["completed_stages"])
    state["audit_log"] = data["audit_log"]
    restore_preferences(state, data.get("preferences"))
    _seed_reduction_controls(state, data["pipeline_data"])
    _restore_extra_controls(data)
    _new_checkpoint_stream()
    _install_snapshot(record.bridge)
    state["checkpoint_rebuild_required"] = True
    log_event(f"Checkpoint recovered from reduction {data['session_id']} — runtime inputs will be rebuilt")
    state["checkpoint_notice"] = (
        "Checkpoint recovered. Saved parameters and the matching baseline snapshot were restored. "
        "Reload the FITS inputs, then revisit the later stages to rebuild runtime results. " + warning
    )
    checkpoint_session("Checkpoint recovered", allow_empty=True)
    if navigate:
        source = data["pipeline_data"].get("01_source_browser", {})
        files = source.get("selected_files") if isinstance(source, Mapping) else None
        st.switch_page("pages/02_File_Loader.py" if isinstance(files, list) and files else "pages/01_Source_Browser.py")


def begin_page(current_stage: int) -> None:
    """Run before page widgets: synchronize Dash and repair the per-page recovery URL."""
    init_session_state()
    st.session_state["checkpoint_current_stage"] = current_stage
    if st.session_state.get("checkpoint_rebuild_required") and current_stage > 2:
        if not st.session_state.get("loaded_spectra"):
            st.switch_page("pages/02_File_Loader.py")
        if current_stage > 3 and st.session_state.get("bandpass_corrected_spectrum") is None:
            st.switch_page("pages/03_Bandpass_Correction.py")
    if st.session_state.get("checkpoint_token"):
        try:
            _accept_dash_revision()
            sync_baseline_state()
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            st.session_state["checkpoint_error"] = f"Checkpoint synchronization failed: {exc}"
    _set_recovery_query(force=True)


def render_checkpoint_status() -> None:
    """Update the shared sidebar placeholder after commits on the same rerun."""
    state = st.session_state
    placeholder = state.get("checkpoint_status_placeholder")
    if placeholder is None:
        return
    error = state.get("checkpoint_error")
    if error:
        placeholder.warning(error)
        return
    saved = state.get("checkpoint_saved_at")
    if state.get("checkpoint_saved_session_id") != state.get("session_id"):
        saved = None
    label = datetime.fromisoformat(saved).strftime("%Y-%m-%d %H:%M:%S UTC") if saved else "Not yet checkpointed"
    count = len(state.get("loaded_spectra") or [])
    stage = state.get("checkpoint_current_stage", 1)
    placeholder.caption(f"Stage {stage} of 8 · {count} files loaded\n\nLast checkpoint: {label}")
    