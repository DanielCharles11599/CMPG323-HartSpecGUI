"""Page 02 — File Loader (FR-02 FITS load, FR-03 validation / quarantine).

Layout reference: HARTSPEC-Page_Build_Spec.md §7, page 02. Column/row widths
below are expressed as flex proportions derived from that spec's pixel
values, not literal pixels -- see utils/styles.py module docstring for why.

Two integration points are stubbed with TODOs rather than guessed, per the
project's "ask, don't invent spec details" rule:

1. The FR-02 load itself currently *simulates* progress rather than calling
   into clc/load_file.py, because that module's function signature /
   progress-callback shape (if any) hasn't been confirmed yet.
2. The FR-03 Quarantine button updates session state and logs the action,
   but doesn't yet call a real "move file out of /data/fits/" function,
   because clc/File_check.py's quarantine entry point (if one already
   exists) hasn't been confirmed.

Both are marked with `# TODO: confirm against design` per the build spec's
own instruction (§8) for exactly this situation.
"""

from __future__ import annotations

import time

import streamlit as st

from utils import session_store, sidebar, styles

STAGE_NUMBER = 2
STAGE_KEY = "file_loader"
LOAD_FILENAME = "spectrum_002.fits"
LOAD_SIMULATED_DURATION_S = 5.0  # matches the <5s FR-02 performance target

# --------------------------------------------------------------------------
# Sample data -- reproduces the build spec's exact sample rows (§7, page 02).
# The header-fields table previews a 30+ field dataset but only the 9
# priority fields below are specified; the search box only searches these
# until the rest of the field list is confirmed (see module docstring).
# --------------------------------------------------------------------------
VALIDATION_ROWS = [
    {"file": "spectrum_002.fits", "issue": "\u2014", "status": "ok"},
    {"file": "spectrum_003.fits", "issue": "Header checksum mismatch", "status": "error"},
    {"file": "pss_survey_015.txt", "issue": "\u2014", "status": "ok"},
]

HEADER_FIELDS_COLUMNS = [
    "Vlsr", "LCP/RCP", "HPBW", "Tsys", "Date", "Object", "RA/Dec", "Focus", "Humidity",
]

HEADER_FIELDS_ROWS = [
    ["-4.2 km/s", "12.3/11.8K", "0.23\u00b0", "48.1K", "08-12", "W3(OH)", "02:27+61\u00b0", "3.1mm", "38%"],
    ["-3.8 km/s", "11.9/11.5K", "0.23\u00b0", "47.6K", "08-12", "W49N", "19:10+09\u00b0", "3.0mm", "37%"],
    ["-5.1 km/s", "13.0/12.4K", "0.23\u00b0", "48.9K", "08-11", "G34.3", "18:53+01\u00b0", "3.2mm", "41%"],
]


