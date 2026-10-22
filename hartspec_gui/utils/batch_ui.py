# batch_ui.py — FR-21: source selection, queue overview and processing panel.
"""Show persisted queue creation, progress and the separate processing controls.

The Source Browser is still Stage 01 of eight. Batch processing is an action
on committed File_check observation blocks, not a ninth pipeline page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

import streamlit as st

from utils import batch_queue, session_store

EDITOR_KEY = "fr21_batch_editor_open"
CURRENT_ID_KEY = "fr21_current_batch_id"


def render_batch_panel(
    selection: Mapping[str, Any], *, source_session_id: str, sessions_root: Path,
    verify_file: Callable[[Path], Any],
) -> None:
    """Create and display queue manifests for the *committed* source selection.

    Args:
        selection: Page 01's committed source metadata, including File_check blocks.
        source_session_id: Owner of those blocks and the pinned source workspace.
        sessions_root: FR-19 configured JSON sessions directory.
        verify_file: The FR-03 FITS integrity checker (read-only).
    """
    if not st.session_state.get(EDITOR_KEY) and not selection.get("batch_queue_id"):
        return

    with st.container(border=True):
        st.markdown('<div class="hs-panel-title">Batch processing</div>', unsafe_allow_html=True)
        if st.session_state.get(EDITOR_KEY):
            available = list(selection.get("observation_blocks") or {})
            if not available or selection.get("file_check_error"):
                st.warning("A batch needs valid File_check observation blocks. Reselect and sort the FITS files.")
            else:
                st.caption("Choose whole observation blocks; File_check's original block and FITS order is retained.")
                chosen = st.multiselect(
                    "Observation blocks", options=available, default=available,
                    key=f"fr21_blocks_{source_session_id}",
                )
                if st.button("Create validated queue", key="fr21_create_queue", disabled=not chosen):
                    try:
                        with st.spinner("Checking the selected FITS files for structural problems…"):
                            manifest = batch_queue.prepare_batch(
                                selection, source_session_id=source_session_id, block_names=chosen,
                                verifier=verify_file,
                            )
                            batch_queue.create_batch(sessions_root, manifest)
                    except (batch_queue.BatchQueueError, OSError) as exc:
                        st.error(f"Could not prepare batch: {exc}")
                    else:
                        st.session_state[CURRENT_ID_KEY] = manifest["batch_id"]
                        st.session_state["pipeline_data"]["01_source_browser"]["batch_queue_id"] = manifest[
                            "batch_id"
                        ]
                        session_store.log_event(
                            f"Batch {manifest['batch_id']} prepared — {len(manifest['jobs'])} block(s)"
                        )
                        session_store.checkpoint_session("Batch queue prepared")
                        st.success("Batch queue saved. Invalid blocks are held and listed below.")
                if st.button("Close batch selection", key="fr21_close_editor"):
                    st.session_state[EDITOR_KEY] = False

        current_id = st.session_state.get(CURRENT_ID_KEY) or selection.get("batch_queue_id")
        if not current_id:
            return
        try:
            manifest = batch_queue.load_batch(sessions_root, current_id)
        except batch_queue.BatchQueueError as exc:
            st.error(f"Could not reload the saved batch: {exc}")
            return
        if manifest.get("source_session_id") != source_session_id:
            st.warning("The displayed batch belongs to a different source reduction; it was not activated.")
            return

        done, total = batch_queue.batch_progress(manifest)
        st.caption(f"Queue {current_id} · {done}/{total} observation jobs completed "
                   "(a multi-pair block can contain several jobs)")
        st.progress(done / total if total else 0.0)
        from utils.batch_observations import job_label
        st.dataframe(
            [{"Block": job_label(job), "FITS files": len(job["inputs"]),
              "Status": job["status"].replace("_", " ").title(),
              "Validation issues": len(job["validation_issues"])} for job in manifest["jobs"]],
            use_container_width=True, hide_index=True,
        )
        for job in manifest["jobs"]:
            if job["validation_issues"]:
                with st.expander(f"{job['block_name']} — {len(job['validation_issues'])} validation issue(s)"):
                    for issue in job["validation_issues"]:
                        st.warning(issue)
        if manifest["discarded_files"]:
            st.warning(
                f"File_check discarded {len(manifest['discarded_files'])} file(s) before queue creation. "
                "Those files were not silently added to a job."
            )
        # FR-21 Pass 2: all actions below use the separately persisted queue,
        # not the active single-observation Streamlit reduction.
        from utils.batch_processing_ui import render_processing_controls
        render_processing_controls(manifest, sessions_root=sessions_root)
