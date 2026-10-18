# test_batch_queue.py — FR-21 (pass 1): queue validation, immutable inputs, persistence and review gates.
"""These tests use tiny temporary files and a fake FR-03 verifier, not real astronomy data.

Numerical CLC equivalence and full pipeline execution are explicitly outside
this pass and must not be marked completed by this test suite.
"""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from utils import batch_queue as queue


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "fits"
    root.mkdir()
    names = ["20260812_01_ON.fits", "20260812_02_OFF.fits",
             "20260813_01_ON.fits", "20260813_02_OFF.fits"]
    for name in names:
        (root / name).write_bytes(f"fake {name}".encode())
    selection = {
        "archive_root": str(root),
        "selected_files": names,
        "fits_file_paths": [str(root / name) for name in names],
        "source_name": "W3(OH)",
        "frequency_mhz": 1420.405,
        "observation_blocks": {
            "20260812_0.txt": names[:2],
            "20260813_0.txt": names[2:],
        },
        "discarded_files": [],
        "file_check_error": None,
    }
    return selection, root


def make(selection, **kwargs):
    return queue.prepare_batch(selection, source_session_id="s0102030", **kwargs)


def test_valid_blocks_are_queued_in_file_check_order_and_verifier_runs_once(source):
    selection, _ = source
    seen = []

    def valid_verifier(path):
        seen.append(path)
        return SimpleNamespace(ok=True, issues=[])

    original = copy.deepcopy(selection)
    manifest = make(selection, block_names=["20260813_0.txt", "20260812_0.txt"], verifier=valid_verifier)
    assert [j["block_name"] for j in manifest["jobs"]] == list(selection["observation_blocks"])
    assert [j["status"] for j in manifest["jobs"]] == ["pending", "pending"]
    assert len(seen) == 4
    assert selection == original  # no mutation to the FR-01 handoff
    assert queue.batch_progress(manifest) == (0, 2)
    assert manifest["template_session_id"] is None
    assert manifest["processing_enabled"] is False


def test_subset_selection_preserves_order(source):
    selection, _ = source
    manifest = make(selection, block_names=["20260813_0.txt"])
    assert len(manifest["jobs"]) == 1
    assert manifest["jobs"][0]["block_name"] == "20260813_0.txt"


def test_missing_fits_does_not_hide_a_bad_job_or_block_other_jobs(source):
    selection, root = source
    (root / "20260813_01_ON.fits").unlink()
    manifest = make(selection)
    assert [job["status"] for job in manifest["jobs"]] == ["pending", "invalid"]
    assert "missing" in " ".join(manifest["jobs"][1]["validation_issues"])


def test_duplicate_basenames_in_two_directories_are_not_guessed(source):
    selection, root = source
    other = root / "other"
    other.mkdir()
    name = selection["selected_files"][0]
    (other / name).write_bytes(b"other measurement")
    selection["selected_files"].append(f"other/{name}")
    selection["fits_file_paths"].append(str(other / name))
    result = make(selection)
    assert result["jobs"][0]["status"] == "invalid"
    assert "ambiguous" in " ".join(result["jobs"][0]["validation_issues"])


def test_repeated_file_across_blocks_is_explicitly_invalid(source):
    selection, _ = source
    name = selection["observation_blocks"]["20260812_0.txt"][0]
    selection["observation_blocks"]["20260813_0.txt"].append(name)
    jobs = make(selection)["jobs"]
    assert [job["status"] for job in jobs] == ["invalid", "invalid"]
    assert all("reused" in " ".join(job["validation_issues"]) for job in jobs)


def test_quarantine_and_corrupt_fits_are_rejected_independently(source):
    selection, root = source
    flagged_dir = root / "Flagged"
    flagged_dir.mkdir()
    old_path = root / selection["selected_files"][0]
    old_path.rename(flagged_dir / old_path.name)
    selection["selected_files"][0] = f"Flagged/{old_path.name}"
    selection["fits_file_paths"][0] = str(flagged_dir / old_path.name)

    def verify(path):
        return SimpleNamespace(ok=path.name != "20260813_01_ON.fits", issues=["checksum mismatch"])

    jobs = make(selection, verifier=verify)["jobs"]
    assert [j["status"] for j in jobs] == ["invalid", "invalid"]
    assert any("Flagged" in issue for issue in jobs[0]["validation_issues"])
    assert any("checksum mismatch" in issue for issue in jobs[1]["validation_issues"])


def test_verifier_exceptions_are_recorded_and_dont_abort_queue(source):
    selection, _ = source

    def verify(path):
        if path.name.startswith("20260812"):
            raise RuntimeError("problem in verifier")
        return SimpleNamespace(ok=True, issues=[])

    jobs = make(selection, verifier=verify)["jobs"]
    assert [job["status"] for job in jobs] == ["invalid", "pending"]
    assert "RuntimeError" in " ".join(jobs[0]["validation_issues"])


