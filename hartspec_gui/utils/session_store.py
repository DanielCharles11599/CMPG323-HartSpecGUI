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

import json
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import streamlit as st

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
    """Write the current session to ``/data/sessions/<id>.json``.

    Returns
    -------
    Path
        The file that was written, so callers can show a confirmation.
    """
    init_session_state()
    _ensure_sessions_dir()
    payload: dict[str, Any] = {
        "session_id": st.session_state["session_id"],
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_data": st.session_state["pipeline_data"],
        "completed_stages": sorted(st.session_state["completed_stages"]),
        "audit_log": st.session_state["audit_log"],
    }
    path = SESSIONS_DIR / f"{st.session_state['session_id']}.json"
    path.write_text(json.dumps(payload, indent=2))
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


def load_session(path: Path) -> None:
    """Replace the current session state with a previously saved one.

    This "replays" a session per FR-19: every prior stage's parameters are
    pre-filled from the loaded file, and pages re-read ``pipeline_data`` on
    their next render.
    """
    data = json.loads(path.read_text())
    st.session_state["session_id"] = data.get("session_id", st.session_state.get("session_id"))
    st.session_state["pipeline_data"] = data.get("pipeline_data", {})
    st.session_state["completed_stages"] = set(data.get("completed_stages", []))
    st.session_state["audit_log"] = data.get("audit_log", [])


def reset_session() -> None:
    """Clear the current session's parameters and start a fresh session id.

    Deliberately does not touch ``st.session_state["theme"]`` -- resetting a
    reduction session shouldn't also flip the user's display preference.
    """
    st.session_state["session_id"] = str(uuid.uuid4())[:8]
    st.session_state["pipeline_data"] = {}
    st.session_state["completed_stages"] = set()
    st.session_state["audit_log"] = []
