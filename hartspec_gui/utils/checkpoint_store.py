# checkpoint_store.py — FR-19/NFR-10: immutable JSON checkpoints shared by Streamlit and Dash.
"""File I/O and baseline snapshot rules, without a Streamlit runtime dependency.

Parameter envelopes stay small. A separate immutable sidecar freezes the existing
Dash bridge (including its already-computed arrays); raw FITS data is never copied.
One RLock serializes writers in the supplied single-process Streamlit/Dash deployment.
This is not a distributed/multi-worker locking protocol.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from utils.baseline_editor_logic import rows_equal, stage_payload

LOCK = threading.RLock()
TOKEN_PATTERN = re.compile(r"[a-f0-9]{32}")
BASELINE = "04_baseline_editor"
BANDPASS = "03_bandpass_correction"
DEPENDENTS = ("05_calibration_dashboard", "07_spectral_fitting", "08_export_and_session")
MAX_JSON_BYTES = 64 * 1024 * 1024


class CheckpointError(ValueError):
    """The checkpoint cannot be read/written safely; retain the active reduction."""


class CheckpointConflict(CheckpointError):
    """Another writer advanced this recovery stream; do not overwrite its work."""


def utc_now() -> str:
    """Return an explicit UTC timestamp for stored records and status labels."""
    return datetime.now(timezone.utc).isoformat()


def json_safe(value: Any) -> Any:
    """Copy metadata into strict JSON types, rejecting non-finite/unserializable values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not math.isfinite(number):
            raise CheckpointError("Cannot checkpoint NaN or infinite parameter values.")
        return number
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, Mapping):
        if any(not isinstance(key, (str, int)) for key in value):
            raise CheckpointError("Checkpoint parameter names must be strings or integer order numbers.")
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    raise CheckpointError(f"Cannot checkpoint parameter of type {type(value).__name__}.")


