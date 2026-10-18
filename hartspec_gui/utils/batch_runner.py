# batch_runner.py — FR-21: sequential queue runner, safe review holds and interruption recovery.
"""Orchestrate one scientifically independent observation block at a time.

Each click executes synchronously on the Streamlit server; no unsafe process
worker/global st.session_state is shared between users. Results and review
previews live in a separate directory per job. The queue manifest is updated
with POSIX file locks and optimistic revisions for concurrent tabs/processes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from utils import batch_queue, batch_science, batch_template


class NoJobReady(batch_queue.BatchQueueError):
    """Queue has nothing processable or a review/running job blocks forward progress."""


def _matching_file_outputs(root: Path, batch_id: str, job_id: str, names: tuple[str, ...]) -> bool:
    """Completion means real nonempty isolated outputs, not only a callback claiming success."""
    required = {"spectrum.csv", "spectrum.fits", "graphs.pdf", "session.json"}
    if set(names) != required or len(names) != len(required):
        return False
    folder = batch_science.job_directory(root, batch_id, job_id)
    return all((folder / name).is_file() and (folder / name).stat().st_size > 0 for name in required)


def run_next(
    sessions_root: str | Path, batch_id: str, *,
    on_stage: Callable[[str], None] | None = None,
    processor: Callable[..., batch_science.ScienceOutcome] | None = None,
) -> dict[str, Any] | None:
    """Claim and attempt exactly the first pending observation in File_check order.

    A held observation blocks subsequent jobs until it is approved or explicitly
    stopped. Failed observations do not block other jobs: the next call attempts
    the next pending block. The optional processor is solely a test seam.
    """
    root = Path(sessions_root)
    manifest = batch_queue.load_batch(root, batch_id)
    if not manifest.get("processing_enabled") or not isinstance(manifest.get("template"), Mapping):
        raise NoJobReady("Select a compatible saved reference session and activate the queue first.")
    if manifest.get("template_signature") != batch_template.signature(manifest["template"]):
        raise NoJobReady("Queue template fingerprint does not match the frozen settings.")
    blocked = next((job for job in manifest["jobs"] if job["status"] == "running"), None)
    if blocked:
        raise NoJobReady("A block is already running. Do not start a second processor; recover only if interrupted.")
    blocked = next((job for job in manifest["jobs"] if job["status"] == "needs_review"), None)
    if blocked:
        raise NoJobReady(f"Review {blocked['block_name']} before advancing the sequential campaign.")
    job = next((item for item in manifest["jobs"] if item["status"] == "pending"), None)
    if job is None:
        return None
    if batch_queue.revalidate_job_inputs(job):
        return batch_queue.invalidate_changed_job(
            root, batch_id, job["job_id"], expected_revision=manifest["revision"]
        )
    document = batch_queue.update_job_status(root, batch_id, job["job_id"], "running",
                                             expected_revision=manifest["revision"])
    active = next(item for item in document["jobs"] if item["job_id"] == job["job_id"])
    last_stage = "01_source_browser"

    def on_step(stage: str) -> None:
        nonlocal last_stage
        last_stage = stage
        if on_stage:
            on_stage(stage)

    try:
        execute = processor or batch_science.run_science
        with batch_queue.worker_lock(root, batch_id, job["job_id"]):
            result = execute(active, document, root, on_stage=on_step)
        if not isinstance(result, batch_science.ScienceOutcome):
            raise TypeError("Batch stage executor must return a ScienceOutcome.")
        if result.status == "needs_review":
            return batch_queue.update_job_status(
                root, batch_id, job["job_id"], "needs_review", expected_revision=document["revision"],
                reason=result.reason, review_stage=result.stage, review_signature=result.signature,
                review_details=result.details, approvable=result.approvable, stage=result.stage,
            )
        if result.status != "completed":
            raise ValueError(f"Unexpected scientific worker result: {result.status}")
        if not _matching_file_outputs(root, batch_id, job["job_id"], result.output_files):
            raise ValueError("Worker returned completion without four saved CSV/FITS/PDF/session files.")
        if result.automatic_pointing_pass:
            document = batch_queue.record_automatic_gate_pass(
                root, batch_id, job["job_id"], "06_pointing_correction",
                expected_revision=document["revision"], evidence=result.automatic_pointing_pass,
            )
        return batch_queue.update_job_status(
            root, batch_id, job["job_id"], "completed", expected_revision=document["revision"],
            session_id=result.session_id, output_files=result.output_files, stage=result.stage,
        )
    except Exception as exc:  # noqa: BLE001 — isolate failure to this one job, keep others queued
        latest = batch_queue.load_batch(root, batch_id)
        current = next(item for item in latest["jobs"] if item["job_id"] == job["job_id"])
        if current["status"] != "running":
            raise  # Another tab has already intervened; never overwrite its decision.
        return batch_queue.update_job_status(
            root, batch_id, job["job_id"], "failed", expected_revision=latest["revision"],
            reason=f"{type(exc).__name__}: {exc}", stage=last_stage,
        )


def run_campaign(
    sessions_root: str | Path, batch_id: str, *, max_jobs: int = 25,
    on_stage: Callable[[str], None] | None = None,
    processor: Callable[..., batch_science.ScienceOutcome] | None = None,
) -> dict[str, Any]:
    """Run pending jobs sequentially until a review gate, existing run or job limit.

    Failures are visible in the persisted manifest and do not abort unrelated
    later blocks; scientific holds do stop the campaign pending human action.
    """
    if type(max_jobs) is not int or not 1 <= max_jobs <= 100:
        raise ValueError("max_jobs must be from 1 to 100")
    for _ in range(max_jobs):
        current = batch_queue.load_batch(sessions_root, batch_id)
        if any(item["status"] in ("running", "needs_review") for item in current["jobs"]):
            return current
        if not any(item["status"] == "pending" for item in current["jobs"]):
            return current
        current = run_next(sessions_root, batch_id, on_stage=on_stage, processor=processor)
        if current is None:
            break
    return batch_queue.load_batch(sessions_root, batch_id)
