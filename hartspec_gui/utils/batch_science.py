# batch_science.py — FR-21: per-observation scientific adapters with explicit human review barriers.
"""Run one validated File_check block through the GUI's existing science helpers.

This module never imports a Streamlit page, never reads st.session_state and
never mutates clc/. Each new observation is loaded afresh; an operator's saved
settings, never its earlier calculated spectra, are reused.

Complex File_check blocks can be split into independently reviewed pair
jobs by batch_observations, after an operator assigns a complete scan to
each pair. Unassigned/ambiguous science still stops rather than guessing.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from utils import batch_queue, batch_template

StageCallback = Callable[[str], None]
_STAGE_SOURCE = "01_source_browser"
_STAGE_INGEST = "02_file_loader"
_STAGE_BANDPASS = "03_bandpass_correction"
_STAGE_BASELINE = "04_baseline_editor"
_STAGE_CALIBRATION = "05_calibration_dashboard"
_STAGE_POINTING = "06_pointing_correction"
_STAGE_FITTING = "07_spectral_fitting"
_STAGE_EXPORT = "08_export_and_session"
_OUTPUT_NAMES = ("spectrum.csv", "spectrum.fits", "graphs.pdf", "session.json")


@dataclass(frozen=True)
class ScienceOutcome:
    """Worker outcome; completion is still checked against the manifest's gates."""

    status: str
    stage: str
    reason: str = ""
    signature: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    approvable: bool = True
    automatic_pointing_pass: str | None = None
    session_id: str | None = None
    output_files: tuple[str, ...] = ()


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def job_directory(sessions_root: str | Path, batch_id: str, job_id: str) -> Path:
    """Derive a fixed output directory solely from validated generated IDs."""
    batch_queue._id(batch_id)
    batch_queue._id(job_id)
    return Path(sessions_root).expanduser().resolve() / "batches" / batch_id / "jobs" / job_id


