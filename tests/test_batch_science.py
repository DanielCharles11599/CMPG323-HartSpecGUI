# test_batch_science.py — FR-21: science adapter sequencing/review with in-memory CLC doubles.
"""Checks real adapter wiring and output/audit isolation, not numerical CLC agreement.

The installed test runner lacks astropy, streamlit and the original telescope
calibration environment; scientific helpers are replaced by deterministic
fakes at their documented APIs. Full FITS regression testing is still due.
"""

from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import utils
from utils import batch_queue, batch_science, batch_template


@pytest.fixture
def job_batch(tmp_path):
    fits = tmp_path / "fits"
    fits.mkdir()
    names = ["on_a.fits", "on_b.fits", "n.fits", "s.fits", "e.fits", "w.fits",
             "center.fits", "reference.fits"]
    for filename in names:
        (fits / filename).write_bytes(b"test input " + filename.encode())
    selection = {
        "source_name": "W3(OH)", "frequency_mhz": 6668.5, "archive_root": str(fits),
        "selected_files": names, "fits_file_paths": [str(fits / name) for name in names],
        "observation_blocks": {"20260812_0.txt": names},
    }
    batch = batch_queue.prepare_batch(selection, source_session_id="s0102030")
    batch["template"] = {
        "version": 1, "session_id": "reference", "source_file": "reference.json", "source_sha256": "a" * 64,
        "settings": {"bandpass_mode": "Frequency Switch", "baseline_blocks": [{"start": -4, "end": -3}],
                     "polynomial_orders": {"LCP": 3, "RCP": 4}, "fit_type": "1D Gaussian",
                     "pointing_peak_velocity_kms": None, "pointing_half_width_channels": 4},
    }
    batch["template_signature"] = batch_template.signature(batch["template"])
    batch["processing_enabled"] = True
    return batch["jobs"][0], batch, tmp_path / "sessions"


@pytest.fixture
def scientific_doubles(monkeypatch, job_batch):
    job, batch, root = job_batch
    names = [entry["filename"] for entry in job["inputs"]]
    v = np.arange(-5.0, 6.0)
    source = {
        name: {"Vlsr": v, "LCP": np.linspace(1, 11, 11), "RCP": np.linspace(2, 12, 11),
               "pointing": 0 if name in names[:2] else 1,
               "position": "ON", "restfreq": 66685.0, "date": "2026-08-12T00:00:00",
               "longitude": 20.0, "latitude": -20.0, "Tamb": 20.0, "Humid": 60.0}
        for name in names
    }
    controls = {"verdict": "Go", "scan_available": True, "spectra": source}

    def install(name, **attributes):
        obj = types.ModuleType(f"utils.{name}")
        for key, value in attributes.items():
            setattr(obj, key, value)
        monkeypatch.setitem(sys.modules, f"utils.{name}", obj)
        monkeypatch.setattr(utils, name, obj, raising=False)
        return obj

    def ingest(path):
        name = Path(path).name
        return SimpleNamespace(ok=True, spectrum=controls["spectra"][name], convention="date", load_errors={})

    install("fits_ingest", verify_fits_file=lambda path: SimpleNamespace(ok=True, issues=[]),
            ingest_fits_file=ingest)
    install("bandpass_correction_logic",
            get_full_integration_pairs=lambda entries: [(entries[0], entries[1])],
            suggest_mode=lambda pair: ("Frequency Switch", "second full-integration file is ON"),
            build_bandpass_result=lambda mode, pair: {
                "corrected": pair[0]["spectrum"], "common_velocity_range_kms": [-5.0, 5.0],
            })

    def compare(spec, blocks):
        return {"panels": [
            {"polarization": pol, "order": order, "chi_squared": 0.03 * order}
            for pol in ("LCP", "RCP") for order in (3, 4, 5)
        ]}

    install("baseline_polynomial_adapter", fit_polynomial_comparison=compare,
            flatten_spectrum_for_orders=lambda spec, result, orders: {
                key: np.asarray(spec[key]).copy() for key in ("Vlsr", "LCP", "RCP")
            })
    install("calibration_logic",
            get_atmospheric_calibration=lambda s: {
                "frequency": "66685", "pwv": 1.2, "elevation": 40.0, "azimuth": 8.0,
                "atcor": 1.1, "optical_depth": 0.03, "nd_lcp": 1.0, "nd_rcp": 1.0,
            },
            get_pss_history=lambda freq: {"frequency": "66685"},
            get_pss_window=lambda date: {"days": 15, "observation_mjd": 60000.0},
            get_pss_window_averages=lambda hist, window: {"lcp": 2.0, "rcp": 3.0},
            apply_calibration_to_spectrum=lambda spec, *args: {
                "Vlsr": np.asarray(spec["Vlsr"]).copy(),
                "LCP": np.asarray(spec["LCP"]) * 2.0,
                "RCP": np.asarray(spec["RCP"]) * 3.0,
            })
    result = SimpleNamespace(correction_factor=0.5, ns_offset_deg=0.001, ew_offset_deg=0.002)
    result.uncertainties = SimpleNamespace(ns_sigma_deg=0.001, ew_sigma_deg=0.002, pc_sigma=0.004)
    signal = SimpleNamespace(evaluated=True, passed=True)
    scan = SimpleNamespace(files=dict(zip(("N", "S", "E", "W", "Centre"), names[2:7])),
                           reference=names[7], reference_position="ON", key="scan#1")

    def compute(**kwargs):
        return SimpleNamespace(result=result, snr=signal, spectra={
            role: {"Vlsr": v, "ave_pol": v * index}
            for index, role in enumerate(("N", "S", "E", "W", "Centre"), start=1)
        })

    install(
        "pointing_logic",
        REFERENCE_POSITION={"Frequency Switch": "ON"}, VERDICT_GO="Go",
        find_pointing_scans=lambda blocks, lookup: [scan] if controls["scan_available"] else [],
        default_peak_index=lambda v, lcp, rcp: 5, nearest_channel=lambda v, vel: 5,
        compute_pointing_from_scan=compute,
        evaluate_pointing_check=lambda res, snr, snr_required: SimpleNamespace(
            verdict=controls["verdict"], overridable=True,
            reasons=("offset outside threshold",) if controls["verdict"] != "Go" else (),
            ns_ratio=1.0, evaluated=True,
        ),
        check_record=lambda check, result, **kwargs: {
            "accepted": kwargs["accepted"],
            "verdict": check.verdict,
            "overridden": check.verdict != "Go",
            "override_note": kwargs.get("override_note"),
            "override_justification": kwargs.get("override_justification"),
        },
    )
    install("spectral_fitting_logic", run_fit=lambda fit_type, vlsr, y, unit: SimpleNamespace(
        fit_type_used=fit_type, curve=np.asarray(y) * 0.9, rows=(("Amplitude", "1", "0.1"),),
        converged=True, notes=(), ok=True, fell_back=False,
    ))
    from utils import export_logic
    monkeypatch.setattr(export_logic, "build_export_fits", lambda **kwargs: b"FITS_TABLE_BYTES")
    monkeypatch.setattr(export_logic, "build_graphs_pdf", lambda *args, **kwargs: b"%PDF-1.4 mock")
    return controls


