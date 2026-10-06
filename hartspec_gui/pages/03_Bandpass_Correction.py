# 03_Bandpass_Correction.py — FR-04: explicit bandpass correction workflow.
#
# --------------------------------------------------------------------------
# FR-19 SESSION-REPLAY REVISION (this revision)
# --------------------------------------------------------------------------
# Confirmed via NotebookLM against Technical Specifications §3.5.3 and §5.4,
# and Functional Specifications §3.2.1: FR-19 "Load Session" is a
# parameter-restoration + deterministic-re-execution design, not a binary
# state snapshot. The session JSON never stores computed spectrum arrays
# (Vlsr/LCP/RCP) -- only stage parameters (here: `mode`). Loading a session
# is expected to "pre-fill every prior pipeline stage with its saved
# parameters" and replay them, relying on NFR-05's six-significant-figure
# determinism guarantee to reproduce identical array output.
#
# Before this revision, Page 03 honored the *storage* half of that contract
# (pipeline_data[PAGE_STAGE_KEY] already held "mode") but not the *replay*
# half: after Load Session, `completed_stages` and `pipeline_data` would
# already show this stage as done, but `bandpass_display_result` (in-memory
# only, by design -- see `_commit_result`'s own comment) would be empty, so
# the page fell through to "Choose the switching mode, then click Apply
# Bandpass Correction to run FR-04" as if nothing had ever been saved. The
# user had to notice this mismatch and manually re-click Apply -- not
# actual session replay.
#
# `_auto_replay_if_needed()` below closes that gap: if this stage is marked
# complete but its in-memory result is missing or belongs to a different
# mode than the one saved in pipeline_data, it re-runs
# `build_bandpass_result()` with the saved mode automatically, using the
# exact same commit path (`_commit_result`) the "Apply" button already
# uses -- so replay can't behave differently than a manual click would.
# --------------------------------------------------------------------------

# Postpone evaluation of type annotations so type hints do not interfere with runtime imports.
from __future__ import annotations

# These typing helpers describe the spectrum dictionaries passed between pipeline stages.
from typing import Any, Mapping

# NumPy is used to validate and compare spectrum arrays.
import numpy as np
# Astropy is used only to read the POSITION keyword directly from the second FITS file when the loaded spectrum
# dictionary does not contain it.
from astropy.io import fits
# Plotly renders the interactive before/after spectrum chart required by FR-04.
import plotly.graph_objects as go
# Streamlit provides the page widgets, session state, navigation, and messages.
import streamlit as st

# Shared project utilities keep FITS paths, session persistence, sidebar state, and styling consistent with the other
# pages.
from utils import baseline_editor_bridge, fits_ingest, session_store, sidebar, styles
from utils.stage_invalidation import invalidate_baseline_dependents
from utils.bandpass_correction_logic import (
    MODE_OPTIONS,
    THIS_STAGE_KEY,
    build_bandpass_result,
    stage_summary,
)

# These constants identify this page inside the eight-stage pipeline and keep stage keys consistent across pages.
PAGE_STAGE_KEY = THIS_STAGE_KEY
CURRENT_STAGE = 3
PAGE_TITLE = "Bandpass Correction"
PAGE_SUBTITLE = "FR-04 — mode selector + before/after spectrum overlay"
UPSTREAM_STAGE_KEYS = ("01_source_browser", "file_loader")
DOWNSTREAM_STAGE_KEYS = ("04_baseline_editor",)
_REQUIRED_ARRAY_KEYS = ("Vlsr", "LCP", "RCP")