def test_empty_block_and_bad_block_name_become_explicit_invalid_or_error(source):
    selection, _ = source
    selection["observation_blocks"]["20260812_0.txt"] = []
    assert make(selection)["jobs"][0]["status"] == "invalid"
    selection["observation_blocks"]["../../bad.txt"] = []
    with pytest.raises(queue.BatchQueueError, match="single filename"):
        make(selection)


@pytest.mark.parametrize("change", [
    lambda s: s.update(file_check_error="sort failed"),
    lambda s: s.update(observation_blocks={}),
    lambda s: s.update(frequency_mhz=float("nan")),
    lambda s: s.update(selected_files=["../sneak.fits"]),
    lambda s: s.update(fits_file_paths=[]),
    lambda s: s.update(source_name=""),
    lambda s: s.update(archive_root=""),
])
def test_bad_selection_fails_without_modification(source, change):
    selection, _ = source
    change(selection)
    snapshot = json.dumps(selection, sort_keys=True)
    with pytest.raises(queue.BatchQueueError):
        make(selection)
    assert json.dumps(selection, sort_keys=True) == snapshot


def test_unselected_and_duplicate_block_names_fail(source):
    selection, _ = source
    with pytest.raises(queue.BatchQueueError, match="not present"):
        make(selection, block_names=["other.txt"])
    with pytest.raises(queue.BatchQueueError, match="unique"):
        make(selection, block_names=["20260812_0.txt"] * 2)


def test_unlinked_bad_file_in_discarded_list_not_silently_added(source):
    selection, _ = source
    selection["discarded_files"] = ["20260814_BAD.fits"]
    result = make(selection)
    assert result["discarded_files"] == ["20260814_BAD.fits"]
    assert all("BAD" not in inp["filename"] for job in result["jobs"] for inp in job["inputs"])


def test_create_and_reload_isolated_from_normal_sessions(source, tmp_path):
    selection, root = source
    original = {path: path.read_bytes() for path in root.glob("*.fits")}
    session_root = tmp_path / "sessions"
    path = queue.create_batch(session_root, make(selection))
    assert path.parent == session_root / "batches"
    assert len(list(session_root.glob("*.json"))) == 0
    manifest = queue.load_batch(session_root, path.stem)
    assert manifest["source_name"] == "W3(OH)"
    assert manifest["revision"] == 1
    assert {path: path.read_bytes() for path in root.glob("*.fits")} == original
    with pytest.raises(queue.BatchConflict, match="already exists"):
        queue.create_batch(session_root, manifest)


def test_cannot_path_traverse_queue_id_or_load_corrupt_json(source, tmp_path):
    selection, _ = source
    root = tmp_path / "sessions"
    path = queue.create_batch(root, make(selection))
    with pytest.raises(queue.BatchQueueError, match="Invalid batch ID"):
        queue.load_batch(root, "../outside")
    path.write_text('{"bad": ', encoding="utf-8")
    with pytest.raises(queue.BatchQueueError, match="Cannot read"):
        queue.load_batch(root, path.stem)


def test_input_change_is_detected_before_a_later_run(source):
    selection, root = source
    manifest = make(selection)
    first = manifest["jobs"][0]
    assert queue.revalidate_job_inputs(first) == []
    (root / first["inputs"][0]["filename"]).write_bytes(b"changed bytes")
    assert "changed" in " ".join(queue.revalidate_job_inputs(first))


def test_batch_jobs_cannot_start_before_processing_is_connected(source, tmp_path):
    selection, _ = source
    manifest = make(selection)
    queue.create_batch(tmp_path, manifest)
    with pytest.raises(queue.BatchQueueError, match="not connected"):
        queue.update_job_status(tmp_path, manifest["batch_id"], manifest["jobs"][0]["job_id"],
                                "running", expected_revision=1)
    assert queue.load_batch(tmp_path, manifest["batch_id"])["revision"] == 1