def test_baseline_hold_requires_per_observation_signature_then_exports(job_batch, scientific_doubles):
    job, batch, root = job_batch
    first = batch_science.run_science(job, batch, root)
    assert first.status == "needs_review"
    assert first.stage == "04_baseline_editor" and first.approvable is True
    preview = batch_science.load_review(root, batch["batch_id"], job["job_id"], first.signature)
    assert preview["type"] == "baseline" and len(preview["corrected"]["Vlsr"]) == 11
    assert len(preview["flattened"]["RCP"]) == 11
    assert batch_science.load_review(root, batch["batch_id"], job["job_id"], "f" * 64) is None
    job2 = copy.deepcopy(job)
    job2["gates"]["04_baseline_editor"] = {
        "state": "approved", "signature": first.signature, "evidence": "Astronomer: inspected region"
    }
    result = batch_science.run_science(job2, batch, root)
    assert result.status == "completed" and result.automatic_pointing_pass.startswith("Go")
    files = batch_science.job_directory(root, batch["batch_id"], job["job_id"])
    assert all((files / name).stat().st_size > 0 for name in result.output_files)
    saved = json.loads((files / "session.json").read_text())
    assert saved["pipeline_data"]["05_calibration_dashboard"]["pss"]["lcp_window_mean"] == 2.0
    assert saved["pipeline_data"]["06_pointing_correction"]["correction_factor"] == 0.5
    assert saved["pipeline_data"]["04_baseline_editor"]["review_evidence"].startswith("Astronomer")
    csv = (files / "spectrum.csv").read_text()
    assert "Calibrated_Jy" in csv and "Fit_Jy" in csv
    assert len(saved["completed_stages"]) == 8


def test_pointing_no_go_only_after_baseline_approval_and_override_is_recorded(job_batch, scientific_doubles):
    job, batch, root = job_batch
    scientific_doubles["verdict"] = "No-Go"
    held = batch_science.run_science(job, batch, root)
    job = copy.deepcopy(job)
    job["gates"]["04_baseline_editor"] = {
        "state": "approved", "signature": held.signature, "evidence": "Reviewer: emission-free region confirmed"
    }
    no_go = batch_science.run_science(job, batch, root)
    assert no_go.stage == "06_pointing_correction" and no_go.status == "needs_review"
    assert no_go.details["verdict"] == "No-Go"
    assert batch_science.load_review(root, batch["batch_id"], job["job_id"], no_go.signature)["type"] == "pointing"
    job["gates"]["06_pointing_correction"] = {
        "state": "approved", "signature": no_go.signature,
        "evidence": "Supervisor: manually inspected pointing scan"
    }
    job["review"].update({"note": "Rationale: checked independent calibrator",
                          "justification": "Independent calibrator confirms same pointing offset"})
    done = batch_science.run_science(job, batch, root)
    assert done.status == "completed" and done.automatic_pointing_pass is None
    path = batch_science.job_directory(root, batch["batch_id"], job["job_id"]) / "session.json"
    check = json.loads(path.read_text())["pipeline_data"]["06_pointing_correction"]["pointing_check"]
    assert check["overridden"] is True
    assert "independent calibrator" in check["override_note"]
    assert "Independent calibrator" in check["override_justification"]


