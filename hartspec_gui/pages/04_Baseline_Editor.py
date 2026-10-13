# 04_Baseline_Editor.py — FR-05/06/07: embedded Dash flat-baseline region + polynomial order editor.
#
# PM feedback revision (2026-10): selected ranges are flat, line-free regions used
# to estimate the baseline. They are not exclusion masks and are not removed from
# the spectrum. The fitted baseline is evaluated across the complete velocity axis
# so emission/spiky channels remain available to downstream pipeline stages.
# Exact start/end editing is the primary interaction; chart dragging may remain as
# an optional convenience inside the embedded Dash editor.

from __future__ import annotations

import os
from typing import Any, Mapping
from urllib.parse import urlencode

import numpy as np
import streamlit as st
import streamlit.components.v1 as components

from dash_apps.baseline_editor import start_server
from utils import session_store, sidebar, styles
from utils.baseline_editor_bridge import initialize_bridge
from utils.baseline_editor_logic import THIS_STAGE_KEY
from utils.feature_detection_ui import render_feature_detection
from utils.stage_invalidation import invalidate_baseline_dependents

CURRENT_STAGE = 4
PAGE_STAGE_KEY = THIS_STAGE_KEY
PAGE_TITLE = "Baseline Block Editor"
PAGE_SUBTITLE = "FR-05 / 06 / 07 — select flat baseline regions and compare polynomial fits"
# The Dash content currently ends shortly after the order-selection row. Keeping
# the old 1050 px viewport left a large empty iframe tail (white in dark mode).
# 880 px keeps the complete editor visible while bringing Streamlit actions up.
IFRAME_HEIGHT = 880
SELECTION_SEMANTICS = "flat_baseline_fit_regions_v2"

# Page 4 may only run after the three preceding pipeline stages are complete.
UPSTREAM_STAGE_KEYS = (
    "01_source_browser",
    "file_loader",
    "03_bandpass_correction",
)
_REQUIRED_ARRAY_KEYS = ("Vlsr", "LCP", "RCP")


def _upstream_complete() -> bool:
    """Return True only when Pages 1–3 are all recorded as complete."""
    completed = st.session_state["completed_stages"]
    return all(stage_key in completed for stage_key in UPSTREAM_STAGE_KEYS)


def _completed_upstream_count() -> int:
    """Count only stages strictly before Page 4 for the shared progress bar."""
    completed = st.session_state["completed_stages"]
    return sum(stage_key in completed for stage_key in UPSTREAM_STAGE_KEYS)


def _normalise_handoff_spectrum(spectrum: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """Validate the Page 3 in-memory handoff before mounting Dash."""
    arrays: dict[str, np.ndarray] = {}
    for key in _REQUIRED_ARRAY_KEYS:
        if key not in spectrum:
            raise ValueError(f"Page 3 handoff is missing required field: {key}.")
        try:
            array = np.asarray(spectrum[key], dtype=float).reshape(-1)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Page 3 handoff field {key} is not a numeric array.") from exc
        if array.size == 0:
            raise ValueError(
                "Page 3 handed Page 4 an empty corrected spectrum. "
                "Return to Bandpass Correction and resolve the zero-channel output first."
            )
        arrays[key] = array.copy()

    lengths = {key: arrays[key].size for key in _REQUIRED_ARRAY_KEYS}
    if len(set(lengths.values())) != 1:
        raise ValueError(
            "Page 3 handoff arrays have inconsistent lengths: "
            + ", ".join(f"{key}={size}" for key, size in lengths.items())
        )
    return arrays


def _clear_page4_completion() -> None:
    """Remove stale Page 4 completion/output without altering upstream stages.

    Also invalidates Page 5/7/8's baseline-derived state (calibrated
    spectrum, saved fit, export marker) -- see utils/stage_invalidation.py.
    Previously this only cleared Page 4's own keys, so a user who reached
    Page 5+ before Page 4 became incomplete again (e.g. upstream changed,
    or the spectrum fingerprint no longer matched) could still be looking at
    a calibrated spectrum or saved fit computed from a baseline that no
    longer exists.
    """
    st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)
    st.session_state["pipeline_data"].pop(PAGE_STAGE_KEY, None)
    st.session_state.pop("baseline_corrected_spectrum", None)
    invalidate_baseline_dependents(st.session_state)
    session_store.checkpoint_session("Baseline result invalidated")


