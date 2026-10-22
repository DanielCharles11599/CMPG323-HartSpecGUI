# batch_processing_ui.py — FR-21: pinned reference settings, run controls, per-job review and outputs.
"""Streamlit FR-21 widgets; the state machine and scientific work live in utils/."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import streamlit as st

from utils import batch_observations, batch_queue, batch_runner, batch_science, batch_template

STAGES = ("01_source_browser", "02_file_loader", "03_bandpass_correction", "04_baseline_editor",
          "05_calibration_dashboard", "06_pointing_correction", "07_spectral_fitting", "08_export_and_session")


def _rerun() -> None:
    """Repaint the queue from disk after a state transition (Streamlit 1.32)."""
    st.rerun()


def _review_charts(review: Mapping[str, Any]) -> None:
    """Plot actual downsampled spectra so approval is more than a blind button."""
    import plotly.graph_objects as go

    if review.get("type") == "baseline":
        corrected, flattened = review["corrected"], review["flattened"]
        figure = go.Figure()
        for pol, color in (("LCP", "#1F77B4"), ("RCP", "#FF7F0E")):
            figure.add_scatter(x=corrected["Vlsr"], y=corrected[pol], name=f"{pol} corrected",
                               mode="lines", line={"color": color})
            figure.add_scatter(x=flattened["Vlsr"], y=flattened[pol], name=f"{pol} baseline-subtracted",
                               mode="lines", line={"color": color, "dash": "dash"})
        for interval in review["blocks"]:
            figure.add_vrect(x0=interval["start"], x1=interval["end"],
                             opacity=0.12, fillcolor="#587BBD", line_width=0)
        figure.update_layout(xaxis_title="Vlsr (km/s)", yaxis_title="Uncalibrated intensity (K)", height=330)
        st.plotly_chart(figure, use_container_width=True)
        st.caption(f"Polynomial orders: {review['orders']}; chi-squared: {review['chi_squared']}")
    elif review.get("type") == "pointing":
        figure = go.Figure()
        for role, spec in review.get("scans", {}).items():
            figure.add_scatter(x=spec["Vlsr"], y=spec["average"], name=role, mode="lines")
        figure.update_layout(xaxis_title="Vlsr (km/s)", yaxis_title="Pointing amplitude", height=330)
        st.plotly_chart(figure, use_container_width=True)


def _review_controls(manifest: Mapping[str, Any], job: Mapping[str, Any], sessions_root: Path) -> None:
    review = job["review"]
    with st.expander(f"Review required: {batch_observations.job_label(job)} — {review['stage']}", expanded=True):
        st.warning(review.get("reason") or "A scientific review is required.")
        detail = review.get("details") or {}
        if detail.get("verdict"):
            st.caption(f"Measured verdict: {detail['verdict']}. Reasons: {', '.join(detail.get('reasons', []))}")
        prefix = f"fr21_{job['job_id']}"
        st.divider()
        st.caption("To continue with the next observation without approving this one, skip it. "
                   "It will be FAILED, not completed, and its review remains recorded.")
        skip_operator = st.text_input("Skip operator", key=f"{prefix}_skip_operator")
        skip_reason = st.text_area("Reason for skipping this block", key=f"{prefix}_skip_reason")
        if st.button("Skip held block (not approved)", key=f"{prefix}_skip"):
            try:
                batch_queue.skip_held_job(
                    sessions_root, manifest["batch_id"], job["job_id"],
                    expected_revision=manifest["revision"], operator=skip_operator, reason=skip_reason,
                )
            except batch_queue.BatchQueueError as exc:
                st.error(str(exc))
            else:
                st.warning("Block was skipped, not accepted. Remaining blocks may now continue.")
                _rerun()
        signature = review.get("signature")
        if signature:
            preview = batch_science.load_review(sessions_root, manifest["batch_id"], job["job_id"], signature)
            if preview:
                _review_charts(preview)
            else:
                st.error("Matching review visualization is unavailable. Do not approve this block.")
                return
        if not review.get("approvable", True) or not signature:
            st.error("This issue requires corrected data/parameters and a newly prepared queue; "
                     "approval cannot replace missing or ambiguous science.")
            return
        reviewer = st.text_input("Reviewer name", key=f"{prefix}_reviewer")
        pointing_override = (review["stage"] == "06_pointing_correction"
                             and detail.get("verdict") == "No-Go")
        label = ("Pointing No-Go override note" if pointing_override
                 else "Scientific review note (why these regions and orders are appropriate)")
        note = st.text_area(label, key=f"{prefix}_note")
        justification = (st.text_area("Scientific justification for overriding No-Go",
                                      key=f"{prefix}_justification") if pointing_override else "")
        if st.button("Approve reviewed block", key=f"{prefix}_approve"):
            try:
                batch_queue.approve_review(
                    sessions_root, manifest["batch_id"], job["job_id"],
                    expected_revision=manifest["revision"], reviewer=reviewer, note=note,
                    justification=justification,
                )
            except batch_queue.BatchQueueError as exc:
                st.error(str(exc))
            else:
                st.success("Approval saved for this exact scientific result. Continue the queue to recompute it.")
                _rerun()


def _job_actions(manifest: Mapping[str, Any], sessions_root: Path) -> None:
    for job in manifest["jobs"]:
        if job["status"] == "needs_review":
            _review_controls(manifest, job, sessions_root)
        elif job["status"] == "failed":
            st.error(f"{batch_observations.job_label(job)}: {job.get('error') or 'Unknown processing error'}")
            if st.button(f"Retry {job['block_name']}", key=f"fr21_retry_{job['job_id']}"):
                try:
                    batch_queue.retry_job(sessions_root, manifest["batch_id"], job["job_id"],
                                          expected_revision=manifest["revision"])
                except batch_queue.BatchQueueError as exc:
                    st.error(str(exc))
                else:
                    _rerun()
        elif job["status"] == "running":
            st.warning(f"{job['block_name']} is recorded as running. If interrupted, recovery is permitted "
                       "after one hour, then the block must be explicitly retried.")
            if st.button("Recover interrupted block", key=f"fr21_recover_{job['job_id']}"):
                try:
                    batch_queue.mark_interrupted_job(sessions_root, manifest["batch_id"], job["job_id"],
                                                     expected_revision=manifest["revision"])
                except (batch_queue.BatchQueueError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    _rerun()
        elif job["status"] == "completed":
            folder = batch_science.job_directory(sessions_root, manifest["batch_id"], job["job_id"])
            with st.expander(f"Completed: {batch_observations.job_label(job)} — results"):
                st.caption(f"Independent reduction session: {job.get('session_id')}")
                saved_session = folder / "session.json"
                if saved_session.is_file() and st.button(
                    "Replay this observation in the normal pipeline",
                    key=f"fr21_replay_{job['job_id']}",
                ):
                    try:
                        from utils import fits_ingest, session_store
                        if not batch_science.replay_paths_match(job, fits_ingest.get_archive_root()):
                            raise ValueError("The current FITS archive root does not match this batch's input "
                                             "paths. Restore the original archive configuration before replay.")
                        # The existing FR-19 loader rebuilds science from raw FITS; no batch arrays
                        # or historical review signatures are injected into the active pipeline.
                        session_store.load_session(saved_session)
                    except (OSError, ValueError, UnicodeError) as exc:
                        st.error(f"Cannot load batch reduction into the pipeline: {exc}")
                for name in job.get("output_files") or []:
                    path = folder / name
                    if path.is_file() and path.stat().st_size <= 25 * 1024 * 1024:
                        st.download_button(
                            f"Download {name}", data=path.read_bytes(), file_name=f"{job['job_id'][:8]}_{name}",
                            key=f"fr21_download_{job['job_id']}_{name}",
                        )
                    elif path.is_file():
                        st.caption(f"{name} saved at {path} (too large for browser download).")
                    else:
                        st.error(f"Result file missing: {name}. The saved job needs investigation.")


def _planning_controls(manifest: Mapping[str, Any], sessions_root: Path) -> None:
    """Split complex File_check blocks before settings are pinned, with explicit scan assignments."""
    batch_id = manifest["batch_id"]
    candidates = [job for job in manifest["jobs"]
                  if job["status"] == "pending" and not job.get("pair_assignment")]
    if not candidates:
        return
    with st.expander("Multi-pair / multi-scan observation blocks — inspect and assign", expanded=False):
        st.caption("Inspect a block if it contains several full-integration pairs or pointing scans. "
                   "Each pair becomes an independent queue job and requires its own baseline and pointing review.")
        selected = st.selectbox("Block to inspect", candidates,
                                format_func=lambda item: item["block_name"], key=f"fr21_plan_job_{batch_id}")
        state_key = f"fr21_inspection_{batch_id}"
        if st.button("Inspect integration pairs and pointing scans", key=f"fr21_inspect_{batch_id}"):
            try:
                with st.spinner("Reading FITS headers and detecting complete pointing scans…"):
                    st.session_state[state_key] = batch_observations.inspect_observation_job(selected)
            except (batch_queue.BatchQueueError, OSError, ValueError) as exc:
                st.session_state.pop(state_key, None)
                st.error(f"Cannot inspect observation block: {exc}")
        inspection = st.session_state.get(state_key)
        if not inspection or inspection.get("job_id") != selected["job_id"]:
            return
        pairs, scans = inspection["pairs"], inspection["scans"]
        st.caption(f"Found {len(pairs)} full-integration pair(s) and {len(scans)} complete pointing scan(s).")
        if len(pairs) == len(scans) == 1:
            st.info("This block is already a simple pair/scan; no split is required.")
            return
        choices: dict[str, str] = {}
        selected_scans = []
        for pair in pairs:
            compatible = [scan for scan in scans if scan["reference_position"] == (
                "ON" if pair["mode"] == "Frequency Switch" else "OFF")]
            st.caption(f"Pair {pair['number']}: {', '.join(pair['files'])} ({pair['mode']})")
            options = ["Select a scan…"] + [scan["key"] for scan in compatible]
            chosen = st.selectbox(f"Pointing scan for pair {pair['number']}", options=options,
                                  key=f"fr21_scan_{batch_id}_{selected['job_id']}_{pair['number']}")
            if chosen != options[0]:
                choices[str(pair["number"])] = chosen
                selected_scans.append(chosen)
        repeated = len(set(selected_scans)) != len(selected_scans)
        unused = bool(set(scan["key"] for scan in scans) - set(selected_scans))
        shared_ok = (st.checkbox("I acknowledge sharing the same pointing scan between integration pairs",
                                 key=f"fr21_share_{selected['job_id']}") if repeated else False)
        unused_ok = (st.checkbox("I acknowledge that some complete pointing scans will not be used",
                                 key=f"fr21_unused_{selected['job_id']}") if unused else False)
        operator = st.text_input("Operator name (scan assignments)", key=f"fr21_plan_operator_{selected['job_id']}")
        note = st.text_area("Scientific explanation for assigning these scans",
                            key=f"fr21_plan_note_{selected['job_id']}")
        if st.button("Split block into separately reviewed pair jobs", key=f"fr21_split_{selected['job_id']}"):
            try:
                batch_observations.split_observation_job(
                    sessions_root, batch_id, selected["job_id"], expected_revision=manifest["revision"],
                    inspection_signature=inspection["signature"], assignments=choices,
                    operator=operator, note=note, acknowledge_shared=shared_ok,
                    acknowledge_unused=unused_ok,
                )
            except (batch_queue.BatchQueueError, OSError, ValueError) as exc:
                st.error(f"Cannot expand observation block: {exc}")
            else:
                st.session_state.pop(state_key, None)
                st.success("Each integration pair now has its own isolated review gates and outputs.")
                _rerun()


def render_processing_controls(manifest: Mapping[str, Any], *, sessions_root: Path) -> None:
    """Pin a reference session, execute the next jobs, inspect holds and download results."""
    batch_id = manifest["batch_id"]
    if not manifest["processing_enabled"]:
        _planning_controls(manifest, sessions_root)
        st.markdown("**Saved reference session**")
        st.caption("Select a completed saved manual session for the same source and frequency. "
                   "Only parameters are copied; calibration/pointing results and previous approval are not.")
        candidates = sorted(
            (path for path in sessions_root.glob("*.json") if "." not in path.stem),
            key=lambda path: path.stat().st_mtime, reverse=True,
        ) if sessions_root.exists() else []
        if not candidates:
            st.info("No manual session JSON files found. Complete and save a normal reduction first.")
            return
        selection = st.selectbox("Reference session", options=candidates, format_func=lambda path: path.name,
                                 key=f"fr21_reference_{batch_id}")
        if st.button("Activate queue with saved settings", key=f"fr21_pin_{batch_id}"):
            try:
                frozen = batch_template.load_template(
                    selection, sessions_root, source=manifest["source_name"],
                    frequency=manifest["frequency_mhz"],
                )
                batch_queue.pin_batch_template(sessions_root, batch_id, frozen,
                                               expected_revision=manifest["revision"])
            except (batch_queue.BatchQueueError, OSError) as exc:
                st.error(f"Cannot activate batch: {exc}")
            else:
                st.success("Reference settings pinned. Ready to process validated observation blocks.")
                _rerun()
        return

    st.caption(f"Frozen reference: {manifest.get('template_session_id', 'unknown')}; "
               "FITS results, calibrations and sign-offs are recomputed for every job.")
    if not any(job["status"] in {"running", "needs_review"} for job in manifest["jobs"]):
        if any(job["status"] == "pending" for job in manifest["jobs"]):
            if st.button("Run sequential batch until next review", key=f"fr21_run_{batch_id}"):
                placeholder = st.empty()
                try:
                    with st.spinner("Processing one observation at a time…"):
                        def on_stage(stage: str) -> None:
                            index = STAGES.index(stage) + 1 if stage in STAGES else 1
                            placeholder.progress(index / len(STAGES), text=f"Current block — {stage}")
                        batch_runner.run_campaign(sessions_root, batch_id, on_stage=on_stage)
                except batch_queue.BatchQueueError as exc:
                    st.error(f"Cannot continue queue: {exc}")
                else:
                    _rerun()
        else:
            st.caption("No pending jobs remain. Failed blocks may be retried; invalid blocks need a new source queue.")
    _job_actions(manifest, sessions_root)
