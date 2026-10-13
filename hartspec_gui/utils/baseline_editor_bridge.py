# baseline_editor_bridge.py — file-backed state bridge between Streamlit Page 4 and its Dash iframe.

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from utils.session_store import SESSIONS_DIR
from utils.accessibility import normalize_font_scale

_LOCK = threading.RLock()


def _bridge_path(session_id: str) -> Path:
    """Return the per-session Page 4 bridge JSON path."""
    safe_id = "".join(ch for ch in session_id if ch.isalnum() or ch in ("-", "_"))
    return SESSIONS_DIR / f"{safe_id}.baseline_editor.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def spectrum_fingerprint(spectrum: Mapping[str, Any]) -> str:
    """Hash Vlsr/LCP/RCP arrays so stale blocks are reset when upstream data changes."""
    digest = hashlib.sha256()
    for key in ("Vlsr", "LCP", "RCP"):
        array = np.asarray(spectrum[key], dtype=np.float64)
        digest.update(key.encode("ascii"))
        digest.update(array.shape.__repr__().encode("ascii"))
        digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def _json_spectrum(spectrum: Mapping[str, Any]) -> dict[str, list[float]]:
    """Convert the three spectrum arrays into JSON-safe lists."""
    return {
        key: [float(value) for value in np.asarray(spectrum[key], dtype=float)]
        for key in ("Vlsr", "LCP", "RCP")
    }


def read_bridge(session_id: str) -> dict[str, Any] | None:
    """Read the current bridge document, returning ``None`` when absent/corrupt."""
    path = _bridge_path(session_id)
    with _LOCK:
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None


def write_bridge(session_id: str, state: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically replace one bridge document and return the written state."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = _bridge_path(session_id)
    payload = dict(state)
    payload["session_id"] = session_id
    payload["updated_at"] = _utc_now()
    temp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp.replace(path)
    return payload


def clear_bridge(session_id: str) -> None:
    """Delete the on-disk bridge document for a session, if one exists.

    03_Bandpass_Correction.py calls this whenever it invalidates Page 4's
    completion (bandpass mode changed, or a newly-applied correction differs
    from the previous one). Without this, only the in-memory
    st.session_state["baseline_corrected_spectrum"] key was being cleared --
    the bridge JSON file on disk kept the old flattened spectrum. Page 4
    itself already guards against exactly this via spectrum_fingerprint
    matching in _sync_dash_state_into_streamlit(), but only when Page 4 is
    actually visited: 07_Spectral_Fitting.py and 08_Export_and_Session.py
    both call read_bridge() directly and trust flattened_spectrum without
    any fingerprint check, so a user who changes bandpass mode and then
    jumps straight to Page 7/8 (skipping Page 4) would otherwise silently
    get fit results computed against a stale, pre-mode-change baseline.
    Deleting the file means read_bridge() correctly returns None afterward,
    so those pages fall through to their next best available spectrum
    instead of trusting stale data.
    """
    path = _bridge_path(session_id)
    with _LOCK:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def update_bridge(session_id: str, mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    """Read-modify-write the bridge under one in-process lock."""
    with _LOCK:
        state = read_bridge(session_id) or {"session_id": session_id, "events": []}
        mutator(state)
        written = write_bridge(session_id, state)
        token = written.get("checkpoint_token")
        if token:
            from utils import checkpoint_store
            try:
                record = checkpoint_store.checkpoint_from_bridge(SESSIONS_DIR, token, session_id, written)
                if record is None:
                    written["checkpoint_notice"] = (
                        "This editor is not attached to the active checkpoint. Reopen Page 4."
                    )
                else:
                    written["checkpoint_saved_at"] = record.payload["saved_at"]
            except (OSError, UnicodeError, ValueError, TypeError) as exc:
                written["checkpoint_error"] = f"Baseline checkpoint not saved: {exc}"
        return written


def initialize_bridge(
    session_id: str,
    spectrum: Mapping[str, Any],
    theme: str,
    bandpass_mode: str,
    checkpoint_token: str | None = None,
    restored_parameters: Mapping[str, Any] | None = None,
    font_scale: int = 100,
) -> dict[str, Any]:
    """Create/refresh the bridge input while preserving valid Dash-side editor state."""
    fingerprint = spectrum_fingerprint(spectrum)
    existing = read_bridge(session_id) or {}
    same_spectrum = existing.get("spectrum_fingerprint") == fingerprint

    old_manual_order = existing.get("manual_order", 3)
    old_selected_order = existing.get("selected_order")
    manual_orders = existing.get("manual_orders") or {"LCP": old_manual_order, "RCP": old_manual_order}
    selected_orders = existing.get("selected_orders")
    if selected_orders is None and old_selected_order in (3, 4, 5):
        selected_orders = {"LCP": old_selected_order, "RCP": old_selected_order}

    state: dict[str, Any] = {
        "session_id": session_id,
        "checkpoint_token": checkpoint_token or existing.get("checkpoint_token"),
        "selection_semantics": existing.get("selection_semantics", "flat_baseline_fit_regions_v2"),
        "theme": theme,
        "font_scale": normalize_font_scale(font_scale),
        "bandpass_mode": bandpass_mode,
        "spectrum_fingerprint": fingerprint,
        "spectrum": _json_spectrum(spectrum),
        "events": existing.get("events", []) if same_spectrum else [],
        "blocks": existing.get("blocks", []) if same_spectrum else [],
        "selection_mode": existing.get("selection_mode", "Automatic") if same_spectrum else "Automatic",
        "manual_orders": manual_orders if same_spectrum else {"LCP": 3, "RCP": 3},
        "selected_orders": selected_orders if same_spectrum else None,
        "fit_result": existing.get("fit_result") if same_spectrum else None,
        "flattened_spectrum": existing.get("flattened_spectrum") if same_spectrum else None,
        "integration_error": existing.get("integration_error") if same_spectrum else None,
        "complete": bool(existing.get("complete")) if same_spectrum else False,
    }
    if not same_spectrum and restored_parameters:
        # Frozen snapshots normally restore above. A parameter-only save has
        # no curves to trust; seed flat-region controls and require a new fit.
        semantics = restored_parameters.get("selection_semantics")
        if semantics == "flat_baseline_fit_regions_v2":
            state["blocks"] = restored_parameters.get("blocks", [])
            state["selection_mode"] = restored_parameters.get("selection_mode", "Automatic")
            state["manual_orders"] = restored_parameters.get("manual_orders") or (
                restored_parameters.get("selected_orders") or {"LCP": 3, "RCP": 3}
            )
    return write_bridge(session_id, state)


def append_event(state: dict[str, Any], message: str) -> None:
    """Append a uniquely identifiable event for later ingestion into FR-20 audit logging."""
    events = state.setdefault("events", [])
    events.append(
        {
            "id": uuid.uuid4().hex,
            "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "message": message,
        }
    )
