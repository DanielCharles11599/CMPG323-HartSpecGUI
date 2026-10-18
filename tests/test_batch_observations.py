# test_batch_observations.py — FR-21: no silent drops in complex, multi-scan observation blocks.
"""Synthetic spectral metadata; the real FITS/CLC adapters are tested separately."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils import batch_observations as obs, batch_queue as queue, pointing_logic


def complex_observation(tmp_path):
    """Construct two integration pairs and two valid six-file pointing scans."""
    archive = tmp_path / "fits"
    archive.mkdir()
    pairs = [("a_on.fits", "a_off.fits"), ("b_on.fits", "b_off.fits")]
    positions = {p[0]: (0, "ON") for p in pairs}
    positions.update({p[1]: (0, "OFF") for p in pairs})
    for scan in (1, 2):
        for role, position in (("n", "HPN"), ("s", "HPS"), ("e", "HPE"), ("w", "HPW"),
                               ("c", "ON"), ("ref", "OFF")):
            positions[f"{scan}_{role}.fits"] = (1, position)
    names = [name for pair in pairs for name in pair]
    for scan in (1, 2):
        names.extend(f"{scan}_{role}.fits" for role in ("n", "s", "e", "w", "c", "ref"))
    for name in names:
        (archive / name).write_bytes(f"synthetic metadata for {name}".encode())
    selection = {
        "archive_root": str(archive), "source_name": "W3(OH)", "frequency_mhz": 6668.5,
        "selected_files": names, "fits_file_paths": [str(archive / name) for name in names],
        "observation_blocks": {"20260812_0.txt": names},
    }
    batch = queue.prepare_batch(selection, source_session_id="testref")
    root = tmp_path / "sessions"
    queue.create_batch(root, batch)

    def ingest(path):
        filename = Path(path).name
        pointing, position = positions[filename]
        spectrum = {"pointing": pointing, "position": position}
        return SimpleNamespace(ok=True, spectrum=spectrum, load_errors={})

    def get_pairs(entries):
        full = [entry for entry in entries if entry["pointing"] == 0]
        return [(full[index], full[index + 1]) for index in range(0, len(full) - 1, 2)]

    def mode(pair):
        return ("Position Switch", "second integration is OFF")

    reader = obs.inspect_observation_job

    def inspect(job):
        return reader(
            job, ingest=ingest, get_pairs=get_pairs, suggest_mode=mode,
            find_scans=pointing_logic.find_pointing_scans,
        )

    return root, batch, inspect, positions


def test_split_preserves_every_pair_in_file_check_order_and_all_review_gates(tmp_path):
    root, manifest, inspect, _ = complex_observation(tmp_path)
    candidate = inspect(manifest["jobs"][0])
    assert [pair["files"] for pair in candidate["pairs"]] == [
        ["a_on.fits", "a_off.fits"], ["b_on.fits", "b_off.fits"]]
    assert len(candidate["scans"]) == 2
    mapping = {"1": candidate["scans"][0]["key"], "2": candidate["scans"][1]["key"]}
    split = obs.split_observation_job(
        root, manifest["batch_id"], manifest["jobs"][0]["job_id"], expected_revision=1,
        inspection_signature=candidate["signature"], assignments=mapping,
        operator="Observatory Scientist", note="Each pair uses its corresponding observed scan",
        inspect=inspect,
    )
    assert len(split["jobs"]) == 2
    assert [job["pair_assignment"]["pair_number"] for job in split["jobs"]] == [1, 2]
    assert [len(job["inputs"]) for job in split["jobs"]] == [8, 8]
    assert len({job["job_id"] for job in split["jobs"]}) == 2
    for job in split["jobs"]:
        assert job["status"] == "pending"
        assert job["output_files"] == []
        assert all(gate["state"] == "pending" for gate in job["gates"].values())
        assert len(job["pair_assignment"]["scan_files"]) == 5
        assert job["pair_assignment"]["operator"] == "Observatory Scientist"
        assert "pair" in obs.job_label(job)
    loaded = queue.load_batch(root, manifest["batch_id"])
    assert loaded == split
    assert any(record["action"] == "block_split" for record in loaded["audit_log"])


def test_unassigned_scan_or_unacknowledged_reuse_cannot_expand(tmp_path):
    root, manifest, inspect, _ = complex_observation(tmp_path)
    result = inspect(manifest["jobs"][0])
    first = result["scans"][0]["key"]
    args = dict(sessions_root=root, batch_id=manifest["batch_id"], job_id=result["job_id"],
                expected_revision=1, inspection_signature=result["signature"],
                operator="Astronomer", note="A calibration scan applies to both integrations", inspect=inspect)
    with pytest.raises(queue.BatchQueueError, match="Every integration pair"):
        obs.split_observation_job(**args, assignments={"1": first})
    with pytest.raises(queue.BatchQueueError, match="Reusing a pointing scan"):
        obs.split_observation_job(**args, assignments={"1": first, "2": first})
    with pytest.raises(queue.BatchQueueError, match="Unused complete pointing scans"):
        obs.split_observation_job(**args, assignments={"1": first, "2": first}, acknowledge_shared=True)
    split = obs.split_observation_job(**args, assignments={"1": first, "2": first},
                                      acknowledge_shared=True, acknowledge_unused=True)
    assert all(job["pair_assignment"]["shared_scan"] for job in split["jobs"])
    assert all(job["pair_assignment"]["unused_scans"] for job in split["jobs"])


def test_inspection_change_prevents_stale_split_and_does_not_update_manifest(tmp_path):
    root, manifest, inspect, _ = complex_observation(tmp_path)
    current = inspect(manifest["jobs"][0])
    Path(manifest["jobs"][0]["inputs"][0]["path"]).write_bytes(b"changed")
    with pytest.raises(queue.BatchQueueError, match="Source FITS changed"):
        obs.split_observation_job(
            root, manifest["batch_id"], current["job_id"], expected_revision=1,
            inspection_signature=current["signature"],
            assignments={"1": current["scans"][0]["key"], "2": current["scans"][1]["key"]},
            operator="Observer", note="Explicit pairing", inspect=inspect,
        )
    assert queue.load_batch(root, manifest["batch_id"])["revision"] == 1


def test_odd_integration_count_does_not_silently_drop_a_file(tmp_path):
    root, manifest, inspect, positions = complex_observation(tmp_path)
    job = manifest["jobs"][0]
    positions["2_ref.fits"] = (0, "OFF")
    with pytest.raises(queue.BatchQueueError, match="must belong to unambiguous"):
        inspect(job)


def test_forged_pair_assignment_with_extra_or_wrong_inputs_rejected(tmp_path):
    root, manifest, inspect, _ = complex_observation(tmp_path)
    result = inspect(manifest["jobs"][0])
    split = obs.split_observation_job(
        root, manifest["batch_id"], result["job_id"], expected_revision=1,
        inspection_signature=result["signature"],
        assignments={"1": result["scans"][0]["key"], "2": result["scans"][1]["key"]},
        operator="Reviewer", note="Confirm observation-pair boundary", inspect=inspect,
    )
    file = root / "batches" / f"{manifest['batch_id']}.json"
    broken = copy.deepcopy(split)
    broken["jobs"][0]["pair_assignment"]["scan_reference"] = "wrong.fits"
    file.write_text(json.dumps(broken))
    with pytest.raises(queue.BatchQueueError, match="match exactly"):
        queue.load_batch(root, manifest["batch_id"])


def test_single_pair_and_single_scan_does_not_need_split(tmp_path):
    root, manifest, inspect, _ = complex_observation(tmp_path)
    single = copy.deepcopy(manifest["jobs"][0])
    keep = {"a_on.fits", "a_off.fits"} | {f"1_{name}.fits" for name in ("n", "s", "e", "w", "c", "ref")}
    single["inputs"] = [item for item in single["inputs"] if item["filename"] in keep]
    inspected = inspect(single)
    assert len(inspected["pairs"]) == len(inspected["scans"]) == 1
    with pytest.raises(queue.BatchQueueError, match="unnecessary"):
        obs.split_observation_job(
            root, manifest["batch_id"], manifest["jobs"][0]["job_id"], expected_revision=1,
            inspection_signature=inspected["signature"], assignments={"1": inspected["scans"][0]["key"]},
            operator="Astronomer", note="No split", inspect=lambda job: inspected,
        )


def test_expanded_pairs_have_independent_review_and_exports_in_sequential_runner(tmp_path):
    """Each pair requires its own fresh approval; completing pair 1 never approves pair 2."""
    import hashlib
    from utils import batch_runner, batch_science, batch_template

    root, manifest, inspect, _ = complex_observation(tmp_path)
    candidate = inspect(manifest["jobs"][0])
    manifest = obs.split_observation_job(
        root, manifest["batch_id"], candidate["job_id"], expected_revision=1,
        inspection_signature=candidate["signature"],
        assignments={"1": candidate["scans"][0]["key"], "2": candidate["scans"][1]["key"]},
        operator="Scientist", note="The scans bracket their corresponding integrations", inspect=inspect,
    )
    template = {
        "version": 1, "session_id": "manual", "source_file": "manual.json",
        "source_sha256": "a" * 64,
        "settings": {
            "bandpass_mode": "Position Switch",
            "baseline_blocks": [{"start": -10, "end": -8}],
            "polynomial_orders": {"LCP": 3, "RCP": 4},
            "fit_type": "1D Gaussian",
            "pointing_peak_velocity_kms": None, "pointing_half_width_channels": 4,
        },
    }
    manifest = queue.pin_batch_template(root, manifest["batch_id"], template,
                                        expected_revision=manifest["revision"])
    assert manifest["template_signature"] == batch_template.signature(template)

    def scientist(job, batch, root, *, on_stage):
        signature = hashlib.sha256(str(job["pair_assignment"]["pair_number"]).encode()).hexdigest()
        on_stage("04_baseline_editor")
        if job["gates"]["04_baseline_editor"].get("signature") != signature:
            return batch_science.ScienceOutcome("needs_review", "04_baseline_editor", "Review actual pair",
                                                signature=signature, approvable=True)
        on_stage("06_pointing_correction")
        folder = batch_science.job_directory(root, batch["batch_id"], job["job_id"])
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("spectrum.csv", "spectrum.fits", "graphs.pdf", "session.json"):
            (folder / name).write_bytes(f"pair {job['pair_assignment']['pair_number']} {name}".encode())
        return batch_science.ScienceOutcome("completed", "08_export_and_session",
                                            automatic_pointing_pass="Go, evaluated on this scan",
                                            session_id=f"session_{job['job_id'][:16]}",
                                            output_files=("spectrum.csv", "spectrum.fits",
                                                          "graphs.pdf", "session.json"))

    first = batch_runner.run_campaign(root, manifest["batch_id"], processor=scientist)
    assert [row["status"] for row in first["jobs"]] == ["needs_review", "pending"]
    first_approved = queue.approve_review(root, manifest["batch_id"], first["jobs"][0]["job_id"],
                                          expected_revision=first["revision"], reviewer="Supervisor",
                                          note="First pair baseline validated")
    assert first_approved["jobs"][0]["status"] == "pending"
    second = batch_runner.run_campaign(root, manifest["batch_id"], processor=scientist)
    assert [row["status"] for row in second["jobs"]] == ["completed", "needs_review"]
    assert second["jobs"][1]["gates"]["04_baseline_editor"]["state"] == "requested"
    assert second["jobs"][0]["session_id"] != second["jobs"][1]["session_id"]
    next_approved = queue.approve_review(root, manifest["batch_id"], second["jobs"][1]["job_id"],
                                         expected_revision=second["revision"], reviewer="Supervisor",
                                         note="Second pair independently validated")
    assert next_approved["jobs"][1]["status"] == "pending"
    finished = batch_runner.run_campaign(root, manifest["batch_id"], processor=scientist)
    assert [job["status"] for job in finished["jobs"]] == ["completed", "completed"]
    assert finished["jobs"][0]["session_id"] != finished["jobs"][1]["session_id"]
    assert queue.batch_progress(finished) == (2, 2)
    assert all(job["gates"]["06_pointing_correction"]["state"] == "passed" for job in finished["jobs"])