def test_review_approval_is_explicit_and_cannot_skip_or_approve_twice(source, tmp_path):
    selection, _ = source
    manifest = make(selection)
    # Simulate the later pass's worker enabling a configured and validated queue.
    manifest["processing_enabled"] = True
    path = tmp_path / "batches" / (manifest["batch_id"] + ".json")
    path.parent.mkdir()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    job_id = manifest["jobs"][0]["job_id"]
    with pytest.raises(queue.BatchQueueError, match="Unsafe"):
        queue.update_job_status(tmp_path, manifest["batch_id"], job_id, "completed", expected_revision=1)
    running = queue.update_job_status(tmp_path, manifest["batch_id"], job_id, "running", expected_revision=1)
    hold = queue.update_job_status(
        tmp_path, manifest["batch_id"], job_id, "needs_review", expected_revision=running["revision"],
        reason="Pointing outside 2.5 sigma", review_stage="06_pointing_correction",
    )
    assert hold["jobs"][0]["review"]["state"] == "requested"
    with pytest.raises(queue.BatchQueueError, match="Unsafe"):
        queue.update_job_status(tmp_path, manifest["batch_id"], job_id, "running",
                                expected_revision=hold["revision"])
    with pytest.raises(queue.BatchQueueError, match="named reviewer"):
        queue.approve_review(tmp_path, manifest["batch_id"], job_id, expected_revision=hold["revision"],
                             reviewer="", note="I checked it")
    approved = queue.approve_review(
        tmp_path, manifest["batch_id"], job_id, expected_revision=hold["revision"],
        reviewer="operator", note="Reviewed scan and accepted fit",
    )
    assert approved["jobs"][0]["status"] == "pending"
    assert approved["jobs"][0]["review"]["reviewer"] == "operator"
    with pytest.raises(queue.BatchQueueError, match="pending review request"):
        queue.approve_review(tmp_path, manifest["batch_id"], job_id, expected_revision=approved["revision"],
                             reviewer="operator", note="duplicate approval")
    restarted = queue.update_job_status(
        tmp_path, manifest["batch_id"], job_id, "running",
        expected_revision=approved["revision"],
    )
    with pytest.raises(queue.BatchQueueError, match="unresolved review gates"):
        queue.update_job_status(tmp_path, manifest["batch_id"], job_id, "completed",
                                expected_revision=restarted["revision"])
    ready = queue.record_automatic_gate_pass(
        tmp_path, manifest["batch_id"], job_id, "04_baseline_editor",
        expected_revision=restarted["revision"], evidence="CLC baseline checked for this observation",
    )
    completed = queue.update_job_status(
        tmp_path, manifest["batch_id"], job_id, "completed", expected_revision=ready["revision"],
        session_id="batch_test", output_files=["spectrum.csv", "spectrum.fits", "graphs.pdf", "session.json"],
    )
    assert queue.batch_progress(completed) == (1, 2)
    assert any(log["action"] == "review_approved" for log in completed["audit_log"])


def test_stale_revision_does_not_overwrite_existing_queue(source, tmp_path):
    selection, _ = source
    manifest = make(selection)
    manifest["processing_enabled"] = True
    path = tmp_path / "batches" / (manifest["batch_id"] + ".json")
    path.parent.mkdir()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    job_id = manifest["jobs"][0]["job_id"]
    first = queue.update_job_status(tmp_path, manifest["batch_id"], job_id, "running", expected_revision=1)
    with pytest.raises(queue.BatchConflict, match="Reload"):
        queue.update_job_status(tmp_path, manifest["batch_id"], job_id, "failed", expected_revision=1,
                                reason="stale worker")
    assert queue.load_batch(tmp_path, manifest["batch_id"])["revision"] == first["revision"]


def test_failed_job_requires_explicit_retry_and_preserves_other_jobs(source, tmp_path):
    selection, _ = source
    manifest = make(selection)
    manifest["processing_enabled"] = True
    path = tmp_path / "batches" / (manifest["batch_id"] + ".json")
    path.parent.mkdir()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    job_id = manifest["jobs"][0]["job_id"]
    running = queue.update_job_status(tmp_path, manifest["batch_id"], job_id, "running", expected_revision=1)
    failed = queue.update_job_status(tmp_path, manifest["batch_id"], job_id, "failed",
                                     expected_revision=running["revision"], reason="mock compute error")
    assert failed["jobs"][1]["status"] == "pending"
    with pytest.raises(queue.BatchQueueError, match="Unsafe"):
        queue.update_job_status(tmp_path, manifest["batch_id"], job_id, "running",
                                expected_revision=failed["revision"])
    again = queue.retry_job(tmp_path, manifest["batch_id"], job_id, expected_revision=failed["revision"])
    assert again["jobs"][0]["status"] == "pending"
    assert again["jobs"][0]["error"] is None


def test_automatic_gate_cannot_bypass_a_pending_review(source, tmp_path):
    selection, _ = source
    manifest = make(selection)
    manifest["processing_enabled"] = True
    path = tmp_path / "batches" / (manifest["batch_id"] + ".json")
    path.parent.mkdir()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    job_id = manifest["jobs"][0]["job_id"]
    running = queue.update_job_status(tmp_path, manifest["batch_id"], job_id, "running", expected_revision=1)
    held = queue.update_job_status(
        tmp_path, manifest["batch_id"], job_id, "needs_review", expected_revision=running["revision"],
        review_stage="04_baseline_editor", reason="Incorrect line-free interval",
    )
    assert held["jobs"][0]["gates"]["04_baseline_editor"]["state"] == "requested"
    with pytest.raises(queue.BatchQueueError, match="during active processing"):
        queue.record_automatic_gate_pass(
            tmp_path, manifest["batch_id"], job_id, "04_baseline_editor",
            expected_revision=held["revision"], evidence="bypass attempt",
        )
    assert queue.load_batch(tmp_path, manifest["batch_id"])["revision"] == held["revision"]