def _encode(value: Any) -> bytes:
    """Canonical JSON makes content comparisons independent of dictionary insertion order."""
    return json.dumps(json_safe(value), sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    """Hash a canonical metadata structure, not raw observation files."""
    return hashlib.sha256(_encode(value)).hexdigest()


def _atomic_create(path: Path, content: bytes) -> None:
    """Publish a complete file exclusively; never overwrite an existing snapshot.

    A temporary file is fsynced before an exclusive hard-link publication in the
    same directory. A failed write/link leaves earlier checkpoints untouched.
    Requires a local filesystem supporting hard links (the documented deployment).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".hartspec-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    """Reject oversized, non-object and non-standard JSON before using saved metadata."""
    if path.stat().st_size > MAX_JSON_BYTES:
        raise CheckpointError("Checkpoint exceeds the 64 MiB safety limit.")

    def invalid_constant(value: str) -> None:
        raise CheckpointError(f"Invalid JSON numeric constant: {value}.")

    data = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=invalid_constant)
    if not isinstance(data, dict):
        raise CheckpointError("The saved JSON is not an object.")
    return data


def token_directory(root: Path, token: str) -> Path:
    """Resolve only an opaque 128-bit recovery token, never an arbitrary browser path."""
    if not isinstance(token, str) or TOKEN_PATTERN.fullmatch(token) is None:
        raise CheckpointError("Invalid recovery identifier.")
    directory = root / "checkpoints" / token
    if directory.is_symlink():
        raise CheckpointError("Recovery directories must not be symbolic links.")
    return directory


def _spectrum_digest(spectrum: Any) -> str | None:
    """Validate/hash existing bridge arrays using the bridge's fingerprint convention."""
    if not isinstance(spectrum, Mapping):
        return None
    digest = hashlib.sha256()
    lengths = set()
    try:
        for key in ("Vlsr", "LCP", "RCP"):
            array = np.asarray(spectrum[key], dtype=np.float64)
            if array.ndim != 1 or array.size == 0 or not np.all(np.isfinite(array)):
                return None
            lengths.add(array.size)
            digest.update(key.encode("ascii"))
            digest.update(repr(array.shape).encode("ascii"))
            digest.update(array.tobytes(order="C"))
    except (KeyError, TypeError, ValueError):
        return None
    return digest.hexdigest() if len(lengths) == 1 else None


def matching_bridge(payload: Mapping[str, Any], bridge: Any) -> dict[str, Any] | None:
    """Freeze only a bridge provably attached to the committed Page 3 result."""
    pipeline = payload.get("pipeline_data")
    if not isinstance(pipeline, Mapping):
        return None
    bandpass = pipeline.get(BANDPASS, {})
    if not isinstance(bridge, Mapping) or not isinstance(bandpass, Mapping):
        return None
    fingerprint = bandpass.get("corrected_fingerprint")
    upstream = ("01_source_browser", "file_loader", BANDPASS)
    if not fingerprint or any(stage not in payload.get("completed_stages", []) for stage in upstream):
        return None
    if bridge.get("spectrum_fingerprint") != fingerprint or _spectrum_digest(bridge.get("spectrum")) != fingerprint:
        return None
    # Do not serialize browser recovery tokens or transient write-status messages into sidecars.
    frozen = {key: value for key, value in bridge.items() if not key.startswith("checkpoint_")}
    frozen.pop("updated_at", None)
    frozen.pop("theme", None)
    fit = frozen.get("fit_result")
    rows = frozen.get("blocks", [])
    if fit and (not isinstance(fit, Mapping) or not rows_equal(rows, fit.get("blocks") or [])):
        frozen.update(fit_result=None, selected_orders=None, flattened_spectrum=None, complete=False)
    if not _spectrum_digest(frozen.get("flattened_spectrum")):
        frozen["complete"] = False
        frozen["flattened_spectrum"] = None
    return json_safe(frozen)


def _baseline_identity(summary: Any) -> Any:
    """Only actual selection/output changes invalidate calibration and fitting."""
    if not isinstance(summary, Mapping):
        return None
    return {key: summary.get(key) for key in (
        "blocks", "selection_mode", "selected_orders", "complete", "flattened_fingerprint",
    )}


def merge_baseline(payload: Mapping[str, Any], bridge: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    """Merge the current valid bridge and its unique audit events into parameter metadata.

    Returns the new envelope and whether dependent runtime results must be cleared.
    Pointing is not a baseline dependency, matching stage_invalidation.py.
    """
    result = copy.deepcopy(dict(payload))
    pipeline = result.setdefault("pipeline_data", {})
    previous = pipeline.get(BASELINE)
    summary = stage_payload(bridge.get("blocks", []), bridge.get("selection_mode", "Automatic"),
                            bridge.get("selected_orders"), bridge.get("fit_result"))
    summary.update({
        "manual_orders": bridge.get("manual_orders", {"LCP": 3, "RCP": 3}),
        "selection_semantics": "flat_baseline_fit_regions_v2",
        "selected_regions_are_masked": False,
        "fit_uses_selected_flat_regions": True,
        "output_preserves_full_velocity_axis": True,
        "spectrum_fingerprint": bridge.get("spectrum_fingerprint"),
        "flattened_fingerprint": _spectrum_digest(bridge.get("flattened_spectrum")),
    })
    summary["complete"] = bool(summary["complete"] and bridge.get("complete") and summary["flattened_fingerprint"])
    changed = _baseline_identity(previous) != _baseline_identity(summary)
    completed = set(result.get("completed_stages", []))
    invalidated = changed and any(key in pipeline or key in completed for key in DEPENDENTS)
    if changed:
        for key in DEPENDENTS:
            pipeline.pop(key, None)
            completed.discard(key)
    pipeline[BASELINE] = summary
    if summary["complete"]:
        completed.add(BASELINE)
    else:
        completed.discard(BASELINE)
    result["completed_stages"] = sorted(completed)
    seen = set(result.get("baseline_event_ids", []))
    audit = result.setdefault("audit_log", [])
    for event in bridge.get("events", []):
        if not isinstance(event, Mapping):
            continue
        event_id = event.get("id")
        if isinstance(event_id, str) and event_id and event_id not in seen and isinstance(event.get("message"), str):
            audit.append({"ts": str(event.get("ts", "")), "message": event["message"]})
            seen.add(event_id)
    if invalidated:
        audit.append({"ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                      "message": "Baseline selection/output changed — calibration, fit and export invalidated"})
    result["baseline_event_ids"] = sorted(seen)
    return json_safe(result), invalidated


def _content_hash(payload: Mapping[str, Any], bridge: Any) -> str:
    """Ordinary reruns do not append revisions for timestamps or display preferences."""
    content = {key: value for key, value in payload.items()
               if key not in ("saved_at", "checkpoint", "baseline_snapshot", "preferences")}
    return _digest({"parameters": content, "baseline": bridge})


@dataclass(frozen=True)
class Record:
    """A fully read/written revision, with an optional frozen baseline sidecar."""
    path: Path
    payload: dict[str, Any]
    bridge: dict[str, Any] | None
    created: bool = False
    warning: str = ""

    @property
    def revision(self) -> str:
        """Opaque revision ID used for compare-and-swap between concurrent writers."""
        return str(self.payload.get("checkpoint", {}).get("revision", ""))


def read_record(path: Path) -> Record:
    """Read one envelope and its checksum-verified, adjacent immutable bridge snapshot."""
    if path.is_symlink():
        raise CheckpointError("Saved snapshots must not be symbolic links.")
    payload = _read_json(path)
    meta = payload.get("checkpoint", {})
    if not isinstance(meta, dict):
        raise CheckpointError("Invalid checkpoint metadata.")
    if meta:
        if (not isinstance(payload.get("session_id"), str)
                or not isinstance(payload.get("pipeline_data"), dict)
                or not isinstance(payload.get("completed_stages"), list)
                or not isinstance(payload.get("audit_log"), list)
                or not isinstance(payload.get("saved_at"), str)
                or not isinstance(meta.get("sequence"), int)
                or isinstance(meta.get("sequence"), bool) or meta["sequence"] < 1):
            raise CheckpointError("Invalid checkpoint envelope.")
        try:
            datetime.fromisoformat(payload["saved_at"])
        except ValueError as exc:
            raise CheckpointError("Invalid checkpoint timestamp.") from exc
    snapshot = payload.get("baseline_snapshot")
    bridge = None
    if snapshot is not None:
        if not isinstance(snapshot, dict):
            raise CheckpointError("Invalid baseline snapshot reference.")
        name = snapshot.get("file")
        if not isinstance(name, str) or not name or Path(name).name != name or "/" in name or "\\" in name:
            raise CheckpointError("A baseline snapshot must be an adjacent file, not an arbitrary path.")
        if name != path.stem + ".baseline_editor.json":
            raise CheckpointError("The baseline snapshot does not belong to this saved record.")
        snapshot_path = path.parent / name
        if snapshot_path.is_symlink():
            raise CheckpointError("Baseline snapshots must not be symbolic links.")
        if snapshot_path.stat().st_size > MAX_JSON_BYTES:
            raise CheckpointError("Baseline snapshot exceeds the safety limit.")
        raw = snapshot_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != snapshot.get("sha256"):
            raise CheckpointError("The saved baseline snapshot checksum does not match.")
        bridge = _read_json(snapshot_path)
        if matching_bridge(payload, bridge) is None:
            raise CheckpointError("The saved baseline does not match its bandpass parameters.")
    if meta and (meta.get("version") != 1 or meta.get("revision") != path.stem):
        raise CheckpointError("Unsupported or mismatched checkpoint version/revision.")
    if meta and meta.get("content_hash") != _content_hash(payload, bridge):
        raise CheckpointError("Checkpoint content checksum does not match.")
    return Record(path, payload, bridge)


def latest(root: Path, token: str, *, recover: bool = False) -> Record | None:
    """Find this browser's newest checkpoint; recovery can fall back after a damaged revision."""
    directory = token_directory(root, token)
    paths = sorted(directory.glob("*.json"), reverse=True)
    paths = [path for path in paths if ".baseline_editor." not in path.name]
    errors = []
    for path in paths:
        try:
            record = read_record(path)
            if not record.revision or not isinstance(record.payload.get("pipeline_data"), dict):
                raise CheckpointError("Recovery file lacks checkpoint metadata.")
            warning = "Newer checkpoint(s) were unreadable; recovered the preceding valid revision." if errors else ""
            return Record(record.path, record.payload, record.bridge, warning=warning)
        except (OSError, UnicodeError, ValueError) as exc:
            if not recover:
                raise CheckpointError(f"Latest checkpoint is unreadable: {exc}") from exc
            errors.append(str(exc))
    if errors:
        raise CheckpointError("No valid checkpoint remains in this recovery stream. Use a saved session.")
    return None


def _publish(path: Path, payload: Mapping[str, Any], bridge: dict[str, Any] | None) -> dict[str, Any]:
    """Publish sidecar first, then the envelope that makes the complete revision visible."""
    document = json_safe(payload)
    document.pop("baseline_snapshot", None)
    if bridge is not None:
        data = _encode(bridge)
        if len(data) > MAX_JSON_BYTES:
            raise CheckpointError("Baseline snapshot exceeds the 64 MiB safety limit.")
        sidecar = path.with_name(path.stem + ".baseline_editor.json")
        _atomic_create(sidecar, data)
        document["baseline_snapshot"] = {"file": sidecar.name, "sha256": hashlib.sha256(data).hexdigest()}
    content = _encode(document)
    if len(content) > MAX_JSON_BYTES:
        raise CheckpointError("Checkpoint parameter envelope exceeds the safety limit.")
    _atomic_create(path, content)
    return document


def write_checkpoint(
    root: Path, token: str, payload: Mapping[str, Any], bridge: dict[str, Any] | None, *,
    reason: str, expected_revision: str | None,
) -> Record:
    """Append a changed checkpoint, or reuse the previous one without touching its mtime."""
    with LOCK:
        current = latest(root, token)
        digest = _content_hash(payload, bridge)
        if current and current.payload["checkpoint"]["content_hash"] == digest:
            return current
        current_revision = current.revision if current else None
        if current_revision != expected_revision:
            raise CheckpointConflict("A newer checkpoint exists. Reload/recover it instead of overwriting it.")
        # Sequence ordering remains correct even if the server's wall clock is adjusted.
        sequence = int(current.payload["checkpoint"].get("sequence", 0)) + 1 if current else 1
        revision = f"{sequence:012d}_{uuid.uuid4().hex}"
        path = token_directory(root, token) / f"{revision}.json"
        document = dict(payload)
        document["saved_at"] = utc_now()
        document["checkpoint"] = {
            "version": 1, "revision": revision, "sequence": sequence, "reason": reason, "content_hash": digest,
        }
        document = _publish(path, document, bridge)
        return Record(path, document, bridge, created=True)


def write_manual(root: Path, payload: Mapping[str, Any], bridge: dict[str, Any] | None) -> Path:
    """Save an immutable manual session; retain every previously saved JSON and sidecar."""
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or re.fullmatch(r"[A-Za-z0-9_-]+", session_id) is None:
        raise CheckpointError("Invalid session ID; the session was not saved.")
    with LOCK:
        path = root / f"{session_id}.json"
        if path.exists() or (bridge is not None and path.with_name(path.stem + ".baseline_editor.json").exists()):
            path = root / f"{session_id}_{uuid.uuid4().hex}.json"
        document = dict(payload)
        document.pop("checkpoint", None)
        document["saved_at"] = utc_now()
        _publish(path, document, bridge)
        return path


def checkpoint_from_bridge(root: Path, token: str, session_id: str, bridge: Mapping[str, Any]) -> Record | None:
    """Dash-only checkpoint: merge baseline data, never touch another/newer reduction.

    The parent checkpoint supplies other stages and UI parameters. A stale iframe
    cannot create a stream or change one whose active session/bandpass has changed.
    """
    with LOCK:
        current = latest(root, token)
        if current is None or current.payload.get("session_id") != session_id:
            return None
        frozen = matching_bridge(current.payload, bridge)
        if frozen is None:
            return None
        payload, _ = merge_baseline(current.payload, frozen)
        return write_checkpoint(root, token, payload, frozen, reason="Baseline editor updated",
                                expected_revision=current.revision)


def list_latest(root: Path) -> list[Record]:
    """List recoverable streams for an explicit chooser; never auto-load a global newest session."""
    records = []
    for directory in (root / "checkpoints").glob("*"):
        if not directory.is_dir() or TOKEN_PATTERN.fullmatch(directory.name) is None:
            continue
        try:
            record = latest(root, directory.name, recover=True)
        except (OSError, ValueError, UnicodeError):
            continue
        if record is not None:
            records.append(record)
    return sorted(records, key=lambda item: item.payload.get("saved_at", ""), reverse=True)