# Configure the Streamlit page before rendering any other Streamlit components.
st.set_page_config(
    page_title="HARTSPEC — Bandpass Correction",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize the shared session schema, draw the common sidebar, and apply the project-wide visual styling.
session_store.init_session_state()
sidebar.render_sidebar(current_stage=CURRENT_STAGE)
styles.inject_base_css()


# Count completed stages before Page 03 so the shared progress header does not count the current stage prematurely.
def _completed_upstream_count() -> int:
    completed = st.session_state["completed_stages"]
    return sum(key in completed for key in UPSTREAM_STAGE_KEYS)


# Check that Source Browser and File Loader are complete before allowing any bandpass work.
def _upstream_complete() -> bool:
    completed = st.session_state["completed_stages"]
    return all(key in completed for key in UPSTREAM_STAGE_KEYS)


# Return the filenames Page 02 was asked to load, preserving the same order Page 02 used.
def _target_filenames() -> list[str]:
    pipeline_selection = st.session_state.get("pipeline_data", {}).get("01_source_browser", {})
    selected_files = pipeline_selection.get("selected_files") or []
    if selected_files:
        return [str(filename) for filename in selected_files]

    fallback_files = st.session_state.get("file_loader_target_filenames") or []
    return [str(filename) for filename in fallback_files]


# Read the two CLC metadata fields used to distinguish pointing scans from full integrations and to identify the
# switching mode.
def _read_observation_metadata(filename: str) -> tuple[int | None, str]:
    try:
        path = fits_ingest.get_archive_root() / filename
        with fits.open(path) as hdul:
            sp_point_raw = hdul[0].header.get("SPPOINT") if len(hdul) > 0 else None
            position_raw = hdul[2].header.get("POSITION") if len(hdul) > 2 else None

        try:
            sp_point = int(sp_point_raw) if sp_point_raw is not None else None
        except (TypeError, ValueError):
            sp_point = None

        position = str(position_raw).strip().upper() if position_raw is not None else ""
        return sp_point, position
    except (OSError, ValueError, IndexError, KeyError):
        return None, ""


# Rebuild Page 02's successful filename-to-spectrum handoff so Page 03 can associate each spectrum with its FITS
# metadata.
def _successful_loaded_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    for filename in _target_filenames():
        ingest_result = st.session_state.get(f"file_loader_ingest_result::{filename}")
        if ingest_result is None or not getattr(ingest_result, "ok", False):
            continue

        spectrum = getattr(ingest_result, "spectrum", None)
        if spectrum is None:
            continue

        sp_point, position = _read_observation_metadata(filename)
        entries.append(
            {
                "filename": filename,
                "spectrum": spectrum,
                "sp_point": sp_point,
                "position": position,
            }
        )

    return entries


# Detect the first full-integration pair using the same SPPOINT ordering rule as the original HartSpec workflow.
def _detect_bandpass_pair() -> tuple[dict[str, Any], dict[str, Any]] | None:
    entries = _successful_loaded_entries()

    # The original CLC builds full_int_on from files where SPPOINT == 0 and
    # pairs those indices in observation order: [0,1], [2,3], ... .
    full_integrations = [entry for entry in entries if entry["sp_point"] == 0]

    if len(full_integrations) < 2:
        return None

    return full_integrations[0], full_integrations[1]


# Suggest the switching mode from the second member of the detected full-integration pair, matching the original CLC
# convention.
def _suggest_mode_from_metadata(pair2: Mapping[str, Any]) -> tuple[str, str]:
    position = str(pair2.get("position", "")).strip().upper()

    if position == "ON":
        return "Frequency Switch", "second full-integration file POSITION = ON"
    if position == "OFF":
        return "Position Switch", "second full-integration file POSITION = OFF"

    return "Unknown", "second full-integration file POSITION metadata is unavailable or unrecognised"


# Show which full-integration pair Page 03 detected and the switching mode suggested by the second file's metadata.
def _render_detected_pair_info(pair: tuple[dict[str, Any], dict[str, Any]]) -> None:
    first, second = pair
    suggested_mode, reason = _suggest_mode_from_metadata(second)

    st.info(
        f"Pair detected: {first['filename']} + {second['filename']}\n\n"
        f"Suggested mode from metadata: **{suggested_mode}** ({reason})."
    )


# Convert a spectrum handoff into validated one-dimensional numeric arrays that downstream code can safely use.
def _normalise_spectrum(spectrum: Mapping[str, Any], label: str) -> dict[str, np.ndarray]:
    arrays: dict[str, np.ndarray] = {}
    for key in _REQUIRED_ARRAY_KEYS:
        if key not in spectrum:
            raise ValueError(f"{label} is missing required field: {key}.")
        try:
            arr = np.asarray(spectrum[key], dtype=float).reshape(-1)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} field {key} is not numeric.") from exc
        if arr.size == 0:
            raise ValueError(f"{label} contains no {key} channels.")
        if not np.all(np.isfinite(arr)):
            raise ValueError(f"{label} field {key} contains NaN or infinite values.")
        arrays[key] = arr.copy()

    sizes = {key: arr.size for key, arr in arrays.items()}
    if len(set(sizes.values())) != 1:
        raise ValueError(
            f"{label} arrays have inconsistent lengths: "
            + ", ".join(f"{key}={size}" for key, size in sizes.items())
        )
    return arrays


