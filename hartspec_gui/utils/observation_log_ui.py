# observation_log_ui.py — FR-20: searchable read-only observation log for Page 08.
"""Render review data without modifying the pipeline, audit trail or checkpoint schema.

Only the view widgets have Streamlit state, under the existing export_ namespace.
The panel never calls save/checkpoint/log_event or reads another session from disk.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd
import streamlit as st

from .observation_log_logic import (
    STAGES,
    build_log_download,
    build_observation_log,
    download_filename,
    filter_events,
    filter_parameters,
)


def _styled_frame(rows: list[dict[str, Any]], theme: Mapping[str, str], *, monospace: bool = False) -> Any:
    """Reuse the supplied theme's cell colours; never inject user content as HTML."""
    frame = pd.DataFrame(rows)
    properties = {"color": theme["text-body"], "background-color": theme["bg-panel"]}
    if monospace:
        properties["font-family"] = "monospace"
    return frame.style.set_properties(**properties).apply(
        lambda row: [f"background-color: {theme['bg-panel-alt'] if row.name % 2 else theme['bg-panel']}"] * len(row),
        axis=1,
    )


def render_observation_log(state: Mapping[str, Any], *, theme: Mapping[str, str], height: int = 240) -> None:
    """Display recorded events, a separate current-parameter summary and one full text download.

    Args:
        state: Active session mapping (read-only input). No draft or runtime arrays
            are consumed by the report builder.
        theme: Existing styles.get_theme() tokens, passed by Page 08.
        height: Bounded event-table height; the parameter table is also bounded.
    """
    log = build_observation_log(state)
    # TODO: confirm against design — see build spec §3. This approved FR-20
    # increment adds search/summary controls to the old fixed-height log section.
    with st.container(border=True):
        st.markdown('<div class="hs-panel-title">Observation Log Panel (FR-20)</div>', unsafe_allow_html=True)
        st.caption(
            "Read-only review. Events are shown exactly as recorded; missing dates and observer identities "
            "are not inferred. The current parameter summary below is separate from event history."
        )
        for warning in log.warnings:
            st.warning(warning)
        search_col, order_col = st.columns([3, 1])
        with search_col:
            query = st.text_input(
                "Search recorded events", placeholder="Search messages or recorded timestamps…",
                key="export_observation_log_search",
            )
        with order_col:
            order = st.selectbox(
                "Event order", ("Last recorded first", "Original recorded order"),
                key="export_observation_log_order",
            )
        events = filter_events(log.events, query, newest_first=order == "Last recorded first")
        st.caption(
            f"{len(events)} of {len(log.events)} recorded events. Entry numbers retain the original append order; "
            "timestamps are not used to infer chronology across midnight."
        )
        if events:
            event_rows = [
                {"Entry": row.number, "Timestamp (recorded)": row.timestamp,
                 "Message": row.message, "Record note": row.note}
                for row in events
            ]
            st.dataframe(_styled_frame(event_rows, theme, monospace=True), height=height,
                         use_container_width=True, hide_index=True)
        else:
            st.caption("No events match this search." if log.events else "No actions recorded yet this session.")

        with st.expander("Current committed parameters — not event history", expanded=False):
            st.caption(
                "Values are read only from pipeline_data, not unsaved controls. Incomplete or legacy records are "
                "labelled. Completion labels describe recorded markers, not a fresh validation of results. "
                "No earlier parameter values are reconstructed. Blank units are unspecified, not inferred."
            )
            stage_labels = dict(STAGES)
            chosen_stage = st.selectbox(
                "Parameter stage", ("",) + tuple(stage_labels),
                format_func=lambda key: stage_labels.get(key, "All stages"),
                key="export_observation_log_stage",
            )
            parameter_query = st.text_input("Search recorded parameters", key="export_observation_log_parameter_search")
            parameters = filter_parameters(log.parameters, stage_key=chosen_stage, query=parameter_query)
            if parameters:
                parameter_rows = [
                    {"Stage": row.stage, "Parameter": row.parameter, "Value": row.value, "Unit": row.unit,
                     "Recorded stage status": row.status, "Field in pipeline_data": row.field}
                    for row in parameters
                ]
                st.dataframe(_styled_frame(parameter_rows, theme), height=320,
                             use_container_width=True, hide_index=True)
            else:
                st.caption("No parameters match this view.")

        st.download_button(
            "Download observation log (.txt)", data=build_log_download(log),
            file_name=download_filename(log.session_id),
            mime="text/plain; charset=utf-8", type="secondary", key="export_observation_log_download",
        )
        st.caption(
            "The download includes ALL recorded events in original order and the current parameter summary, "
            "regardless of these filters. It is not a loadable session file and does not alter the spectrum CSV or PDF."
        )
