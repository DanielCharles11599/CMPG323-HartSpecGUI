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
from utils.baseline_editor_bridge import (
    initialize_bridge,
    read_bridge,
    spectrum_fingerprint,
)
from utils.baseline_editor_logic import THIS_STAGE_KEY, stage_payload
from utils.stage_invalidation import invalidate_baseline_dependents

CURRENT_STAGE = 4
PAGE_STAGE_KEY = THIS_STAGE_KEY
PAGE_TITLE = "Baseline Block Editor"
PAGE_SUBTITLE = "FR-05 / 06 / 07 — select flat baseline regions and compare polynomial fits"
# The revised Dash editor includes numeric range controls and an editable table,
# so it needs more vertical room than the original drag-only mock-up.
IFRAME_HEIGHT = 1050
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
    """Pull the current Dash bridge state into Streamlit session/audit state.

    A stale bridge is ignored when its spectrum fingerprint does not match
    the current Page 3 handoff. This prevents an old baseline fit from being
    re-marked complete after the user changes the bandpass result.
    """
    if not _upstream_complete():
        _clear_page4_completion()
        return

    current_spectrum = st.session_state.get("bandpass_corrected_spectrum")
    if not current_spectrum:
        _clear_page4_completion()
        return

    try:
        current_fingerprint = spectrum_fingerprint(current_spectrum)
    except (KeyError, TypeError, ValueError):
        _clear_page4_completion()
        return

    session_id = st.session_state["session_id"]
    bridge = read_bridge(session_id)
    if not bridge:
        return

    if bridge.get("spectrum_fingerprint") != current_fingerprint:
        _clear_page4_completion()
        return

    # New bridge payloads use ``baseline_regions`` to make the semantics explicit.
    # Fall back to the legacy ``blocks`` key so saved sessions created before this
    # PM revision still replay correctly.
    baseline_regions = bridge.get("baseline_regions", bridge.get("blocks", []))
    payload = stage_payload(
        baseline_regions,
        bridge.get("selection_mode", "Manual ranges"),
        bridge.get("selected_orders"),
        bridge.get("fit_result"),
    )
    # Persist the clarified domain meaning alongside the legacy payload shape.
    # These fields are JSON-safe and make future replay/migrations unambiguous.
    payload["selection_semantics"] = SELECTION_SEMANTICS
    payload["selected_regions_are_masked"] = False
    payload["fit_uses_selected_flat_regions"] = True
    payload["output_preserves_full_velocity_axis"] = True
    st.session_state["pipeline_data"][PAGE_STAGE_KEY] = payload

    flattened = bridge.get("flattened_spectrum")
    if payload["complete"] and flattened:
        previous_flattened = st.session_state.get("baseline_corrected_spectrum")
        if previous_flattened is not None and not _flattened_spectra_equal(previous_flattened, flattened):
            # Page 4 is still complete, but a different block/order selection
            # produced a genuinely different flattened spectrum -- Page 5/7/8
            # derived state (calibrated spectrum, saved fit, export marker)
            # was computed from the old one and is now stale.
            invalidate_baseline_dependents(st.session_state)
            session_store.log_event(
                "Baseline output changed — downstream calibration/fit results invalidated"
            )
        st.session_state["baseline_corrected_spectrum"] = flattened
        session_store.mark_stage_complete(PAGE_STAGE_KEY)
    else:
        st.session_state.pop("baseline_corrected_spectrum", None)
        st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)
        invalidate_baseline_dependents(st.session_state)

    seen_event_ids = set(
        st.session_state.setdefault("baseline_editor_seen_event_ids", [])
    )
    for event in bridge.get("events", []):
        event_id = event.get("id")
        if event_id and event_id not in seen_event_ids:
            session_store.log_event(
                event.get("message", "Baseline editor updated")
            )
            seen_event_ids.add(event_id)
    st.session_state["baseline_editor_seen_event_ids"] = sorted(seen_event_ids)


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
                    color:{theme['text-body']}; font-size:12px; line-height:1.55;">
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
        bandpass_mode=bandpass_mode,
    )

    # start_server() is already a process-level singleton guarded by a lock.
    # Calling it directly avoids Streamlit cache lifecycle warnings while
    # still ensuring only one Dash server is started per process.
    port = start_server()

    # Changing the revision changes the iframe src, forcing Dash's hydrate
    # callback to re-read the bridge instead of leaving an old blank graph.
    revision = (
        f"{bridge['spectrum_fingerprint'][:12]}-"
        f"{styles.get_theme_name()}-flat-regions-v2"
    )
    components.iframe(
        _dash_url(port, st.session_state["session_id"], revision),
        height=IFRAME_HEIGHT,
        scrolling=False,
    )

    # Keep the next pipeline action directly below the embedded editor so the
    # user does not have to return to the sidebar after finishing FR-05/06/07.
    # Clicking the button triggers a normal Streamlit rerun first, which means
    # _sync_dash_state_into_streamlit() at the top of main() has already pulled
    # the latest Dash bridge state before this readiness check is evaluated.
    st.markdown(
        f"<div style='height:{styles.SECTION_GAP}px'></div>",
        unsafe_allow_html=True,
    )

    baseline_ready = (
        PAGE_STAGE_KEY in st.session_state["completed_stages"]
        and st.session_state.get("baseline_corrected_spectrum") is not None
    )

    if st.button(
        "Continue to Calibration Dashboard →",
        type="primary",
        key="continue_to_calibration_dashboard",
    ):
        if baseline_ready:
            st.switch_page("pages/05_Calibration_Dashboard.py")
        else:
            st.warning(
                "Select at least one valid flat baseline region and complete the polynomial fit "
                "before continuing. Start/end values must be within the displayed velocity "
                "range and each start must be smaller than its end."
            )


if __name__ == "__main__":
    main()