# Compare only the scientific Vlsr/LCP/RCP arrays to determine whether the Page 03 output actually changed.
def _spectra_equal(left: Mapping[str, Any] | None, right: Mapping[str, Any]) -> bool:
    if not left:
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


# Clear Page 03 and Page 04 results when the current bandpass state is no longer valid.
def _clear_stage3_and_downstream() -> None:
    st.session_state["completed_stages"].discard(PAGE_STAGE_KEY)
    st.session_state["pipeline_data"].pop(PAGE_STAGE_KEY, None)
    st.session_state.pop("bandpass_corrected_spectrum", None)
    st.session_state.pop("bandpass_display_result", None)
    for key in DOWNSTREAM_STAGE_KEYS:
        st.session_state["completed_stages"].discard(key)
        st.session_state["pipeline_data"].pop(key, None)
    st.session_state.pop("baseline_corrected_spectrum", None)
    # Also clear the on-disk Page 4 bridge file, not just in-memory state --
    # see baseline_editor_bridge.clear_bridge()'s own docstring for why this
    # was a real staleness gap otherwise (Pages 7/8 read the bridge file
    # directly and don't check spectrum_fingerprint themselves).
    baseline_editor_bridge.clear_bridge(st.session_state["session_id"])
    # And everything derived from that baseline further downstream
    # (calibrated spectrum, saved fit, export marker) -- see
    # utils/stage_invalidation.py.
    invalidate_baseline_dependents(st.session_state)


# Invalidate an already-applied result when the user switches mode and has not applied the new choice yet.
def _on_mode_change() -> None:
    """A mode choice is only a pending parameter until Apply is clicked."""
    previously_applied = st.session_state.get("bandpass_applied_mode")
    selected = st.session_state.get("bandpass_mode")
    if previously_applied and selected != previously_applied:
        _clear_stage3_and_downstream()


