# file_loader_logic.py — FR-02/03: validated spectrum handoff and dependent-state safety.
"""One eligibility rule for the File Loader and Bandpass Correction pages.

CLC ingestion and FITS structural verification are independent checks. Both
must succeed before a spectrum can enter the processing handoff. Flagging is
not quarantining: this module never moves files or triggers validation itself.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

from utils.stage_invalidation import LOADED_INPUT_DEPENDENT_STAGE_KEYS, invalidate_loaded_input_dependents

LOADER_STAGE_KEY = "file_loader"
_SIGNATURE_KEY = "file_loader_validated_input_signature"


def eligible_loaded_entries(state: Mapping[str, Any], filenames: Sequence[str]) -> list[dict[str, Any]]:
    """Return only loaded, verified, non-quarantined spectra in input order.

    Args:
        state: Active reduction mapping, with the existing per-file caches.
        filenames: The current Page 1 handoff (or Page 2 developer override).

    Returns:
        Filename/spectrum pairs. Spectrum objects are referenced, not copied
        or numerically altered. Missing verification fails closed even when
        ingestion succeeded; a checksum keyword is not required to pass.
    """
    quarantined = state.get("file_loader_quarantined", set())
    entries = []
    for filename in filenames:
        if filename in quarantined:
            continue
        ingest = state.get(f"file_loader_ingest_result::{filename}")
        verify = state.get(f"file_loader_verify_result::{filename}")
        spectrum = getattr(ingest, "spectrum", None)
        if (
            getattr(ingest, "ok", False) and getattr(verify, "ok", False)
            and isinstance(spectrum, Mapping) and all(key in spectrum for key in ("Vlsr", "LCP", "RCP"))
        ):
            entries.append({"filename": filename, "spectrum": spectrum})
    return entries


def restore_saved_quarantine(state: MutableMapping[str, Any]) -> None:
    """Restore recorded exclusions after Load, without moving any files.

    Step 1 deliberately clears runtime quarantine state. New Page 2 summaries
    retain confirmed exclusions in JSON so replay does not try to reload the
    original (now missing) paths. Existing runtime state always takes priority.
    """
    if "file_loader_quarantined" in state:
        return
    pipeline = state.get("pipeline_data", {})
    saved = pipeline.get(LOADER_STAGE_KEY, {}) if isinstance(pipeline, Mapping) else {}
    recorded = saved.get("quarantined_files", []) if isinstance(saved, Mapping) else []
    if isinstance(recorded, list) and all(isinstance(name, str) and name for name in recorded):
        state["file_loader_quarantined"] = set(recorded)


def _input_signature(entries: Sequence[Mapping[str, Any]], archive_root: str | Path) -> str:
    """Identify ordered usable paths without rereading or hashing large FITS files."""
    root = Path(archive_root).expanduser()
    paths = [os.path.normcase(str((root / entry["filename"]).resolve())) for entry in entries]
    return hashlib.sha256(json.dumps(paths, ensure_ascii=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ValidatedHandoff:
    """Summary of one validation-to-processing state transition."""

    eligible_files: tuple[str, ...]
    flagged_files: tuple[str, ...]
    quarantined_files: tuple[str, ...]
    invalidated: bool
    previous_session_id: str


def publish_validated_handoff(
    state: MutableMapping[str, Any], filenames: Sequence[str], archive_root: str | Path, *,
    new_id: Callable[[], str] | None = None,
) -> ValidatedHandoff:
    """Publish validated inputs and invalidate results when eligibility changes.

    Args:
        state: The current reduction mapping; all candidate loads/verification
            checks should already be recorded in its per-file caches.
        filenames: Current target files, preserving the observation order.
        archive_root: The same root used by the actual ingestion wrapper.
        new_id: Optional ID factory for deterministic tests. Normal calls use
            a UUID; a changed input set must not reuse the old bridge ID.

    Returns:
        Counts/filenames for display and whether Pages 3–8 were invalidated.
        Audit messages and navigation remain the calling page's responsibility.

    New saves persist the eligibility signature in pipeline_data. Older saves
    have no such record: retain replay parameters when every selected file
    passes, but invalidate conservatively if any selected input is excluded.
    Previously published legacy runtime arrays must also match by object identity
    (the ingest cache owns them). This protects an already-open pre-patch tab.

    This is input-eligibility tracking, not an in-place archive modification
    detector. A new reduction is still needed after externally editing files.
    """
    entries = eligible_loaded_entries(state, filenames)
    signature = _input_signature(entries, archive_root)
    pipeline = state.get("pipeline_data", {})
    completed = state.get("completed_stages", set())
    if not isinstance(pipeline, dict) or not isinstance(completed, set):
        raise ValueError("The active session has invalid pipeline data or completion flags.")
    saved_loader = pipeline.get(LOADER_STAGE_KEY, {})
    if not isinstance(saved_loader, Mapping):
        saved_loader = {}
    previous_signature = state.get(_SIGNATURE_KEY) or saved_loader.get("validated_input_signature")
    previous_id = str(state.get("session_id", ""))
    if previous_signature is not None:
        changed = previous_signature != signature
    else:
        # A new Page 1 selection has neither runtime arrays nor derived stages;
        # it does not need a second ID change just because validation ran.
        has_derived = any(stage in completed or stage in pipeline for stage in LOADED_INPUT_DEPENDENT_STAGE_KEYS)
        has_derived = has_derived or any(
            state.get(key) is not None for key in (
                "bandpass_corrected_spectrum", "bandpass_display_result", "baseline_corrected_spectrum",
                "calibrated_spectrum", "latest_fit",
            )
        )
        prior_spectra = state.get("loaded_spectra")
        if prior_spectra is not None:
            changed = bool(prior_spectra or has_derived) and (
                len(prior_spectra) != len(entries)
                or any(old is not entry["spectrum"] for old, entry in zip(prior_spectra, entries))
            )
        else:
            changed = has_derived and len(entries) != len(filenames)

    quarantined = state.get("file_loader_quarantined", set())
    eligible_names = tuple(entry["filename"] for entry in entries)
    eligible_set = set(eligible_names)
    quarantined_names = tuple(name for name in filenames if name in quarantined)
    flagged_names = tuple(name for name in filenames if name not in quarantined and name not in eligible_set)
    summary = dict(saved_loader)
    summary.update({
        "validation_policy": "ingest_and_structural_verification_v1",
        "selected_files": list(filenames),
        "eligible_files": list(eligible_names),
        "flagged_files": list(flagged_names),
        "quarantined_files": list(quarantined_names),
        "validated_input_signature": signature,
    })
    if changed:
        factory = new_id if new_id is not None else lambda: uuid.uuid4().hex
        invalidate_loaded_input_dependents(state, new_session_id=factory())

    state.setdefault("pipeline_data", {})[LOADER_STAGE_KEY] = summary
    state.setdefault("completed_stages", set())
    state[_SIGNATURE_KEY] = signature
    spectra = [entry["spectrum"] for entry in entries]
    state["loaded_spectra"] = spectra
    if spectra:
        state["loaded_spectrum"] = spectra[0]
    else:
        state.pop("loaded_spectrum", None)
        state["completed_stages"].discard(LOADER_STAGE_KEY)
    state["file_loader_load_done"] = bool(spectra)
    return ValidatedHandoff(eligible_names, flagged_names, quarantined_names, changed, previous_id)
