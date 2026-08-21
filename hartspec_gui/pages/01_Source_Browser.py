"""Stage 01 -- Source Browser (FR-01).

Lets the user browse available FITS/PSS files grouped by observation month,
pick a frequency / spectral line, and hand the selection off to Stage 02
(File Loader). Implements the layout in the code-gen prompt's "01 -- Source
Browser" section: a single "Sources & Frequencies" panel with a grouped file
list, a frequency dropdown below it, and a selection-summary bar with the
"Load into Pipeline" action.

Design note: the mockup shows a checkbox next to each file, but the
selection-summary bar only ever names a single file. That's resolved here as
single-select (checking one file unchecks any other) -- i.e. "pick the one
file to load next" rather than a multi-file batch load. Flagging this
explicitly since the prompt didn't state the multi- vs single-select
behavior outright.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from utils import session_store, sidebar, styles


CURRENT_STAGE = 1
STAGE_KEY = "01_source_browser"

# Sample catalog data. In the real pipeline this would come from scanning
# the FITS archive / PSS database (read-only access, per project data
# conventions) rather than being hardcoded -- swap this out for the real
# file-listing call when clc/ integration lands.
FILE_GROUPS: list[dict[str, Any]] = [
    {
        "label": "2026-08 Observations",
        "count": 12,
        "files": [
            {"name": "spectrum_001.fits", "meta": "FITS · 42MB", "date": "2026-08-10", "dec": "+61°34'"},
            {"name": "spectrum_002.fits", "meta": "FITS · 38MB", "date": "2026-08-12", "dec": "+12°34'"},
            {"name": "spectrum_003.fits", "meta": "FITS · 41MB", "date": "2026-08-11", "dec": "+09°10'"},
        ],
    },
    {
        "label": "2026-07 Observations",
        "count": 8,
        "files": [
            {"name": "pss_survey_014.txt", "meta": "PSS · 3MB", "date": "2026-07-28", "dec": "+01°53'"},
            {"name": "pss_survey_015.txt", "meta": "PSS · 3MB", "date": "2026-07-29", "dec": "+02°10'"},
        ],
    },
]

FREQUENCY_OPTIONS: list[str] = [
    "1420.405 MHz — HI line",
    "1612.231 MHz — OH satellite line",
    "1665.402 MHz — OH main line",
    "1667.359 MHz — OH main line",
    "6668.518 MHz — CH3OH maser line",
    "22235.080 MHz — H2O maser line",
]

DEFAULT_SELECTED_FILE = "spectrum_002.fits"


def _select_file(filename: str) -> None:
    """Checkbox on_change callback: enforce single-file selection."""
    st.session_state["source_browser_selected_file"] = filename


def _find_file(filename: str) -> dict[str, Any]:
    """Look up a file's metadata by name across all groups."""
    for group in FILE_GROUPS:
        for file_entry in group["files"]:
            if file_entry["name"] == filename:
                return file_entry
    raise KeyError(f"Unknown file: {filename}")


def render_file_browser_panel() -> None:
    """Render the grouped, checkbox-driven file list (FR-01)."""
    theme = styles.get_theme()
    styles.render_panel_open("Source Browser — FR-01")

    for group in FILE_GROUPS:
        st.markdown(
            f'<div style="font-size:14px; font-weight:600; color:{theme["text-body"]}; '
            f'margin-top:12px;">{group["label"]}</div>'
            f'<div style="font-size:11px; color:{theme["text-muted"]}; margin-bottom:6px;">'
            f'{group["count"]} files</div>',
            unsafe_allow_html=True,
        )
        for file_entry in group["files"]:
            checkbox_col, name_col, status_col = st.columns([0.06, 0.7, 0.24])
            with checkbox_col:
                st.checkbox(
                    "select file",
                    value=(file_entry["name"] == st.session_state["source_browser_selected_file"]),
                    key=f"file_select_{file_entry['name']}",
                    label_visibility="collapsed",
                    on_change=_select_file,
                    args=(file_entry["name"],),
                )
            with name_col:
                st.markdown(
                    f'<div style="font-size:14px; color:{theme["text-body"]};">{file_entry["name"]}</div>'
                    f'<div style="font-size:11px; color:{theme["text-muted"]};">{file_entry["meta"]}</div>',
                    unsafe_allow_html=True,
                )
            with status_col:
                st.markdown(
                    f'<div style="text-align:right; padding-top:2px;">{styles.render_badge("OK", "ok")}</div>',
                    unsafe_allow_html=True,
                )

    styles.render_panel_close()


def render_frequency_picker() -> None:
    """Render the FREQUENCY eyebrow label + dropdown."""
    st.markdown('<div class="hs-eyebrow">Frequency</div>', unsafe_allow_html=True)
    st.session_state["source_browser_frequency"] = st.selectbox(
        "Frequency",
        FREQUENCY_OPTIONS,
        index=FREQUENCY_OPTIONS.index(st.session_state["source_browser_frequency"]),
        label_visibility="collapsed",
    )


def render_selection_summary_and_load_button() -> None:
    """Render the summary bar + "Load into Pipeline" action (hands off to Stage 02)."""
    theme = styles.get_theme()
    selected_file = _find_file(st.session_state["source_browser_selected_file"])
    frequency_label = st.session_state["source_browser_frequency"].split(" — ")[-1]

    styles.render_panel_open("")
    st.markdown(
        f'<div style="font-size:13px; color:{theme["text-body"]}; margin-bottom:12px;">'
        f'Selected: {selected_file["name"]} · {selected_file["date"]} · {frequency_label} · '
        f'Dec {selected_file["dec"]}</div>',
        unsafe_allow_html=True,
    )

    if st.button("Load into Pipeline →", type="primary", key="load_into_pipeline"):
        st.session_state["pipeline_data"][STAGE_KEY] = {
            "file": selected_file["name"],
            "date": selected_file["date"],
            "frequency": st.session_state["source_browser_frequency"],
        }
        session_store.mark_stage_complete(STAGE_KEY)
        session_store.log_event(
            f"Source selected: {selected_file['name']} @ {st.session_state['source_browser_frequency']}"
        )
        st.success("Selection loaded. Continuing to Stage 02 — File Loader.")
        st.switch_page("pages/02_File_Loader.py")

    styles.render_panel_close()


def main() -> None:
    """Entry point for this Streamlit page script."""
    st.set_page_config(
        page_title="HARTSPEC — Source Browser",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    session_store.init_session_state()
    sidebar.render_sidebar(current_stage=CURRENT_STAGE)
    styles.inject_base_css()

    st.session_state.setdefault("source_browser_selected_file", DEFAULT_SELECTED_FILE)
    st.session_state.setdefault("source_browser_frequency", FREQUENCY_OPTIONS[0])

    styles.render_page_header(
        title="Source Browser",
        subtitle="FR-01 — file browser for source & frequency selection",
        current_stage=CURRENT_STAGE,
        completed_stages=session_store.completed_count(),
    )

    render_file_browser_panel()
    render_frequency_picker()
    render_selection_summary_and_load_button()


main()