def test_no_scan_cannot_be_approved_without_new_science(job_batch, scientific_doubles):
    job, batch, root = job_batch
    held = batch_science.run_science(job, batch, root)
    job = copy.deepcopy(job)
    job["gates"]["04_baseline_editor"] = {
        "state": "approved", "signature": held.signature, "evidence": "Reviewer confirmed baseline"
    }
    scientific_doubles["scan_available"] = False
    result = batch_science.run_science(job, batch, root)
    assert result.status == "needs_review" and result.approvable is False
    assert result.stage == "06_pointing_correction" and result.signature is None
    assert not (batch_science.job_directory(root, batch["batch_id"], job["job_id"]) / "session.json").exists()


def test_changed_data_invalidates_previously_approved_baseline(job_batch, scientific_doubles):
    job, batch, root = job_batch
    held = batch_science.run_science(job, batch, root)
    job = copy.deepcopy(job)
    job["gates"]["04_baseline_editor"] = {
        "state": "approved", "signature": held.signature, "evidence": "Reviewer confirmed baseline"
    }
    original = scientific_doubles["spectra"]["on_a.fits"]
    scientific_doubles["spectra"]["on_a.fits"] = {
        **original, "LCP": np.asarray(original["LCP"]) + 0.1,
    }
    changed = batch_science.run_science(job, batch, root)
    assert changed.status == "needs_review" and changed.stage == "04_baseline_editor"
    assert changed.signature != held.signature


def test_source_replay_preserves_nested_archive_relative_paths(tmp_path):
    """FR-19 replay must not lose the selected archive subdirectory."""
    root = tmp_path / "fits"
    data = root / "source" / "2026-08"
    data.mkdir(parents=True)
    job = {"block_name": "20260812_0.txt", "archive_root": str(root), "inputs": [
        {"filename": "pair_a.fits", "path": str(data / "pair_a.fits")},
        {"filename": "pair_b.fits", "path": str(data / "pair_b.fits")},
    ]}
    batch = {"batch_id": "a" * 32, "source_name": "W3(OH)", "frequency_mhz": 6668.5,
             "source_session_id": "ref"}
    selection = batch_science._pipeline_input(job, batch)
    assert selection["selected_files"] == ["source/2026-08/pair_a.fits", "source/2026-08/pair_b.fits"]
    assert selection["observation_blocks"]["20260812_0.txt"] == ["pair_a.fits", "pair_b.fits"]


def test_replay_rejects_an_archive_root_that_would_read_different_files(tmp_path):
    root = tmp_path / "fits"
    job = {"archive_root": str(root), "inputs": [
        {"filename": "a.fits", "path": str(root / "night" / "a.fits")},
    ]}
    assert batch_science.replay_paths_match(job, root)
    assert not batch_science.replay_paths_match(job, tmp_path / "different_fits")


def test_expanded_pair_science_enforces_operator_chosen_scan(job_batch, scientific_doubles):
    """The worker verifies both selected full pair and scan before trusting review signatures."""
    job, batch, root = job_batch
    names = [entry["filename"] for entry in job["inputs"]]
    assignment = {"source_job_id": job["job_id"], "pair_number": 2, "pair_total": 3,
                  "pair_files": names[:2], "scan_key": "original_block#2",
                  "scan_files": dict(zip(("N", "S", "E", "W", "Centre"), names[2:7])),
                  "scan_reference": names[7], "mode": "Frequency Switch",
                  "operator": "Observer", "note": "Matched by observation timestamps"}
    selected = copy.deepcopy(job)
    selected["pair_assignment"] = assignment
    baseline = batch_science.run_science(selected, batch, root)
    assert baseline.stage == "04_baseline_editor" and baseline.approvable
    selected["gates"]["04_baseline_editor"] = {
        "state": "approved", "signature": baseline.signature,
        "evidence": "Astronomer: verified the selected pair and baseline",
    }
    done = batch_science.run_science(selected, batch, root)
    assert done.status == "completed"
    output = batch_science.job_directory(root, batch["batch_id"], job["job_id"]) / "session.json"
    saved = json.loads(output.read_text())
    assert saved["pair_assignment"]["scan_key"] == "original_block#2"
    assert saved["pipeline_data"]["06_pointing_correction"]["scan_key"] == "original_block#2"

    selected["pair_assignment"] = {**assignment, "scan_reference": names[0]}
    with pytest.raises(ValueError, match="explicit operator assignment"):
        batch_science.run_science(selected, batch, root)