def _write_atomic(path: Path, data: bytes) -> None:
    """Replace an output only after bytes have been fsync'd in the job directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".hartspec-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _fingerprint(*parts: Any) -> str:
    """Hash exact input/setting identity plus a stable numerical review result."""
    document = json.dumps(parts, sort_keys=True, allow_nan=False, default=str).encode("utf-8")
    return hashlib.sha256(document).hexdigest()


def _spectrum_digest(spec: Mapping[str, Any]) -> str:
    result = hashlib.sha256()
    for label in ("Vlsr", "LCP", "RCP"):
        values = np.asarray(spec[label], dtype="<f8")
        if values.ndim != 1 or not values.size or not np.isfinite(values).all():
            raise ValueError(f"{label} must contain finite, one-dimensional channels.")
        result.update(label.encode("ascii"))
        result.update(values.tobytes())
    return result.hexdigest()


def _save_review(sessions_root: str | Path, batch_id: str, job_id: str,
                 content: Mapping[str, Any]) -> None:
    """Persist bounded, display-only data separately from the queue manifest."""
    raw = json.dumps(content, sort_keys=True, allow_nan=False).encode("utf-8")
    if len(raw) > 1_500_000:
        raise ValueError("Scientific review preview exceeds its 1.5 MB limit.")
    _write_atomic(job_directory(sessions_root, batch_id, job_id) / "review.json", raw)


def load_review(sessions_root: str | Path, batch_id: str, job_id: str,
                signature: str) -> dict[str, Any] | None:
    """Return only review arrays that match the *current* held result signature."""
    path = job_directory(sessions_root, batch_id, job_id) / "review.json"
    try:
        if path.stat().st_size > 1_500_000:
            return None
        result = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(result, dict) and result.get("signature") == signature:
            return result
    except (OSError, ValueError):
        return None
    return None


def _sample(spec: Mapping[str, Any], *, limit: int = 1536) -> dict[str, list[float]]:
    """Downsample for *review display only*, never scientific calculations."""
    size = len(spec["Vlsr"])
    indices = np.linspace(0, size - 1, min(size, limit), dtype=int)
    return {key: np.asarray(spec[key], dtype=float)[indices].tolist() for key in ("Vlsr", "LCP", "RCP")}


def _held(stage: str, reason: str, *, signature: str | None = None,
          details: Mapping[str, Any] | None = None, approvable: bool = False) -> ScienceOutcome:
    """Create a review barrier. Missing science is NOT an approvable override."""
    return ScienceOutcome("needs_review", stage, reason, signature, dict(details or {}), approvable)


def _pipeline_input(job: Mapping[str, Any], batch: Mapping[str, Any]) -> dict[str, Any]:
    """Keep archive-relative paths so FR-19 replay also finds nested FITS directories."""
    archive = Path(job["archive_root"]).resolve()
    relative_names = [Path(entry["path"]).resolve().relative_to(archive).as_posix() for entry in job["inputs"]]
    return {
        "selected_files": relative_names,
        "fits_file_paths": [entry["path"] for entry in job["inputs"]],
        "archive_root": job.get("archive_root", str(Path(job["inputs"][0]["path"]).parent)),
        "observation_blocks": {job["block_name"]: [entry["filename"] for entry in job["inputs"]]},
        "source_name": batch["source_name"], "frequency_mhz": batch["frequency_mhz"],
        "source_session_id": batch["source_session_id"], "batch_queue_id": batch["batch_id"],
    }


def replay_paths_match(job: Mapping[str, Any], current_archive_root: str | Path) -> bool:
    """Verify that Page 02's configured FITS root will reopen the exact batch inputs.

    FR-19's replay is parameter restoration followed by a fresh FITS load;
    it must not quietly load files of the same names from another archive.
    """
    try:
        source_root = Path(job["archive_root"]).resolve()
        target_root = Path(current_archive_root).expanduser().resolve()
        for item in job["inputs"]:
            relative = Path(item["path"]).resolve().relative_to(source_root)
            if (target_root / relative).resolve() != Path(item["path"]).resolve():
                return False
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return True


def _ensure_input_integrity(job: Mapping[str, Any], verify: Callable[[Path], Any]) -> None:
    problems = batch_queue.revalidate_job_inputs(job)
    for item in job["inputs"]:
        result = verify(Path(item["path"]))
        if not getattr(result, "ok", False):
            problems.extend(f"{item['filename']}: {issue}" for issue in (getattr(result, "issues", []) or [
                "FITS structural validation failed"
            ]))
    if problems:
        raise ValueError("FITS inputs cannot be processed: " + "; ".join(problems))


def run_science(
    job: Mapping[str, Any], batch: Mapping[str, Any], sessions_root: str | Path,
    *, on_stage: StageCallback | None = None,
) -> ScienceOutcome:
    """Compute one block, holding for per-block baseline and pointing review.

    During a review pause all steps are rerun on resume. The approval is
    honoured *only* if the freshly calculated fingerprint matches exactly.
    This avoids storing gigabytes of mutable transient arrays in a session.
    """
    # Scientific imports remain lazy so queue/template tests run headlessly.
    from utils import (bandpass_correction_logic as bp, baseline_polynomial_adapter as baseline,
                       calibration_logic as cal, export_logic as export, fits_ingest, fitting_inputs,
                       pointing_logic as point, spectral_fitting_logic as fitting)

    if not batch.get("processing_enabled") or not isinstance(batch.get("template"), Mapping):
        raise ValueError("A validated reference-session template must be pinned before processing.")
    template = batch["template"]
    if batch.get("template_signature") != batch_template.signature(template):
        raise ValueError("Reference-session settings changed after the batch was activated.")
    settings = template["settings"]
    session_id = f"batch_{job['job_id'][:16]}"
    events: list[dict[str, str]] = []
    pipeline: dict[str, Any] = {_STAGE_SOURCE: _pipeline_input(job, batch)}

    def record(stage: str, description: str) -> None:
        events.append({"ts": _utc(), "message": f"{stage} — {description}"})
        if on_stage is not None:
            on_stage(stage)

    record(_STAGE_SOURCE, f"Processing {job['block_name']} with {len(job['inputs'])} input files")
    _ensure_input_integrity(job, fits_ingest.verify_fits_file)
    loaded: dict[str, dict[str, Any]] = {}
    entries: list[dict[str, Any]] = []
    conventions: dict[str, str] = {}
    for item in job["inputs"]:
        ingested = fits_ingest.ingest_fits_file(item["path"])
        if not ingested.ok or not isinstance(ingested.spectrum, Mapping):
            raise ValueError(f"{item['filename']}: FITS ingest failed: {ingested.load_errors}")
        spec = ingested.spectrum
        loaded[item["filename"]] = spec
        conventions[item["filename"]] = ingested.convention
        raw_pointing = spec.get("pointing")
        try:
            pointing = int(raw_pointing)
            if float(raw_pointing) != pointing:
                pointing = None
        except (TypeError, ValueError):
            pointing = None
        entries.append({"filename": item["filename"], "spectrum": spec,
                        "pointing": pointing, "position": str(spec.get("position", "")).strip().upper(),
                        "observation_dir": job["block_name"]})
    pipeline["file_loader"] = {"complete": True, "eligible_files": list(loaded), "conventions": conventions}
    record(_STAGE_INGEST, f"Verified and loaded {len(loaded)} FITS files")

    full = [entry for entry in entries if entry["pointing"] == 0]
    if any(entry["pointing"] is None for entry in entries):
        return _held(_STAGE_BANDPASS, "SPPOINT is unknown for one or more FITS files; choose the pair manually.")
    if len(full) != 2:
        return _held(_STAGE_BANDPASS, f"Expected one on-source pair, found {len(full)} full integrations. "
                     "This block needs explicit pair selection; no files were silently skipped.")
    pairs = bp.get_full_integration_pairs(entries)
    if len(pairs) != 1:
        return _held(_STAGE_BANDPASS, "Could not establish one safe full-integration pair.")
    pair = pairs[0]
    assignment = job.get("pair_assignment")
    if assignment is not None:
        actual_pair = {entry["filename"] for entry in pair}
        if actual_pair != set(assignment["pair_files"]):
            raise ValueError("The selected bandpass pair no longer matches the explicit operator assignment.")
    suggestion, explanation = bp.suggest_mode(pair)
    mode = settings["bandpass_mode"]
    if suggestion is None or suggestion != mode or (assignment and assignment["mode"] != mode):
        return _held(_STAGE_BANDPASS, f"Pair suggests {suggestion!r} ({explanation}), "
                     f"but reference template specifies {mode}. Review the observation.")
    bandpass = bp.build_bandpass_result(mode, pair)
    corrected = bandpass["corrected"]
    pipeline[_STAGE_BANDPASS] = {"mode": mode, "filename1": pair[0]["filename"],
                                 "filename2": pair[1]["filename"],
                                 "common_velocity_range_kms": bandpass["common_velocity_range_kms"]}
    record(_STAGE_BANDPASS, f"{mode}; {pair[0]['filename']} / {pair[1]['filename']}")

    blocks = settings["baseline_blocks"]
    comparison = baseline.fit_polynomial_comparison(corrected, blocks)
    orders = settings["polynomial_orders"]
    flattened = baseline.flatten_spectrum_for_orders(corrected, comparison, orders)
    chi = {pol: {str(panel["order"]): float(panel["chi_squared"]) for panel in comparison["panels"]
                 if panel["polarization"] == pol} for pol in ("LCP", "RCP")}
    if any(not np.isfinite(score) for values in chi.values() for score in values.values()):
        raise ValueError("Non-finite chi-squared value in the polynomial baseline comparison.")
    baseline_signature = _fingerprint(
        batch["template_signature"], job["block_name"], [entry["identity"] for entry in job["inputs"]],
        _spectrum_digest(corrected), _spectrum_digest(flattened), chi,
    )
    pipeline[_STAGE_BASELINE] = {
        "blocks": list(blocks), "selected_orders": dict(orders),
        "fit_provider": "clc", "complete": True, "chi_squared": chi,
        "review_signature": baseline_signature,
        "review_evidence": (
            job["gates"][_STAGE_BASELINE].get("evidence")
            if job["gates"][_STAGE_BASELINE].get("state") == "approved" else None
        ),
    }
    record(_STAGE_BASELINE, f"Applied orders {orders} to {len(blocks)} emission-free regions")
    baseline_gate = job["gates"][_STAGE_BASELINE]
    if baseline_gate.get("state") != "approved" or baseline_gate.get("signature") != baseline_signature:
        _save_review(sessions_root, batch["batch_id"], job["job_id"], {
            "type": "baseline", "signature": baseline_signature, "block": job["block_name"],
            "corrected": _sample(corrected), "flattened": _sample(flattened), "blocks": blocks,
            "orders": orders, "chi_squared": chi,
        })
        return _held(
            _STAGE_BASELINE, "Check that the saved emission-free windows and polynomial orders remain "
            "scientifically appropriate for this observation before its calibration proceeds.",
            signature=baseline_signature, details={"orders": orders, "chi_squared": chi}, approvable=True,
        )

    # Page 05 obtains atmospheric/PSS metadata from the exact first member of
    # the Page 03 pair; no cached values from the reference spectrum are used.
    first_spec = pair[0]["spectrum"]
    atmosphere = cal.get_atmospheric_calibration(first_spec)
    history = cal.get_pss_history(first_spec["restfreq"])
    window = cal.get_pss_window(first_spec["date"])
    means = cal.get_pss_window_averages(history, window)
    if means.get("lcp") is None or means.get("rcp") is None:
        raise ValueError("No LCP/RCP PSS calibrations are available for this observation's 15-day window.")
    calibrated = cal.apply_calibration_to_spectrum(
        flattened, atmosphere["atcor"], means["lcp"], means["rcp"],
        atmosphere["nd_lcp"], atmosphere["nd_rcp"],
    )
    pipeline[_STAGE_CALIBRATION] = {
        "complete": True,
        "atmospheric": {
            key: atmosphere[key]
            for key in ("frequency", "pwv", "elevation", "azimuth", "atcor", "optical_depth")
        },
        "pss": {"frequency": history["frequency"], "window_days": int(window["days"]),
                "observation_mjd": float(window["observation_mjd"]),
                "lcp_window_mean": float(means["lcp"]), "rcp_window_mean": float(means["rcp"])},
    }
    record(_STAGE_CALIBRATION, f"Computed PWV/ATcor and per-observation PSS (LCP {means['lcp']}, "
                               f"RCP {means['rcp']})")

    scans = point.find_pointing_scans(
        {job["block_name"]: [entry["filename"] for entry in job["inputs"]]}, loaded.get,
    )
    if len(scans) != 1 or scans[0].reference is None:
        return _held(
            _STAGE_POINTING,
            "One complete N/S/E/W/Centre pointing scan plus the matching reference is required; "
            f"found {len(scans)} possible scan(s). No previous pointing factor will be reused.",
        )
    scan = scans[0]
    if assignment is not None and (scan.reference != assignment["scan_reference"]
                                   or dict(scan.files) != assignment["scan_files"]):
        raise ValueError("Pointing scan no longer matches the explicit operator assignment.")
    if scan.reference_position != point.REFERENCE_POSITION[mode]:
        return _held(_STAGE_POINTING, "Pointing reference does not match the selected bandpass mode.")
    by_name = {entry["filename"]: entry["path"] for entry in job["inputs"]}
    if scan.reference not in by_name or any(filename not in by_name for filename in scan.files.values()):
        return _held(_STAGE_POINTING, "Pointing input paths are incomplete in this block.")
    vlsr = np.asarray(corrected["Vlsr"], dtype=float)
    peak_setting = settings["pointing_peak_velocity_kms"]
    if peak_setting is None:
        chosen_peak = float(vlsr[point.default_peak_index(vlsr, corrected["LCP"], corrected["RCP"])])
    else:
        chosen_peak = float(vlsr[point.nearest_channel(vlsr, peak_setting)])
    half_width = int(settings["pointing_half_width_channels"])
    processed = point.compute_pointing_from_scan(
        scan_paths={role: by_name[name] for role, name in scan.files.items()},
        reference_path=by_name[scan.reference], mode=mode, blocks=blocks, baseline_vlsr=vlsr,
        peak_vel=chosen_peak, half_width=half_width, dirname=job["block_name"].removesuffix(".txt"),
        plot_dir=None,
    )
    result = processed.result
    check = point.evaluate_pointing_check(result, processed.snr, snr_required=True)
    pointing_details = {
        "verdict": check.verdict, "overridable": bool(check.overridable),
        "reasons": list(check.reasons), "correction_factor": float(result.correction_factor),
        "ns_offset_deg": float(result.ns_offset_deg), "ew_offset_deg": float(result.ew_offset_deg),
        "peak_velocity_kms": chosen_peak, "half_width_channels": half_width,
    }
    pointing_signature = _fingerprint(
        baseline_signature, pointing_details, scan.files, scan.reference,
        [round(float(result.ns_offset_deg), 9), round(float(result.ew_offset_deg), 9)],
    )
    gate = job["gates"][_STAGE_POINTING]
    approved = gate.get("state") == "approved" and gate.get("signature") == pointing_signature
    if check.verdict != point.VERDICT_GO and not approved:
        _save_review(sessions_root, batch["batch_id"], job["job_id"], {
            "type": "pointing", "signature": pointing_signature, "block": job["block_name"],
            "details": pointing_details,
            "scans": {role: {"Vlsr": np.asarray(s["Vlsr"])[::max(1, len(s["Vlsr"]) // 1536)].tolist(),
                             "average": np.asarray(s["ave_pol"])[::max(1, len(s["Vlsr"]) // 1536)].tolist()}
                      for role, s in processed.spectra.items()},
        })
        return _held(
            _STAGE_POINTING, "Pointing No-Go; review the five-scans quality check and provide a "
            "scientific justification for any override: " + "; ".join(check.reasons),
            signature=pointing_signature, details=pointing_details,
            approvable=bool(check.overridable and check.evaluated),
        )
    pipeline[_STAGE_POINTING] = {
        "input_source": "pointing scan (Cal_point_check)",
        "scan_key": assignment["scan_key"] if assignment else scan.key,
        "scan_files": dict(scan.files), "peak_velocity_kms": chosen_peak,
        "half_width_channels": half_width, "correction_factor": float(result.correction_factor),
        "ns_offset_deg": float(result.ns_offset_deg), "ew_offset_deg": float(result.ew_offset_deg),
        "pointing_check": point.check_record(
            check, result, signature=pointing_signature, accepted=True,
            override_note=(job["review"].get("note", "") if approved else ""),
            override_justification=(job["review"].get("justification", "") if approved else ""),
        ),
    }
    record(_STAGE_POINTING, f"{check.verdict}; correction factor {result.correction_factor}")
    automatic_pass = None if approved else (
        f"{check.verdict}, NS significance {check.ns_ratio}; Sig_point evaluated={processed.snr.evaluated}"
    )

    graph3 = np.asarray(calibrated["LCP"], dtype=float) + np.asarray(calibrated["RCP"], dtype=float)
    graph3 = graph3 + float(result.correction_factor)  # Page 07's calibrated-input formula
    fitted = fitting.run_fit(settings["fit_type"], vlsr, graph3, fitting_inputs.GRAPH3_UNIT)
    if not fitted.ok or fitted.fell_back:
        raise ValueError("Spectral fitting did not converge to the requested template model: " +
                         "; ".join(fitted.notes))
    pss = fitting_inputs.PssValue(
        (float(means["lcp"]) + float(means["rcp"])) / 2.0, float(means["lcp"]),
        float(means["rcp"]), str(history["frequency"]), int(window["days"]),
    )
    fit_summary = {
        "fit_type": fitted.fit_type_used, "fit_type_requested": settings["fit_type"],
        "parameters": [{"parameter": name, "value": value, "error": error}
                       for name, value, error in fitted.rows],
        "converged": bool(fitted.converged), "notes": list(fitted.notes),
        "pss_jy_per_k": pss.value, "pointing_correction_factor": float(result.correction_factor),
        "n_channels": int(vlsr.size), "intensity_unit": fitting_inputs.GRAPH3_UNIT,
    }
    pipeline[_STAGE_FITTING] = fit_summary
    record(_STAGE_FITTING, f"Computed {fitted.fit_type_used} Graph 3 fit")

    averaged, _ = fitting_inputs.pair_average(calibrated["LCP"], calibrated["RCP"])
    metadata = export.build_metadata(
        spectrum=first_spec, spectrum_source="batch_calibrated", intensity_unit="Jy",
        pss=pss, pointing_factor=float(result.correction_factor), fit_summary=fit_summary,
    )
    export_args = dict(
        vlsr=vlsr, lcp=calibrated["LCP"], rcp=calibrated["RCP"], average=averaged,
        unit="Jy", calibrated=graph3, fit_curve=fitted.curve, metadata=metadata,
    )
    csv_bytes = export.build_export_csv(**export_args)
    traceability, notes = export.build_fits_traceability(session_id, pipeline)
    fits_bytes = export.build_export_fits(**export_args, traceability=traceability, trace_notes=notes)
    charts = [
        export.GraphSpec("Calibrated LCP/RCP", "Jy", [
            export.GraphTrace("LCP", vlsr, calibrated["LCP"], "#1F77B4"),
            export.GraphTrace("RCP", vlsr, calibrated["RCP"], "#FF7F0E"),
        ]),
        export.GraphSpec("Graph 3 and fit", fitting_inputs.GRAPH3_UNIT, [
            export.GraphTrace("Graph 3", vlsr, graph3, "#1F77B4"),
            export.GraphTrace("Fit", vlsr, fitted.curve, "#DC2626", dashed=True),
        ]),
    ]
    pdf_bytes = export.build_graphs_pdf(charts, title=f"HARTSPEC {batch['source_name']} — {job['block_name']}")
    pipeline[_STAGE_EXPORT] = {
        "complete": True, "formats": ["CSV", "FITS", "PDF"],
        "source": job["block_name"], "session_id": session_id,
    }
    record(_STAGE_EXPORT, "Finished CSV/FITS/PDF export")
    session = {
        "session_id": session_id, "pipeline_data": pipeline,
        "completed_stages": ["01_source_browser", "file_loader", _STAGE_BANDPASS, _STAGE_BASELINE,
                             _STAGE_CALIBRATION, _STAGE_POINTING, _STAGE_FITTING, _STAGE_EXPORT],
        "audit_log": events, "stages": {}, "batch_id": batch["batch_id"],
        "reference_session_id": template["session_id"],
        "reference_session_sha256": template["source_sha256"], "generated_at": _utc(),
        "pair_assignment": assignment,
    }
    records = {
        "spectrum.csv": csv_bytes, "spectrum.fits": fits_bytes, "graphs.pdf": pdf_bytes,
        "session.json": json.dumps(session, sort_keys=True, indent=2, allow_nan=False).encode("utf-8"),
    }
    folder = job_directory(sessions_root, batch["batch_id"], job["job_id"])
    for name, data in records.items():
        _write_atomic(folder / name, data)
    return ScienceOutcome("completed", _STAGE_EXPORT, automatic_pointing_pass=automatic_pass,
                          session_id=session_id, output_files=_OUTPUT_NAMES)