def _simulate_fits_load() -> None:
    """Animate the FR-02 load progress bar once per session.

    TODO: confirm against design -- replace this simulation with a real
    call into clc/load_file.py once its signature (and whether it exposes
    a progress callback) is confirmed. Until then this only demonstrates
    the UI: track/fill/caption computed at runtime per the build spec.
    """
    placeholder = st.empty()
    theme = styles.get_theme()
    steps = 40
    for i in range(1, steps + 1):
        pct = i / steps
        elapsed = pct * LOAD_SIMULATED_DURATION_S
        fill_px = round(1140 * pct)
        with placeholder.container():
            st.markdown(
                f"""
                <div>
                  <div style="font-size:14px; color:{theme['text-body']};">
                      Loading {LOAD_FILENAME}
                  </div>
                  <div style="width:100%; height:10px; border-radius:5px;
                              background-color:{theme['border-subtle']}; margin:14px 0 8px;">
                    <div style="width:{fill_px}px; max-width:100%; height:100%; border-radius:5px;
                                background-color:{theme['accent']};"></div>
                  </div>
                  <div style="font-size:11px; color:{theme['text-muted']};">
                      {elapsed:.1f}s elapsed \u00b7 {round(pct * 100)}%
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        time.sleep(LOAD_SIMULATED_DURATION_S / steps)

    st.session_state["file_loader_load_done"] = True
    session_store.log_event(f"{LOAD_FILENAME} loaded in {LOAD_SIMULATED_DURATION_S:.1f}s")


def _render_load_progress() -> None:
    styles.render_panel_open("")
    if not st.session_state.get("file_loader_load_done"):
        _simulate_fits_load()
        st.rerun()
    else:
        theme = styles.get_theme()
        st.markdown(
            f"""
            <div>
              <div style="font-size:14px; color:{theme['text-body']};">
                  Loaded {LOAD_FILENAME}
              </div>
              <div style="width:100%; height:10px; border-radius:5px;
                          background-color:{theme['border-subtle']}; margin:14px 0 8px;">
                <div style="width:100%; height:100%; border-radius:5px;
                            background-color:{theme['accent']};"></div>
              </div>
              <div style="font-size:11px; color:{theme['text-muted']};">
                  {LOAD_SIMULATED_DURATION_S:.1f}s elapsed \u00b7 100%
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    styles.render_panel_close()


def _quarantine_file(filename: str) -> None:
    """Mark a file quarantined in session state and log the action.

    TODO: confirm against design -- this should call the real
    clc/File_check.py quarantine entry point (moving the file out of the
    read-only /data/fits/ archive) once that function is confirmed to
    exist; right now this only updates UI-facing session state.
    """
    st.session_state.setdefault("file_loader_quarantined", set())
    st.session_state["file_loader_quarantined"].add(filename)
    session_store.log_event(f"{filename} quarantined (header checksum mismatch)")


def _render_validation_table() -> None:
    quarantined = st.session_state.get("file_loader_quarantined", set())

    styles.render_panel_open("")
    styles.render_table_header([("File", "45.5%"), ("Issue", "35.1%"), ("Status", "19.4%")])

    for idx, row in enumerate(VALIDATION_ROWS):
        striped = idx % 2 == 1
        theme = styles.get_theme()
        bg = theme["bg-panel-alt"] if striped else theme["bg-panel"]

        if row["file"] in {r["file"] for r in VALIDATION_ROWS if r["status"] == "error"}:
            # The flagged row gets a real inline Quarantine button, so it's
            # laid out with st.columns (matching the header's proportions)
            # instead of the static render_table_row HTML helper.
            is_quarantined = row["file"] in quarantined
            status_label = "QUARANTINED" if is_quarantined else "FLAGGED"

            st.markdown(
                f'<div style="background-color:{bg}; border-bottom:1px solid '
                f'{theme["border-subtle"]}; padding:2px 0;">',
                unsafe_allow_html=True,
            )
            col_file, col_issue, col_status, col_action = st.columns([455, 300, 140, 106])
            with col_file:
                st.markdown(
                    f'<div style="padding-left:10px; font-size:10.5px; color:{theme["text-body"]}; '
                    f'line-height:28px;">{row["file"]}</div>',
                    unsafe_allow_html=True,
                )
            with col_issue:
                st.markdown(
                    f'<div style="font-size:10.5px; color:{theme["text-body"]}; '
                    f'line-height:28px;">{row["issue"]}</div>',
                    unsafe_allow_html=True,
                )
            with col_status:
                st.markdown(
                    f'<div style="line-height:28px;">{styles.render_badge(status_label, "error")}</div>',
                    unsafe_allow_html=True,
                )
            with col_action:
                if not is_quarantined:
                    if st.button("Quarantine", key=f"quarantine_{row['file']}", use_container_width=True):
                        _quarantine_file(row["file"])
                        st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            badge = styles.render_badge("OK", "ok")
            styles.render_table_row(
                [(row["file"], "45.5%"), (row["issue"], "35.1%"), (badge, "19.4%")],
                striped=striped,
            )

    styles.render_panel_close()


def _render_header_fields_table() -> None:
    search = st.text_input(
        "Search fields",
        placeholder="Search 30+ fields\u2026",
        key="file_loader_field_search",
        label_visibility="collapsed",
    )

    if search:
        visible_columns = [c for c in HEADER_FIELDS_COLUMNS if search.lower() in c.lower()]
    else:
        visible_columns = HEADER_FIELDS_COLUMNS

    styles.render_panel_open("")
    if not visible_columns:
        st.caption(
            "No matching fields among the 9 priority columns shown here. "
            "The full 30+ field list isn't specified yet in the build spec -- "
            "ask before adding more columns rather than inventing field names."
        )
    else:
        col_width = f"{100 / len(visible_columns):.4f}%"
        styles.render_table_header([(c, col_width) for c in visible_columns])
        for idx, row in enumerate(HEADER_FIELDS_ROWS):
            values = [row[HEADER_FIELDS_COLUMNS.index(c)] for c in visible_columns]
            styles.render_table_row([(v, col_width) for v in values], striped=(idx % 2 == 1))
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

    _render_load_progress()
    _render_validation_table()

    st.markdown(f"<div style='height:{styles.SECTION_GAP}px'></div>", unsafe_allow_html=True)
    _render_header_fields_table()

    if st.session_state.get("file_loader_load_done"):
        session_store.mark_stage_complete(STAGE_KEY)


if __name__ == "__main__":
    main()