# Save a successful correction into session state, update the JSON-safe stage summary, and invalidate stale downstream
# output.
def _commit_result(mode: str, result: Mapping[str, Any]) -> None:
    corrected = _normalise_spectrum(result["corrected"], "Bandpass-corrected spectrum")
    previous = st.session_state.get("bandpass_corrected_spectrum")

    if previous is not None and not _spectra_equal(previous, corrected):
        for key in DOWNSTREAM_STAGE_KEYS:
            st.session_state["completed_stages"].discard(key)
            st.session_state["pipeline_data"].pop(key, None)
        st.session_state.pop("baseline_corrected_spectrum", None)
        baseline_editor_bridge.clear_bridge(st.session_state["session_id"])
        invalidate_baseline_dependents(st.session_state)
        session_store.log_event(
            "Bandpass output changed — Baseline Block Editor state invalidated"
        )

    # Full arrays remain in memory for Page 04; only lightweight metadata is
    # placed in pipeline_data so session JSON remains serializable. This is
    # by design, confirmed against Technical Specifications §3.5.3 -- see
    # this module's header comment. It's also exactly why
    # `_auto_replay_if_needed()` exists below: the metadata survives a
    # save/load round trip, the arrays don't, and FR-19 defines the fix as
    # "re-run from the saved metadata", not "also serialize the arrays".
    st.session_state["bandpass_corrected_spectrum"] = corrected
    st.session_state["bandpass_display_result"] = {
        "mode": mode,
        "raw_spec1": _normalise_spectrum(result["raw_spec1"], "Input spectrum 1"),
        "raw_spec2": _normalise_spectrum(result["raw_spec2"], "Input spectrum 2"),
        "corrected": corrected,
        "common_velocity_range_kms": list(result.get("common_velocity_range_kms") or []),
    }
    st.session_state["bandpass_applied_mode"] = mode
    st.session_state["pipeline_data"][PAGE_STAGE_KEY] = stage_summary(mode, corrected)
    st.session_state["pipeline_data"][PAGE_STAGE_KEY]["common_velocity_range_kms"] = list(
        result.get("common_velocity_range_kms") or []
    )
    session_store.mark_stage_complete(PAGE_STAGE_KEY)
    session_store.log_event(
        f"Bandpass correction applied — {mode} ({corrected['Vlsr'].size} channels)"
    )


# FR-19 session replay (see this module's header comment for the confirmed
# spec basis). Runs on every page load; it's a no-op unless the saved
# parameters and the current in-memory result have actually diverged, so
# it's safe to call unconditionally rather than gating it behind a "was
# this a Load Session click" flag.
def _auto_replay_if_needed() -> None:
    """Reproduce a saved bandpass result from `pipeline_data` alone.

    Fires when this stage is recorded as complete (e.g. because
    `session_store.load_session()` just restored a saved
    `completed_stages` set) but the in-memory `bandpass_display_result` is
    either missing entirely (a brand-new browser session that loaded
    straight into a saved session) or belongs to a different mode than the
    one actually saved (a stale in-memory result left over from something
    else in the same browser tab). In either case this re-runs the exact
    same `build_bandpass_result` / `_commit_result` path the "Apply"
    button uses, seeded from the saved mode, instead of leaving the page
    showing "choose a mode" underneath a progress bar that already claims
    this stage is done.

    Deliberately does NOT run when the stage was never completed (a
    genuinely fresh session) -- in that case `pipeline_data` has no saved
    mode to replay from, and the normal "pick a mode, click Apply" flow is
    correct, unchanged behavior.
    """
    completed = st.session_state["completed_stages"]
    if PAGE_STAGE_KEY not in completed:
        return  # nothing was ever saved as complete for this stage

    saved_mode = st.session_state["pipeline_data"].get(PAGE_STAGE_KEY, {}).get("mode")
    if saved_mode not in MODE_OPTIONS:
        return  # no valid saved parameter to replay from -- let the normal button flow handle it

    stored_result = st.session_state.get("bandpass_display_result")
    applied_mode = st.session_state.get("bandpass_applied_mode")
    if stored_result is not None and applied_mode == saved_mode:
        return  # already reflects the saved parameters -- nothing to replay

    st.session_state["bandpass_mode"] = saved_mode
    try:
        result = build_bandpass_result(saved_mode)
        _commit_result(saved_mode, result)
        session_store.log_event(
            f"Bandpass correction replayed from saved session — {saved_mode}"
        )
    except (ValueError, TypeError, KeyError) as exc:
        _clear_stage3_and_downstream()
        st.error(f"Could not replay saved bandpass correction: {exc}")


