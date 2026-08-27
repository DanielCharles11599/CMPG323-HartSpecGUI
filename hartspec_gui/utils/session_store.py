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

SESSIONS_DIR = Path(os.environ.get("HARTSPEC_SESSIONS_DIR", "hartspec_gui/data/sessions"))
#SESSIONS_DIR = Path("/data/sessions")


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
    """Return saved session files, most recently modified first."""
    _ensure_sessions_dir()
    return sorted(SESSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


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
