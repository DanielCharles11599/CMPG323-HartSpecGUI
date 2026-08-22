"""Page 02 — File Loader (FR-02 FITS load + header extraction, FR-03
validation / quarantine).

This is a functional rewrite -- it calls the real clc/load_file.py and
clc/load_file2.py modules via utils/fits_ingest.py rather than simulating
progress with mock data. See utils/fits_ingest.py's module docstring for
the two real integration gaps discovered by testing against an actual
sample file, and how each is handled without modifying clc/:

* clc/load_file.py raises KeyError on files missing a RESTFREQ key in HDU0
  -- surfaced here as an FR-03 validation error, with a raw-header fallback
  so the page still shows what it can.
* clc/load_file2.py's hard-coded DATE-OBS lookup is used as a *probe*: its
  failure mode is itself the "legacy DATE convention" detection FR-02 asks
  for, rather than something to patch.

RA/Dec is not available from either loader on the one real file this was
tested against (only telescope LONGITUD/LATITUDE are present, not source
coordinates) -- shown as "not available" rather than guessed. Flag this to
the team if source RA/Dec needs to come from somewhere else (e.g. a catalog
lookup keyed on OBJECT).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import time

import pandas as pd
import streamlit as st

from utils import fits_ingest, session_store, sidebar, styles

STAGE_NUMBER = 2
STAGE_KEY = "file_loader"

PRIORITY_LABELS = ["Vlsr", "LCP/RCP", "HPBW", "Tsys", "Date", "Object", "RA/Dec", "Focus", "Humidity"]


def _pick_file() -> None:
    """FR-02 file selection.

    Prefers whatever page 01 (Source Browser) put in session state
    (`pipeline_data["selected_fits_path"]`); falls back to a dropdown over
    /data/fits/ so this page is independently testable before page 01 is
    wired up to write that key.

    Uses filenames (not full paths) as the selectbox's option values --
    Streamlit's AppTest harness has a known incompatibility between
    `format_func` and non-string option values where its internal index
    lookup breaks after certain rerun sequences (verified while building
    this page's tests). Filenames as values sidesteps it and is simpler
    besides.
    """
    pipeline_data = st.session_state["pipeline_data"]
    preselected = pipeline_data.get("selected_fits_path")

    available = fits_ingest.list_available_fits()
    if not available:
        st.error(f"No .fits files found directly under {fits_ingest.get_fits_archive_dir()}.")
        st.stop()

    path_by_filename = {p.name: p for p in available}
    filenames = list(path_by_filename.keys())
    preselected_name = preselected.split("/")[-1] if preselected else None
    default_index = filenames.index(preselected_name) if preselected_name in filenames else 0

    chosen_name = st.selectbox(
        "FITS file",
        filenames,
        index=default_index,
        key="file_loader_selected_path",
        label_visibility="collapsed",
    )
    pipeline_data["selected_fits_path"] = str(path_by_filename[chosen_name])


def _render_load_panel() -> fits_ingest.IngestResult:
    """FR-02 load: calls the real ingest wrapper, times the real call."""
    styles.render_panel_open("")
    _pick_file()

    selected_path = st.session_state["pipeline_data"]["selected_fits_path"]

    cache_key = f"file_loader_result::{selected_path}"
    if cache_key not in st.session_state:
        theme = styles.get_theme()
        st.markdown(
            f'<div style="font-size:14px; color:{theme["text-body"]}; margin-top:12px;">'
            f"Loading {selected_path.split('/')[-1]}</div>",
            unsafe_allow_html=True,
        )
        with st.spinner("Extracting FITS header metadata\u2026"):
            start = time.perf_counter()
            result = fits_ingest.ingest_fits(selected_path)
            elapsed = time.perf_counter() - start
        st.session_state[cache_key] = result
        st.session_state[f"{cache_key}::elapsed"] = elapsed
        session_store.log_event(
            f"{result.filename} loaded ({result.status}) in {elapsed:.3f}s"
        )
    else:
        result = st.session_state[cache_key]
        elapsed = st.session_state[f"{cache_key}::elapsed"]

    theme = styles.get_theme()
    st.markdown(
        f'<div style="font-size:11px; color:{theme["text-muted"]}; margin-top:8px;">'
        f"Loaded in {elapsed:.3f}s</div>",
        unsafe_allow_html=True,
    )
    styles.render_panel_close()
    return result


def _render_validation_alerts(result: fits_ingest.IngestResult) -> None:
    """FR-03 validation, using plain Streamlit status blocks (per spec)."""
    if result.status == "error":
        st.error(
            f"**{result.filename}** failed to load via `clc/load_file.py`:\n\n"
            + "\n".join(f"- {issue}" for issue in result.issues)
        )
    elif result.status == "warning":
        st.warning(
            f"**{result.filename}** loaded with warnings:\n\n"
            + "\n".join(f"- {issue}" for issue in result.issues)
        )
    else:
        st.success(f"**{result.filename}** loaded cleanly.")
        if result.date_convention:
            st.caption(f"Date convention: {result.date_convention}")

    if result.status == "error":
        _render_quarantine_control(result)


def _render_quarantine_control(result: fits_ingest.IngestResult) -> None:
    """FR-03 quarantine, as a modal-free confirm block (no st.dialog in
    Streamlit 1.32.0 -- confirmed unavailable, so this uses a bordered
    container + explicit confirm/cancel, matching what the spec itself
    suggested as the fallback pattern)."""
    confirm_key = f"file_loader_confirm_quarantine::{result.filepath}"

    if st.session_state.get(f"file_loader_quarantined::{result.filepath}"):
        st.info(f"Already moved to `{fits_ingest.get_flagged_dir()}/`.")
        return

    if not st.session_state.get(confirm_key):
        if st.button("Quarantine this file", key=f"quarantine_start::{result.filepath}"):
            st.session_state[confirm_key] = True
            st.rerun()
        return

    with st.container(border=True):
        st.markdown(f"Move **{result.filename}** to `{fits_ingest.get_flagged_dir()}/`?")
        st.caption("This is the one write action permitted against the read-only /data/fits/ archive.")
        col_confirm, col_cancel = st.columns(2)
        with col_confirm:
            if st.button("Confirm", key=f"quarantine_confirm::{result.filepath}", type="primary"):
                try:
                    destination = fits_ingest.move_to_flagged(result.filepath)
                except (FileNotFoundError, PermissionError) as exc:
                    st.error(f"Quarantine failed: {exc}")
                else:
                    st.session_state[f"file_loader_quarantined::{result.filepath}"] = True
                    session_store.log_event(f"{result.filename} quarantined -> {destination}")
                    st.session_state.pop(confirm_key, None)
                    # The quarantined file just disappeared from /data/fits/,
                    # so the file-picker's persisted selection (and the
                    # pipeline_data mirror of it) would now point at a path
                    # that no longer exists in list_available_fits(). Clear
                    # both so the selectbox falls back to its default on
                    # rerun instead of erroring on a stale value.
                    st.session_state.pop("file_loader_selected_path", None)
                    st.session_state["pipeline_data"].pop("selected_fits_path", None)
                    st.rerun()
        with col_cancel:
            if st.button("Cancel", key=f"quarantine_cancel::{result.filepath}"):
                st.session_state.pop(confirm_key, None)
                st.rerun()


def _render_mapping_toggle(result: fits_ingest.IngestResult) -> dict[str, str] | None:
    """Auto vs Manual header-mapping segmented control (FR-02)."""
    mode = st.radio(
        "Header mapping",
        options=["Auto-detected", "Manual"],
        horizontal=True,
        key="file_loader_mapping_mode",
        label_visibility="collapsed",
    )

    if mode == "Auto-detected":
        return None

    st.caption("Manually map each priority field to a raw FITS header key.")
    raw_keys = ["(auto)"] + sorted(result.raw_header.keys())
    mapping: dict[str, str] = {}
    cols = st.columns(3)
    for idx, label in enumerate(PRIORITY_LABELS):
        with cols[idx % 3]:
            choice = st.selectbox(
                label,
                raw_keys,
                key=f"file_loader_manual_map::{result.filepath}::{label}",
            )
            if choice != "(auto)":
                mapping[label] = choice
    return mapping


def _render_header_table(result: fits_ingest.IngestResult, manual_mapping: dict[str, str] | None) -> None:
    """FITS Header Table -- st.dataframe with built-in column search, per
    the updated spec. Priority fields are pinned as the first columns;
    the rest of load_file.py's 30+ scalar fields (or the raw-header
    fallback, if load_file.py failed) follow after."""
    styles.render_panel_open("FITS Header Fields")

    priority_rows = dict(fits_ingest.priority_field_rows(result, manual_mapping))
    ordered = {label: priority_rows[label] for label in PRIORITY_LABELS}

    source = result.scalar_fields if result.scalar_fields is not None else result.raw_header
    for key, value in source.items():
        if key not in ordered:
            ordered[key] = value

    df = pd.DataFrame([ordered])
    st.dataframe(df, use_container_width=True, hide_index=True)

    if result.array_fields:
        with st.expander("Spectral / calibration arrays (not shown as table columns)"):
            for key, arr in result.array_fields.items():
                st.caption(f"**{key}**: {fits_ingest.format_array_summary(arr)}")

    styles.render_panel_close()


def _render_extension_viewer(result: fits_ingest.IngestResult) -> None:
    """FITS Extension Viewer (FR-02)."""
    styles.render_panel_open("FITS Extensions")

    try:
        extensions = fits_ingest.list_extensions(result.filepath)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not list extensions: {exc}")
        styles.render_panel_close()
        return

    ext_labels = [f"HDU{e.index} \u2014 {e.name} ({e.hdu_type})" for e in extensions]
    label_to_index = {label: e.index for label, e in zip(ext_labels, extensions)}
    chosen_label = st.selectbox(
        "Extension",
        ext_labels,
        key=f"file_loader_ext_choice::{result.filepath}",
    )
    chosen = extensions[label_to_index[chosen_label]]

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Dimensions", chosen.dimensions)
    col_b.metric("Header cards", chosen.n_header_cards)
    col_c.metric("Data columns", chosen.n_data_columns if chosen.n_data_columns is not None else "\u2014")

    cards = fits_ingest.read_extension_header(result.filepath, chosen.index)
    cards_df = pd.DataFrame(cards, columns=["Keyword", "Value", "Comment"])
    cards_df["Value"] = cards_df["Value"].astype(str)  # mixed bool/int/str values break Arrow serialization
    st.dataframe(
        cards_df,
        use_container_width=True,
        hide_index=True,
        height=240,
    )

    styles.render_panel_close()


def main() -> None:
    st.set_page_config(page_title="HARTSPEC \u2014 File Loader", layout="wide", initial_sidebar_state="expanded")

    session_store.init_session_state()
    sidebar.render_sidebar(current_stage=STAGE_NUMBER)
    styles.inject_base_css()

    styles.render_page_header(
        title="File Loader",
        subtitle="FR-02 FITS load & FR-03 validation / quarantine",
        current_stage=STAGE_NUMBER,
        completed_stages=session_store.completed_count(),
    )

    result = _render_load_panel()
    _render_validation_alerts(result)

    st.markdown(f"<div style='height:{styles.SECTION_GAP}px'></div>", unsafe_allow_html=True)
    manual_mapping = _render_mapping_toggle(result)

    st.markdown(f"<div style='height:{styles.SECTION_GAP}px'></div>", unsafe_allow_html=True)
    _render_header_table(result, manual_mapping)

    st.markdown(f"<div style='height:{styles.SECTION_GAP}px'></div>", unsafe_allow_html=True)
    _render_extension_viewer(result)

    if result.status != "error":
        session_store.mark_stage_complete(STAGE_KEY)


if __name__ == "__main__":
    main()