# Add one consistently formatted spectrum line to the Plotly figure.
def _add_trace(fig: go.Figure, x, y, name: str, color: str, dash: str, opacity: float) -> None:
    fig.add_scatter(
        x=x,
        y=y,
        mode="lines",
        name=name,
        line=dict(color=color, width=1.5, dash=dash),
        opacity=opacity,
        hovertemplate=f"{name}<br>Vlsr=%{{x:.2f}} km/s<br>T=%{{y:.3f}} K<extra></extra>",
    )


# Render the FR-04 before/after overlay and visually mark the common velocity range shared by the pair.
def _render_before_after(result: Mapping[str, Any]) -> None:
    theme = styles.get_theme()
    raw1 = result["raw_spec1"]
    corrected = result["corrected"]
    common_range = result.get("common_velocity_range_kms") or []

    with st.container(border=True):
        st.markdown(
            '<div class="hs-panel-title">Before / after bandpass correction</div>',
            unsafe_allow_html=True,
        )
        fig = go.Figure()

        # "Before" is the first member of the selected switching pair. The
        # second raw spectrum is the reference used by the correction and is
        # available in state, while the chart remains readable with four traces.
        _add_trace(fig, raw1["Vlsr"], raw1["LCP"], "Before LCP", styles.LCP_COLOR, "dot", 0.48)
        _add_trace(fig, raw1["Vlsr"], raw1["RCP"], "Before RCP", styles.RCP_COLOR, "dot", 0.48)
        _add_trace(fig, corrected["Vlsr"], corrected["LCP"], "After LCP", styles.LCP_COLOR, "solid", 1.0)
        _add_trace(fig, corrected["Vlsr"], corrected["RCP"], "After RCP", styles.RCP_COLOR, "solid", 1.0)

        if len(common_range) == 2:
            fig.add_vrect(
                x0=common_range[0],
                x1=common_range[1],
                fillcolor=theme["accent"],
                opacity=0.08,
                line_width=0,
                annotation_text="Common velocity range",
                annotation_position="top left",
            )

        fig.update_layout(**styles.plotly_layout_theme(theme))
        fig.update_layout(
            paper_bgcolor=theme["bg-panel"],
            plot_bgcolor=theme["bg-panel"],
            height=430,
            margin=dict(l=52, r=18, t=24, b=44),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            xaxis=dict(
                title="Vlsr (km/s)",
                showgrid=False,
                zeroline=False,
                showline=True,
                linecolor=theme["border-subtle"],
                color=theme["text-muted"],
            ),
            yaxis=dict(
                title="Temperature (K)",
                showgrid=False,
                zeroline=False,
                showline=True,
                linecolor=theme["border-subtle"],
                color=theme["text-muted"],
            ),
            font=dict(
                family="Inter, -apple-system, 'Segoe UI', sans-serif",
                size=11,
                color=theme["text-body"],
            ),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": True}, theme = None)

        if len(common_range) == 2:
            st.caption(
                f"Common velocity range: {common_range[0]:.3f} to {common_range[1]:.3f} km/s"
            )


# Render the Streamlit page after all helper functions have been defined.

# Keep the selected mode stable across Streamlit reruns, defaulting to frequency switching for a new session.
st.session_state.setdefault("bandpass_mode", MODE_OPTIONS[0])

# Draw the common page heading and show progress based only on the two required upstream stages.
styles.render_page_header(
    title=PAGE_TITLE,
    subtitle=PAGE_SUBTITLE,
    current_stage=CURRENT_STAGE,
    completed_stages=_completed_upstream_count(),
)

# Stop early if the user reached Page 03 before completing the required ingestion stages.
if not _upstream_complete():
    missing = [key for key in UPSTREAM_STAGE_KEYS if key not in st.session_state["completed_stages"]]
    _clear_stage3_and_downstream()
    st.error(
        "Bandpass correction requires Source Browser and File Loader to be completed first. "
        f"Missing stage keys: {', '.join(missing)}."
    )
    if st.button("Return to File Loader", key="bandpass_return_loader"):
        st.switch_page("pages/02_File_Loader.py")
    st.stop()

# Page 02 stores every successfully ingested spectrum here; FR-04 needs at least one valid switching pair.
loaded_spectra = st.session_state.get("loaded_spectra") or []
if len(loaded_spectra) < 2:
    _clear_stage3_and_downstream()
    st.error(
        "Bandpass correction requires at least two successfully loaded FITS spectra. "
        "Return to Page 02 and load a compatible switching pair."
    )
    if st.button("Return to File Loader", key="bandpass_return_loader_pair"):
        st.switch_page("pages/02_File_Loader.py")
    st.stop()

# FR-19 session replay -- see _auto_replay_if_needed's own docstring and
# this module's header comment. Must run after the loaded_spectra check
# above (replay needs the same spectra Page 02 already re-derived on this
# rerun) and before the manual mode/Apply controls below, so a replayed
# result renders immediately instead of behind an extra click.
_auto_replay_if_needed()
# Detect the first full-integration pair using SPPOINT == 0, exactly as the original CLC groups science integrations.
detected_pair = _detect_bandpass_pair()
if detected_pair is None:
    _clear_stage3_and_downstream()
    st.error(
        "No complete bandpass pair could be detected. Page 03 needs at least two "
        "successfully loaded FITS files with SPPOINT = 0 in the same observation set."
    )
    if st.button("Return to File Loader", key="bandpass_return_loader_no_pair"):
        st.switch_page("pages/02_File_Loader.py")
    st.stop()

_render_detected_pair_info(detected_pair)

# Keep the exact two spectra used for the detected pair so Apply operates on the same files shown above.
detected_pair_spectra = [detected_pair[0]["spectrum"], detected_pair[1]["spectrum"]]

# Let the user explicitly choose the scientific switching mode required by FR-04.
st.markdown('<div class="hs-eyebrow">Bandpass mode</div>', unsafe_allow_html=True)
st.radio(
    "Bandpass mode",
    options=MODE_OPTIONS,
    horizontal=True,
    key="bandpass_mode",
    label_visibility="collapsed",
    on_change=_on_mode_change,
)

# The correction is deliberately run only after this explicit action, rather than automatically on every rerun.
apply_clicked = st.button(
    "Apply Bandpass Correction",
    type="primary",
    key="apply_bandpass_correction",
)

# Run the correction, commit it only if successful, and leave the stage incomplete if validation fails.
if apply_clicked:
    try:
        result = build_bandpass_result(st.session_state["bandpass_mode"], detected_pair_spectra)
        _commit_result(st.session_state["bandpass_mode"], result)
        st.success("Bandpass correction applied successfully.")
    except (ValueError, TypeError, KeyError) as exc:
        _clear_stage3_and_downstream()
        st.error(f"Bandpass correction failed: {exc}")

# Reuse the last successfully applied result for display without recomputing it during unrelated Streamlit reruns.
stored_result = st.session_state.get("bandpass_display_result")
applied_mode = st.session_state.get("bandpass_applied_mode")

# Show a committed result only when it belongs to the mode currently selected in the UI.
if stored_result and applied_mode == st.session_state["bandpass_mode"]:
    _render_before_after(stored_result)

    st.session_state["pipeline_data"][PAGE_STAGE_KEY] = stage_summary(
        applied_mode,
        stored_result["corrected"],
    )
    st.session_state["pipeline_data"][PAGE_STAGE_KEY]["common_velocity_range_kms"] = list(
        stored_result.get("common_velocity_range_kms") or []
    )
    session_store.mark_stage_complete(PAGE_STAGE_KEY)

    if st.button("Continue to Baseline Block Editor →", key="continue_to_baseline"):
        st.switch_page("pages/04_Baseline_Editor.py")
else:
    st.info("Choose the switching mode, then click Apply Bandpass Correction to run FR-04.")
