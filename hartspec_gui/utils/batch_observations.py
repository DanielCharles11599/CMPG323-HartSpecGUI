# batch_observations.py — FR-21: explicit multi-pair / pointing-scan planning for File_check blocks.
"""Inspect real FITS metadata and split complex blocks into independently reviewed jobs.

Never guess which pointing scan belongs to which full-integration pair.  The
operator maps every pair to a complete scan before the reference template is
pinned.  Each expanded job contains exactly its integration pair and chosen
five-direction pointing scan plus reference; existing single-pair scientific
adapters then process the jobs independently, in File_check order.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping

from utils import batch_queue

ROLES = frozenset({"N", "S", "E", "W", "Centre"})


def _signature(data: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


def _read_observation_header(path: str) -> SimpleNamespace:
    """Read only SPPOINT/POSITION cards; never allocate the entire FITS spectrum.

    Real science still goes through the existing ingest_fits_file() worker.
    This is a read-only classification pass for large campaign observations.
    """
    try:
        from astropy.io import fits
        with fits.open(path, mode="readonly", memmap=False, lazy_load_hdus=True) as hdu_list:
            if len(hdu_list) < 3:
                raise ValueError("Expected primary, beam and spectrum HDUs")
            header = {"pointing": hdu_list[0].header.get("SPPOINT"),
                      "position": hdu_list[2].header.get("POSITION")}
        return SimpleNamespace(ok=True, spectrum=header, load_errors={})
    except (OSError, ValueError, KeyError, IndexError) as exc:
        return SimpleNamespace(ok=False, spectrum=None, load_errors={"header": str(exc)})


def inspect_observation_job(
    job: Mapping[str, Any], *,
    ingest: Callable[[str], Any] | None = None,
    get_pairs: Callable[[list[dict[str, Any]]], Any] | None = None,
    suggest_mode: Callable[[Any], Any] | None = None,
    find_scans: Callable[[Mapping[str, list[str]], Callable[..., Any]], Any] | None = None,
) -> dict[str, Any]:
    """Inspect a pending block; report all pairs and complete scans without guessing associations.

    Optional function arguments are test seams for synthetic/in-memory spectra.
    Real calls use the same FITS, bandpass and pointing helpers as the worker.
    """
    if job.get("status") != "pending" or job.get("pair_assignment"):
        raise batch_queue.BatchQueueError("Only an unsplit, pending observation block can be inspected.")
    errors = batch_queue.revalidate_job_inputs(job)
    if errors:
        raise batch_queue.BatchQueueError("Source FITS changed: " + "; ".join(errors))
    if ingest is None or get_pairs is None or suggest_mode is None or find_scans is None:
        from utils import bandpass_correction_logic as bp, pointing_logic as point
        ingest = ingest or _read_observation_header
        get_pairs = get_pairs or bp.get_full_integration_pairs
        suggest_mode = suggest_mode or bp.suggest_mode
        find_scans = find_scans or point.find_pointing_scans

    entries: list[dict[str, Any]] = []
    loaded: dict[str, Mapping[str, Any]] = {}
    for item in job["inputs"]:
        result = ingest(item["path"])
        spectrum = getattr(result, "spectrum", None)
        if not getattr(result, "ok", False) or not isinstance(spectrum, Mapping):
            raise batch_queue.BatchQueueError(
                f"{item['filename']}: cannot inspect FITS: {str(getattr(result, 'load_errors', ''))[:400]}"
            )
        try:
            value = float(spectrum.get("pointing"))
        except (ValueError, TypeError):
            value = float("nan")
        if value not in (0.0, 1.0):
            raise batch_queue.BatchQueueError(
                f"{item['filename']}: SPPOINT must be 0 or 1; cannot safely assign integrations or scans."
            )
        filename = item["filename"]
        if filename in loaded:
            raise batch_queue.BatchQueueError("Repeated FITS filename in a candidate observation block.")
        loaded[filename] = spectrum
        entries.append({"filename": filename, "spectrum": spectrum, "pointing": int(value),
                        "position": str(spectrum.get("position", "")).strip().upper(),
                        "observation_dir": job["block_name"]})

    full = [entry["filename"] for entry in entries if entry["pointing"] == 0]
    pairs = list(get_pairs(entries))
    paired = [entry["filename"] for pair in pairs for entry in pair]
    if not full or len(full) % 2 or Counter(full) != Counter(paired):
        raise batch_queue.BatchQueueError(
            "All SPPOINT=0 integrations must belong to unambiguous, non-overlapping pairs. "
            f"Found {len(full)} integrations but {len(pairs)} complete pair(s)."
        )
    pair_rows = []
    for number, pair in enumerate(pairs, start=1):
        filenames = [entry["filename"] for entry in pair]
        if len(set(filenames)) != 2:
            raise batch_queue.BatchQueueError("A bandpass pair contains a repeated integration filename.")
        mode, explanation = suggest_mode(pair)
        if mode not in {"Frequency Switch", "Position Switch"}:
            raise batch_queue.BatchQueueError(
                f"Cannot determine bandpass mode for integration pair {number}: {explanation}"
            )
        pair_rows.append({"number": number, "files": filenames, "mode": mode, "reason": str(explanation)})

    scans = list(find_scans({job["block_name"]: [e["filename"] for e in entries]}, loaded.get))
    scan_rows = []
    covered_pointing = set()
    for scan in scans:
        files = dict(scan.files)
        names = list(files.values())
        reference = scan.reference
        if (set(files) != ROLES or len(set(names)) != len(ROLES) or not reference or reference in names
                or any(name not in loaded for name in names + [reference])):
            raise batch_queue.BatchQueueError(
                f"Scan {scan.key} is missing a direction, has duplicate inputs or lacks a valid reference."
            )
        if scan.reference_position not in {"ON", "OFF"}:
            raise batch_queue.BatchQueueError(f"Scan {scan.key} has unknown reference POSITION metadata.")
        # Each scan reference is an SPPOINT=1 file, never one of the full integrations.
        if any(float(loaded[name]["pointing"]) != 1 for name in names + [reference]):
            raise batch_queue.BatchQueueError(f"Scan {scan.key} includes a non-pointing integration.")
        covered_pointing.update(names + [reference])
        scan_rows.append({"key": scan.key, "files": files, "reference": reference,
                          "reference_position": scan.reference_position})
    all_pointing = {entry["filename"] for entry in entries if entry["pointing"] == 1}
    unused_pointing = sorted(all_pointing - covered_pointing)
    if unused_pointing:
        raise batch_queue.BatchQueueError(
            "Incomplete or unclassified pointing inputs cannot be silently omitted: "
            + ", ".join(unused_pointing)
        )
    if not scan_rows:
        raise batch_queue.BatchQueueError("No complete pointing scan with matching reference was found.")

    snapshot = {"job_id": job["job_id"], "block_name": job["block_name"],
                "inputs": [{"name": row["filename"], "identity": row["identity"]} for row in job["inputs"]],
                "pairs": pair_rows, "scans": scan_rows}
    return {"job_id": job["job_id"], "block_name": job["block_name"],
            "pairs": pair_rows, "scans": scan_rows, "signature": _signature(snapshot)}


def split_observation_job(
    sessions_root: str | Path, batch_id: str, job_id: str, *, expected_revision: int,
    inspection_signature: str, assignments: Mapping[str, str], operator: str, note: str,
    acknowledge_shared: bool = False, acknowledge_unused: bool = False,
    inspect: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Atomically replace one unsplit block by one queue job for every integration pair.

    Every pair must have an explicit pointing-scan assignment. Shared or unused
    scans require acknowledgement and a persisted operator justification.
    Uses the queue revision lock and re-inspects FITS before committing.
    """
    if not isinstance(operator, str) or not operator.strip() or not isinstance(note, str) or not note.strip():
        raise batch_queue.BatchQueueError("A named operator and scientific assignment note are required.")
    if not isinstance(assignments, Mapping):
        raise batch_queue.BatchQueueError("Pointing scan assignments must map every integration pair.")
    inspector = inspect or inspect_observation_job

    def apply(document: dict[str, Any]) -> None:
        if document["processing_enabled"] or any(
            job["status"] not in {"pending", "invalid"} for job in document["jobs"]
        ):
            raise batch_queue.BatchQueueError("Expand observation blocks before pinning a template or running jobs.")
        original = batch_queue._job(document, job_id)
        result = inspector(original)
        if result["signature"] != inspection_signature:
            raise batch_queue.BatchConflict("FITS/header inspection changed. Inspect the observation again.")
        pairs, scans = result["pairs"], {row["key"]: row for row in result["scans"]}
        if len(pairs) < 2 and len(scans) < 2:
            raise batch_queue.BatchQueueError("This block already has one pair and one scan; splitting is unnecessary.")
        expected = {str(row["number"]) for row in pairs}
        if set(assignments) != expected or any(key not in scans for key in assignments.values()):
            raise batch_queue.BatchQueueError("Every integration pair needs one explicit, known pointing scan.")
        modes = {row["mode"] for row in pairs}
        if len(modes) != 1:
            raise batch_queue.BatchQueueError(
                "A reference session has one bandpass mode; separate mixed-mode pairs into different queues."
            )
        expected_position = "ON" if next(iter(modes)) == "Frequency Switch" else "OFF"
        if any(scans[key]["reference_position"] != expected_position for key in assignments.values()):
            raise batch_queue.BatchQueueError("A selected pointing reference is incompatible with the pair mode.")
        duplicate_scans = [name for name, count in Counter(assignments.values()).items() if count > 1]
        unused_scans = set(scans) - set(assignments.values())
        if duplicate_scans and not acknowledge_shared:
            raise batch_queue.BatchQueueError("Reusing a pointing scan requires explicit acknowledgement.")
        if unused_scans and not acknowledge_unused:
            raise batch_queue.BatchQueueError("Unused complete pointing scans require explicit acknowledgement.")
        from copy import deepcopy
        from uuid import uuid4
        new_jobs = []
        for pair in pairs:
            chosen = scans[assignments[str(pair["number"])]]
            chosen_names = set(pair["files"]) | set(chosen["files"].values()) | {chosen["reference"]}
            source_names = {row["filename"] for row in original["inputs"]}
            if not chosen_names <= source_names:
                raise batch_queue.BatchQueueError("An assigned scan references a FITS file outside the source block.")
            new = deepcopy(original)
            new["job_id"] = uuid4().hex
            new["inputs"] = [item for item in original["inputs"] if item["filename"] in chosen_names]
            new["pair_assignment"] = {
                "source_job_id": job_id, "pair_number": pair["number"], "pair_total": len(pairs),
                "pair_files": list(pair["files"]), "scan_key": chosen["key"],
                "scan_files": dict(chosen["files"]), "scan_reference": chosen["reference"],
                "mode": pair["mode"], "operator": operator.strip(), "note": note.strip(),
                "shared_scan": bool(duplicate_scans), "unused_scans": sorted(unused_scans),
            }
            new_jobs.append(new)
        index = document["jobs"].index(original)
        document["jobs"][index:index + 1] = new_jobs
        document["audit_log"].append({
            "at": batch_queue._now(), "action": "block_split", "job_id": job_id,
            "detail": f"{operator.strip()} split {original['block_name']} into {len(pairs)} ordered pairs; "
            f"assignments={dict(assignments)}; shared={duplicate_scans}; unused={sorted(unused_scans)}; "
            f"note={note.strip()}",
        })

    return batch_queue._update(sessions_root, batch_id, expected_revision, apply)


def job_label(job: Mapping[str, Any]) -> str:
    """Human-readable output identity; distinguish several pairs within one File_check block."""
    assignment = job.get("pair_assignment") or {}
    if not assignment:
        return str(job["block_name"])
    return (f"{job['block_name']} · pair {assignment['pair_number']}/{assignment['pair_total']} "
            f"· {assignment['scan_key']}")
