# test_batch_runner.py — FR-21: sequential status changes, failures and review holds.
"""Fake science is injected solely to test the worker; fake outputs cannot mark jobs completed."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from utils import batch_queue as queue, batch_runner, batch_science


def prepared(tmp_path, count=2):
    fits = tmp_path / "fits"
    fits.mkdir()
    names = [f"2026_{i}_ON.fits" for i in range(count)]
    for name in names:
        (fits / name).write_bytes(b"test contents")
    selection = {
        "archive_root": str(fits), "selected_files": names,
        "fits_file_paths": [str(fits / n) for n in names],
        "source_name": "W3(OH)", "frequency_mhz": 1420.405,
        "observation_blocks": {f"2026_{i}.txt": [n] for i, n in enumerate(names)},
    }
    manifest = queue.prepare_batch(selection, source_session_id="s0102030")
    queue.create_batch(tmp_path / "sessions", manifest)
    template = {
        "version": 1, "session_id": "reference", "source_file": "reference.json", "source_sha256": "a" * 64,
        "settings": {"bandpass_mode": "Frequency Switch", "baseline_blocks": [{"start": -10, "end": -8}],
                     "polynomial_orders": {"LCP": 3, "RCP": 4}, "fit_type": "1D Gaussian",
                     "pointing_peak_velocity_kms": None, "pointing_half_width_channels": 4},
    }
    root = tmp_path / "sessions"
    enabled = queue.pin_batch_template(root, manifest["batch_id"], template, expected_revision=1)
    return root, enabled


def output_files(root, manifest, job):
    folder = batch_science.job_directory(root, manifest["batch_id"], job["job_id"])
    folder.mkdir(parents=True, exist_ok=True)
    names = ("spectrum.csv", "spectrum.fits", "graphs.pdf", "session.json")
    for name in names:
        (folder / name).write_bytes(b"fake science output for gate tests")
    return names


def test_baseline_review_holds_campaign_and_reviewer_can_approve(tmp_path):
    root, manifest = prepared(tmp_path)
    batches = []
    expected_signature = "a" * 64

    def science(job, batch, root, *, on_stage):
        batches.append(job["block_name"])
        on_stage("04_baseline_editor")
        if job["gates"]["04_baseline_editor"]["state"] != "approved":
            return batch_science.ScienceOutcome(
                "needs_review", "04_baseline_editor", "Check science", expected_signature, {"order": 3}, True,
            )
        assert job["gates"]["04_baseline_editor"]["signature"] == expected_signature
        output = output_files(root, batch, job)
        return batch_science.ScienceOutcome(
            "completed", "08_export_and_session", automatic_pointing_pass="Go, 1 sigma",
            session_id=f"batch_{job['job_id'][:16]}", output_files=output,
        )

    held = batch_runner.run_campaign(root, manifest["batch_id"], processor=science)
    assert [j["status"] for j in held["jobs"]] == ["needs_review", "pending"]
    assert batches == ["2026_0.txt"]
    with pytest.raises(queue.BatchQueueError, match="Review"):
        batch_runner.run_next(root, manifest["batch_id"], processor=science)
    with pytest.raises(queue.BatchQueueError, match="named reviewer"):
        queue.approve_review(root, manifest["batch_id"], held["jobs"][0]["job_id"],
                             expected_revision=held["revision"], reviewer="", note="scientific check")
    approved = queue.approve_review(root, manifest["batch_id"], held["jobs"][0]["job_id"],
                                    expected_revision=held["revision"], reviewer="Astronomer",
                                    note="Emission-free windows match observed spectrum")
    done = batch_runner.run_campaign(root, manifest["batch_id"], processor=science)
    assert [j["status"] for j in done["jobs"]] == ["completed", "needs_review"]
    assert done["jobs"][0]["gates"]["06_pointing_correction"]["state"] == "passed"
    assert queue.batch_progress(done) == (1, 2)
    assert batches == ["2026_0.txt", "2026_0.txt", "2026_1.txt"]
    assert approved["jobs"][0]["review"]["state"] == "approved"


def test_one_failed_job_does_not_overwrite_other_jobs(tmp_path):
    root, manifest = prepared(tmp_path)

    def science(job, batch, root, *, on_stage):
        on_stage("02_file_loader")
        if job["block_name"] == "2026_0.txt":
            raise RuntimeError("corrupt science calculation")
        return batch_science.ScienceOutcome("needs_review", "06_pointing_correction", "missing scan",
                                            approvable=False)

    result = batch_runner.run_campaign(root, manifest["batch_id"], processor=science)
    assert [job["status"] for job in result["jobs"]] == ["failed", "needs_review"]
    assert "corrupt science calculation" in result["jobs"][0]["error"]
    job = result["jobs"][1]
    with pytest.raises(queue.BatchQueueError, match="approval cannot bypass"):
        queue.approve_review(root, manifest["batch_id"], job["job_id"],
                             expected_revision=result["revision"], reviewer="Scientist", note="fine")
    assert queue.load_batch(root, manifest["batch_id"])["revision"] == result["revision"]


def test_no_completion_from_unsaved_or_unapproved_result(tmp_path):
    root, manifest = prepared(tmp_path, count=1)

    def fake(job, batch, root, *, on_stage):
        return batch_science.ScienceOutcome("completed", "08_export_and_session", session_id="fake",
                                            output_files=("spectrum.csv", "spectrum.fits", "graphs.pdf",
                                                          "session.json"))

    result = batch_runner.run_campaign(root, manifest["batch_id"], processor=fake)
    assert result["jobs"][0]["status"] == "failed"
    assert "without four saved" in result["jobs"][0]["error"]
    output_files(root, result, result["jobs"][0])
    retried = queue.retry_job(root, result["batch_id"], result["jobs"][0]["job_id"],
                              expected_revision=result["revision"])
    result = batch_runner.run_campaign(root, retried["batch_id"], processor=fake)
    assert result["jobs"][0]["status"] == "failed"
    assert "unresolved review gates" in result["jobs"][0]["error"]


def test_second_runner_cannot_claim_another_job_while_running(tmp_path):
    root, manifest = prepared(tmp_path)
    job = manifest["jobs"][0]
    running = queue.update_job_status(root, manifest["batch_id"], job["job_id"], "running",
                                      expected_revision=manifest["revision"])
    with pytest.raises(queue.BatchQueueError, match="already running"):
        batch_runner.run_next(root, manifest["batch_id"])
    with pytest.raises(queue.BatchQueueError, match="Another observation"):
        queue.update_job_status(root, manifest["batch_id"], running["jobs"][1]["job_id"], "running",
                                expected_revision=running["revision"])


def test_cannot_mutate_template_after_any_job_started(tmp_path):
    root, manifest = prepared(tmp_path)
    template = copy.deepcopy(manifest["template"])
    with pytest.raises(queue.BatchQueueError, match="unstarted"):
        queue.pin_batch_template(root, manifest["batch_id"], template,
                                 expected_revision=manifest["revision"])
    corrupt = root / "batches" / (manifest["batch_id"] + ".json")
    raw = json.loads(corrupt.read_text())
    raw["template"]["settings"]["fit_type"] = "2D Gaussian"
    corrupt.write_text(json.dumps(raw))
    with pytest.raises(queue.BatchQueueError, match="fingerprint"):
        batch_runner.run_next(root, manifest["batch_id"])


def test_pointing_no_go_needs_separate_justification(tmp_path):
    """A note alone never overrides a measured No-Go; both reasons are audited."""
    root, manifest = prepared(tmp_path, count=1)
    job = manifest["jobs"][0]
    running = queue.update_job_status(root, manifest["batch_id"], job["job_id"], "running",
                                      expected_revision=manifest["revision"])
    held = queue.update_job_status(
        root, manifest["batch_id"], job["job_id"], "needs_review",
        expected_revision=running["revision"], reason="Measured pointing offset exceeds 2.5 sigma",
        stage="06_pointing_correction", review_stage="06_pointing_correction",
        review_signature="a" * 64, review_details={"verdict": "No-Go", "reasons": ["2.5 sigma"]},
        approvable=True,
    )
    with pytest.raises(queue.BatchQueueError, match="separate scientific justification"):
        queue.approve_review(root, manifest["batch_id"], job["job_id"],
                             expected_revision=held["revision"], reviewer="Scientist",
                             note="Visually inspected the scans")
    approved = queue.approve_review(root, manifest["batch_id"], job["job_id"],
                                    expected_revision=held["revision"], reviewer="Scientist",
                                    note="Visually inspected the scans",
                                    justification="Independent calibrator verifies this broad line")
    assert approved["jobs"][0]["status"] == "pending"
    assert approved["jobs"][0]["review"]["justification"].startswith("Independent")
    assert approved["jobs"][0]["gates"]["06_pointing_correction"]["state"] == "approved"
    assert any(entry["action"] == "review_approved" and "scientific justification" in entry["detail"]
               for entry in approved["audit_log"])


def test_unapprovable_review_can_be_skipped_without_completing_science(tmp_path):
    """Skipping never passes a gate, but unlocks the next sequential observation."""
    root, manifest = prepared(tmp_path)

    def science(job, batch, root, *, on_stage):
        if job["block_name"] == "2026_0.txt":
            return batch_science.ScienceOutcome(
                "needs_review", "03_bandpass_correction", "Ambiguous full-integration pair", approvable=False,
            )
        return batch_science.ScienceOutcome(
            "needs_review", "04_baseline_editor", "Review baseline", "f" * 64, approvable=True,
        )

    held = batch_runner.run_campaign(root, manifest["batch_id"], processor=science)
    assert [item["status"] for item in held["jobs"]] == ["needs_review", "pending"]
    with pytest.raises(queue.BatchQueueError, match="operator name and a reason"):
        queue.skip_held_job(root, manifest["batch_id"], held["jobs"][0]["job_id"],
                            expected_revision=held["revision"], operator="", reason="cannot locate pair")
    skipped = queue.skip_held_job(root, manifest["batch_id"], held["jobs"][0]["job_id"],
                                  expected_revision=held["revision"], operator="Astronomer",
                                  reason="requires new observation data")
    assert skipped["jobs"][0]["status"] == "failed"
    assert skipped["jobs"][0]["gates"]["04_baseline_editor"]["state"] == "pending"
    assert skipped["jobs"][0]["gates"]["06_pointing_correction"]["state"] == "pending"
    assert skipped["jobs"][0]["review"]["skipped_by"] == "Astronomer"
    again = batch_runner.run_campaign(root, manifest["batch_id"], processor=science)
    assert [item["status"] for item in again["jobs"]] == ["failed", "needs_review"]


def test_changed_input_is_invalidated_and_next_job_proceeds(tmp_path):
    """A file replaced after preparation is never silently processed."""
    root, manifest = prepared(tmp_path)
    Path(manifest["jobs"][0]["inputs"][0]["path"]).write_bytes(b"changed source file contents")
    called = []

    def science(job, batch, root, *, on_stage):
        called.append(job["block_name"])
        return batch_science.ScienceOutcome("needs_review", "04_baseline_editor",
                                            "Review baseline", "f" * 64, approvable=True)

    result = batch_runner.run_campaign(root, manifest["batch_id"], processor=science)
    assert [item["status"] for item in result["jobs"]] == ["invalid", "needs_review"]
    assert called == ["2026_1.txt"]
    assert "requeue" in " ".join(result["jobs"][0]["validation_issues"])


def test_recovery_rejects_active_worker_then_allows_stale_interruption(tmp_path):
    """Recovery cannot free a live worker even when its start timestamp is old."""
    from datetime import datetime, timedelta, timezone
    root, manifest = prepared(tmp_path, count=1)
    job = manifest["jobs"][0]
    running = queue.update_job_status(root, manifest["batch_id"], job["job_id"], "running",
                                      expected_revision=manifest["revision"])
    with pytest.raises(queue.BatchQueueError, match="wait an hour"):
        queue.mark_interrupted_job(root, manifest["batch_id"], job["job_id"],
                                   expected_revision=running["revision"])
    path = root / "batches" / f"{manifest['batch_id']}.json"
    old = json.loads(path.read_text())
    old["jobs"][0]["started_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    path.write_text(json.dumps(old))
    with queue.worker_lock(root, manifest["batch_id"], job["job_id"]):
        with pytest.raises(queue.BatchConflict, match="worker is still active"):
            queue.mark_interrupted_job(root, manifest["batch_id"], job["job_id"],
                                       expected_revision=running["revision"])
    recovered = queue.mark_interrupted_job(root, manifest["batch_id"], job["job_id"],
                                           expected_revision=running["revision"])
    assert recovered["jobs"][0]["status"] == "failed"
    assert recovered["jobs"][0]["error"] == "Worker interrupted"
    assert any(entry["action"] == "worker_interrupted" for entry in recovered["audit_log"])


def test_interrupted_partial_result_cannot_be_mistaken_for_completed_job(tmp_path):
    """A stale CSV from a crashed attempt is never sufficient for completion."""
    root, manifest = prepared(tmp_path, count=1)
    job = manifest["jobs"][0]

    def crashes_after_one_output(current_job, batch, sessions_root, *, on_stage):
        on_stage("08_export_and_session")
        folder = batch_science.job_directory(sessions_root, batch["batch_id"], current_job["job_id"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "spectrum.csv").write_bytes(b"incomplete-output")
        raise OSError("simulated disk interruption")

    failed = batch_runner.run_campaign(root, manifest["batch_id"], processor=crashes_after_one_output)
    assert failed["jobs"][0]["status"] == "failed"
    retried = queue.retry_job(root, manifest["batch_id"], job["job_id"],
                              expected_revision=failed["revision"])

    def falsely_reports_completion(current_job, batch, sessions_root, *, on_stage):
        return batch_science.ScienceOutcome("completed", "08_export_and_session",
                                            session_id="retry_done",
                                            output_files=("spectrum.csv", "spectrum.fits",
                                                          "graphs.pdf", "session.json"))

    refused = batch_runner.run_campaign(root, manifest["batch_id"], processor=falsely_reports_completion)
    assert refused["jobs"][0]["status"] == "failed"
    assert "four saved" in refused["jobs"][0]["error"]
    assert retried["jobs"][0]["session_id"] is None
