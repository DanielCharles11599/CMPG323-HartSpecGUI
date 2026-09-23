"""
utils/session.py — session-state schema, audit trail, and JSON persistence
shared by every pipeline page (FR-19/20).

Source of truth for "completed stage": a stage counts once its key exists
under st.session_state["session"] — not via a separately tracked progress
counter that can drift out of sync (build spec §6).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import streamlit as st

# Order matches pages/01..08 — index i is "stage i+1"
STAGE_KEYS = [
    "source",       # 01 Source Browser
    "file_loader",  # 02 File Loader
    "bandpass",     # 03 Bandpass Correction
    "baseline",     # 04 Baseline Block Editor
    "calibration",  # 05 Calibration Dashboard
    "pointing",     # 06 Pointing Correction
    "fitting",      # 07 Spectral Fitting
    "export",       # 08 Export & Session
]

# Per the project prompt's .env convention — never hardcode a path that
# assumes data lives alongside the app code.
SESSIONS_PATH = Path(os.environ.get("SESSIONS_PATH", "./data/sessions"))


def init_session() -> None:
    """Ensure st.session_state["session"], ["audit_log"], and ["theme"]
    exist. Idempotent — safe to call at the top of every page."""
    if "session" not in st.session_state:
        st.session_state["session"] = {
            "session_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "created": datetime.now(timezone.utc).isoformat(),
        }
    if "audit_log" not in st.session_state:
        st.session_state["audit_log"] = []
    if "theme" not in st.session_state:
        st.session_state["theme"] = "light"


def log_action(message: str) -> None:
    """Append a timestamped line to the Observation Log (FR-20). Every
    parameter change on every page should call this — the log on page 08
    is a live view of this list, not static text."""
    init_session()
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state["audit_log"].append(f"{ts} {message}")


def completed_stages(current_stage_index: int) -> int:
    """Number of stages strictly before current_stage_index (0-based) whose
    key already exists in the session dict. The current page never counts
    as complete, even if its key already exists mid-edit."""
    init_session()
    sess = st.session_state["session"]
    return sum(1 for i in range(current_stage_index) if STAGE_KEYS[i] in sess)


def set_stage_data(stage_key: str, data: dict) -> None:
    init_session()
    st.session_state["session"][stage_key] = data


def get_stage_data(stage_key: str) -> Optional[dict]:
    init_session()
    return st.session_state["session"].get(stage_key)


def save_session(label: str = "") -> Path:
    """Write the current session dict + audit log to SESSIONS_PATH as JSON
    (FR-19). Filename is timestamp-based so history sorts naturally."""
    init_session()
    SESSIONS_PATH.mkdir(parents=True, exist_ok=True)
    payload = {
        **st.session_state["session"],
        "audit_log": st.session_state["audit_log"],
        "label": label or st.session_state["session"].get("session_id"),
    }
    fname = f"{payload['session_id']}.json"
    path = SESSIONS_PATH / fname
    path.write_text(json.dumps(payload, indent=2, default=str))
    log_action(f"Session saved — {fname}")
    return path


def list_saved_sessions(limit: int = 3) -> list[Path]:
    if not SESSIONS_PATH.exists():
        return []
    files = sorted(SESSIONS_PATH.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def load_session(path: Path) -> None:
    """Replay a saved session — pre-fill every prior stage with its saved
    parameters (FR-19). Overwrites current in-memory session state."""
    payload = json.loads(Path(path).read_text())
    audit_log = payload.pop("audit_log", [])
    payload.pop("label", None)
    st.session_state["session"] = payload
    st.session_state["audit_log"] = audit_log
    log_action(f"Session loaded — {Path(path).stem}")


def reset_session() -> None:
    st.session_state["session"] = {
        "session_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "created": datetime.now(timezone.utc).isoformat(),
    }
    st.session_state["audit_log"] = []