def _flattened_spectra_equal(left: Mapping[str, Any] | None, right: Mapping[str, Any] | None) -> bool:
    """Compare two flattened-spectrum dicts for equality, array by array.

    Mirrors 03_Bandpass_Correction.py's own _spectra_equal() -- same
    dict-of-array-likes shape ({"Vlsr": [...], "LCP": [...], "RCP": [...]}),
    same reason for existing (detect a genuine output change vs. an
    identical rerun) -- kept as a page-local copy rather than a shared
    utils function since this task's scope was Pages 3/4/5/6, not
    introducing new shared modules for a two-line comparison.
    """
    if not left or not right:
        return False
    try:
        return all(
            np.array_equal(
                np.asarray(left[key], dtype=float),
                np.asarray(right[key], dtype=float),
                equal_nan=True,
            )
            for key in _REQUIRED_ARRAY_KEYS
        )
    except (KeyError, TypeError, ValueError):
        return False


def _sync_dash_state_into_streamlit() -> None:
    """Synchronize the same bridge parameters used by the global checkpoint path."""
    if not _upstream_complete():
        _clear_page4_completion()
        session_store.checkpoint_session("Baseline upstream inputs unavailable")
        return
    session_store.sync_baseline_state()


def _dash_url(port: int, session_id: str, revision: str) -> str:
    """Return the Dash iframe URL with a revision that forces fresh hydration.

    The revision changes when the Page 3 spectrum or theme changes. Without
    it, Streamlit can reuse the same iframe URL and the Dash app can keep an
    old/empty hydrated state even though the bridge JSON has been refreshed.
    """
    base = os.environ.get("DASH_BRIDGE_URL", f"http://localhost:{port}").rstrip("/")
    query = urlencode(
        {
            "session_id": session_id,
            "rev": revision,
            "selection_semantics": SELECTION_SEMANTICS,
        }
    )
    return f"{base}/?{query}"


def _render_upstream_error(missing_stages: list[str]) -> None:
    """Show a normal Streamlit error rather than mounting an empty editor."""
    missing_text = ", ".join(missing_stages)
    st.error(
        "Baseline editing requires Pages 1–3 to be completed first. "
        f"Missing stage keys: {missing_text}."
    )
    if st.button("Return to Bandpass Correction", key="return_to_bandpass"):
        st.switch_page("pages/03_Bandpass_Correction.py")


def _render_selection_guidance() -> None:
    """Explain the revised baseline-region semantics before the Dash iframe.

    The old wording encouraged users to select noisy/emission channels as ranges
    to exclude. PM feedback reverses that interpretation: users now select the
    flat, line-free channels that are safe inputs to the polynomial fit. The
    fitted baseline is then subtracted from every channel, so spectral features
    outside the selections remain in the downstream spectrum.
    """
    theme = styles.get_theme()
    st.markdown(
        f"""
        <div style="background:{theme['bg-panel']}; border:1px solid {theme['border-default']};
                    border-left:4px solid {theme['accent']}; border-radius:{styles.PANEL_RADIUS}px;
                    padding:12px 14px; margin-bottom:{styles.SECTION_GAP}px;
                    color:{theme['text-body']}; font-size:0.75rem; line-height:1.55;">
          <div style="font-weight:600; margin-bottom:4px;">How to choose baseline regions</div>
          Select only the <strong>flat, line-free</strong> parts of the spectrum. These ranges are
          inputs to the baseline fit; they are <strong>not masked or removed</strong>. Emission and
          spiky channels outside the selected ranges remain on the full velocity axis and continue
          through the pipeline. Enter exact start/end velocities in the editor and adjust them in
          the editable table. Chart dragging is optional.
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    """Render Streamlit Page 4 and mount the Dash baseline editor iframe."""
    st.set_page_config(
        page_title="HARTSPEC — Baseline Block Editor",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    session_store.init_session_state()
    _sync_dash_state_into_streamlit()
    sidebar.render_sidebar(current_stage=CURRENT_STAGE)
    styles.inject_base_css()

    # Page 4 itself remains in-progress in its own header. Once FR-05/06/07
    # is complete, Page 5 will show 4/8 complete.
    styles.render_page_header(
        title=PAGE_TITLE,
        subtitle=PAGE_SUBTITLE,
        current_stage=CURRENT_STAGE,
        completed_stages=_completed_upstream_count(),
    )
    _render_selection_guidance()

    completed = st.session_state["completed_stages"]
    missing_stages = [
        stage_key
        for stage_key in UPSTREAM_STAGE_KEYS
        if stage_key not in completed
    ]
    if missing_stages:
        _clear_page4_completion()
        _render_upstream_error(missing_stages)
        st.stop()

    raw_handoff = st.session_state.get("bandpass_corrected_spectrum")
    if raw_handoff is None:
        _clear_page4_completion()
        st.error(
            "The Page 3 corrected spectrum is not present in this Streamlit session. "
            "Return to Bandpass Correction and let FR-04 run again."
        )
        if st.button("Return to Bandpass Correction", key="restore_bandpass_handoff"):
            st.switch_page("pages/03_Bandpass_Correction.py")
        st.stop()

    try:
        corrected = _normalise_handoff_spectrum(raw_handoff)
    except ValueError as exc:
        _clear_page4_completion()
        st.error(str(exc))
        if st.button("Return to Bandpass Correction", key="repair_bandpass_handoff"):
            st.switch_page("pages/03_Bandpass_Correction.py")
        st.stop()

    bandpass_state = st.session_state["pipeline_data"].get(
        "03_bandpass_correction",
        {},
    )
    bandpass_mode = bandpass_state.get("mode")
    if bandpass_mode not in ("Frequency Switch", "Position Switch"):
        _clear_page4_completion()
        st.error(
            "The Page 3 completion record has no valid bandpass mode. "
            "Return to Bandpass Correction and run FR-04 again."
        )
        st.stop()

    bridge = initialize_bridge(
        session_id=st.session_state["session_id"],
        spectrum=corrected,
        theme=styles.get_theme_name(),
        font_scale=styles.get_font_scale(),
        bandpass_mode=bandpass_mode,
        checkpoint_token=st.session_state.get("checkpoint_token"),
        restored_parameters=st.session_state["pipeline_data"].get(PAGE_STAGE_KEY),
    )
    session_store.checkpoint_session("Baseline editor opened")

    # start_server() is already a process-level singleton guarded by a lock.
    # Calling it directly avoids Streamlit cache lifecycle warnings while
    # still ensuring only one Dash server is started per process.
    port = start_server()

    # Changing the revision changes the iframe src, forcing Dash's hydrate
    # callback to re-read the bridge instead of leaving an old blank graph.
    revision = (
        f"{bridge['spectrum_fingerprint'][:12]}-"
        f"{styles.get_theme_name()}-{styles.get_font_scale()}-flat-regions-v2"
    )
    st.caption(
        "Baseline editor: Tab enters its controls. Use Region to edit and numeric velocities; dragging is optional. "
        "Tab after its last control returns to the page."
    )
    components.iframe(
        _dash_url(port, st.session_state["session_id"], revision),
        height=round(IFRAME_HEIGHT * styles.get_font_scale() / 100),
        scrolling=True,
    )

    # Keep the next pipeline action directly below the embedded editor so the
    # user does not have to return to the sidebar after finishing FR-05/06/07.
    # Clicking the button triggers a normal Streamlit rerun first, which means
    # _sync_dash_state_into_streamlit() at the top of main() has already pulled
    # the latest Dash bridge state before this readiness check is evaluated.
    baseline_ready = (
        PAGE_STAGE_KEY in st.session_state["completed_stages"]
        and st.session_state.get("baseline_corrected_spectrum") is not None
    )

    # Dash writes its bridge independently of Streamlit. Clicking this secondary
    # control triggers a normal Streamlit rerun, so the sync at the top of main()
    # pulls the newest committed blocks/fit before FR-08 is recalculated below.
    st.button("Refresh feature detection from editor", key="refresh_feature_detection")

    feature_detection_ready = False
    if baseline_ready:
        baseline_stage = st.session_state["pipeline_data"].get(PAGE_STAGE_KEY, {})
        blocks = baseline_stage.get("blocks", []) if isinstance(baseline_stage, Mapping) else []
        feature_detection_ready = render_feature_detection(
            st.session_state["baseline_corrected_spectrum"],
            blocks,
        )
    else:
        st.info("Complete the baseline fit above to run FR-08 feature detection.")

    if st.button(
        "Continue to Calibration Dashboard →",
        type="primary",
        key="continue_to_calibration_dashboard",
    ):
        if baseline_ready and feature_detection_ready:
            st.switch_page("pages/05_Calibration_Dashboard.py")
        elif not baseline_ready:
            st.warning(
                "Select at least one valid flat baseline region and complete the polynomial fit "
                "before continuing. Start/end values must be within the displayed velocity "
                "range and each start must be smaller than its end."
            )
        else:
            st.warning("Resolve the FR-08 feature-detection error shown above before continuing.")


if __name__ == "__main__":
    main()
