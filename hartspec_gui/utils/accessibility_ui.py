# accessibility_ui.py — FR-22/NFR-11: keyboard-equivalent chart views and scalable table views.
"""Shared Streamlit presentation adapters; they never write pipeline_data or arrays."""
from __future__ import annotations

import hashlib
from importlib import import_module
import json
from datetime import datetime
from html import escape
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder

from utils.accessibility import validate_view_range
from utils.accessibility_plotly import axis_bounds, inspected_value, scaled_figure, trace_sequence


def _streamlit():
    """Resolve the active Streamlit instance (headless fixtures can swap it)."""
    return import_module("streamlit")


def _styles():
    """Use the currently loaded theme module, not a stale test fixture."""
    from utils import styles
    return styles


def _key(kind: str) -> str:
    """Allocate deterministic per-page presentation keys, reset by inject_base_css."""
    st = _streamlit()
    counter = f"_a11y_{kind}_counter"
    index = st.session_state.get(counter, 0)
    st.session_state[counter] = index + 1
    return f"_a11y_{kind}_{st.session_state.get('checkpoint_current_stage', 0)}_{index}"


def _table_html(frame: pd.DataFrame, caption: str, *, hide_index: bool = True) -> str:
    """Render an escaped, semantic read-only table; user values cannot inject HTML."""
    columns = list(frame.columns) if hide_index else [frame.index.name or "Row", *frame.columns]
    header = "".join(f'<th scope="col">{escape(str(name))}</th>' for name in columns)
    rows = []
    for index, row in frame.iterrows():
        values = row.tolist() if hide_index else [index, *row.tolist()]
        cells = "".join(f"<td>{escape(str(value))}</td>" for value in values)
        rows.append(f"<tr>{cells}</tr>")
    return (f'<div class="hs-accessible-table" tabindex="0" role="region" aria-label="{escape(caption, quote=True)}">'
            f'<table><caption>{escape(caption)}</caption><thead><tr>{header}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def render_dataframe(data: Any, **kwargs):
    """Retain native grid behaviour at 100%, with a paginated non-canvas alternative.

    Streamlit 1.32's canvas grid does not inherit CSS font sizes. At enlarged
    sizes the semantic HTML table is the primary view. At 100% it is optional.
    A page selector reaches every row; horizontal arrow-key scrolling reaches
    all columns. CSV contains exactly the displayed dataset, not raw FITS bytes.
    """
    st = _streamlit()
    styles = _styles()
    key = _key("table")
    frame = data.data if isinstance(getattr(data, "data", None), pd.DataFrame) else pd.DataFrame(data)
    hide_index = bool(kwargs.get("hide_index", False))
    large = styles.get_font_scale() > 100
    native = None if large else st.dataframe(data, **kwargs)
    with st.container():
        show = large or st.checkbox("Accessible table view", key=f"{key}_show")
        if show:
            total = len(frame)
            pages = max(1, (total + 49) // 50)
            # Streamlit 1.32 AppTest compares selectbox values with displayed options.
            # Use actual labelled strings so 0/1/2 cannot mismatch "1 of N"/"2 of N".
            page_labels = [f"{i + 1} of {pages}" for i in range(pages)]
            selected_page = st.selectbox("Table page", page_labels, key=f"{key}_page")
            # Native Streamlit returns the label; legacy headless doubles may return
            # a zero-based integer. Both select the same dataset slice.
            page = page_labels.index(selected_page) if isinstance(selected_page, str) else int(selected_page)
            start = page * 50
            caption = f"Rows {start + 1 if total else 0}–{min(start + 50, total)} of {total}"
            table_html = _table_html(frame.iloc[start:start + 50], caption, hide_index=hide_index)
            st.markdown(table_html, unsafe_allow_html=True)
            st.download_button("Download this table as CSV", frame.to_csv(index=not hide_index),
                               file_name="hartspec_table.csv", mime="text/csv", key=f"{key}_csv")
    return native


def _inspect(figure: go.Figure, key: str, labels: list[str]) -> None:
    """Inspect individual original points/cells, including non-numeric coordinates."""
    st = _streamlit()
    if not figure.data or not st.checkbox("Inspect chart values without hovering", key=f"{key}_inspect"):
        return
    index = st.selectbox("Series to inspect", list(range(len(labels))), format_func=lambda i: labels[i],
                         key=f"{key}_inspect_series")
    trace = figure.data[index]
    z = trace_sequence(trace, "z")
    count = len(z) if z else max(len(trace_sequence(trace, "x")), len(trace_sequence(trace, "y")))
    if not count:
        st.caption("This series has no stored point values.")
        return
    sample = int(st.number_input("Row / sample number (first = 1)", min_value=1, max_value=count,
                                 value=1, step=1, key=f"{key}_sample_{index}")) - 1
    column = 0
    if z:
        column = int(st.number_input("Column number (first = 1)", min_value=1, max_value=len(z[sample]),
                                     value=1, step=1, key=f"{key}_column_{index}")) - 1
    values = inspected_value(trace, sample, column)
    st.markdown(_table_html(pd.DataFrame([values]), labels[index]), unsafe_allow_html=True)


def render_plotly_chart(figure: Any, **kwargs):
    """Provide view-only pan/zoom, series selection, value inspection and font scaling.

    All state uses an accessibility namespace, never a pipeline-stage namespace.
    The original figure/arrays and scientific input parameters are not mutated.
    """
    st = _streamlit()
    styles = _styles()
    key = _key("chart")
    original = go.Figure(figure)
    # View settings must not leak onto new data drawn in the same page slot.
    payload = [{name: value for name, value in trace.to_plotly_json().items()
                if name in ("type", "name", "x", "y", "z")} for trace in original.data]
    signature = hashlib.sha256(json.dumps(payload, cls=PlotlyJSONEncoder, sort_keys=True).encode()).hexdigest()[:16]
    key = f"{key}_{signature}"
    display = go.Figure(original)
    labels = [f"{i + 1}. {trace.name or trace.type}" for i, trace in enumerate(original.data)]
    if st.checkbox("Keyboard chart controls and values", key=f"{key}_tools"):
        st.caption("Display only — these controls do not change fits, baseline regions or exported scientific data.")
        visible = st.multiselect("Visible chart series", list(range(len(labels))), default=list(range(len(labels))),
                                 format_func=lambda i: labels[i], key=f"{key}_visible")
        for i, trace in enumerate(display.data):
            trace.visible = i in visible
        limits = {axis: axis_bounds(original, axis) for axis in ("x", "y")}
        if any(limits.values()):
            with st.form(f"{key}_view_form"):
                entries = {}
                for axis, bounds in limits.items():
                    if bounds is None:
                        continue
                    lower, upper, kind = bounds
                    title = getattr(original.layout, f"{axis}axis").title.text or axis.upper()
                    columns = st.columns(2)
                    with columns[0]:
                        first = st.text_input(f"{title}: view start", value=str(lower), key=f"{key}_{axis}_start")
                    with columns[1]:
                        last = st.text_input(f"{title}: view end", value=str(upper), key=f"{key}_{axis}_end")
                    entries[axis] = (first, last, kind)
                submitted = st.form_submit_button("Apply chart view")
            if submitted:
                try:
                    parsed = {}
                    for axis, (lower, upper, kind) in entries.items():
                        if kind == "number":
                            parsed[axis] = list(validate_view_range(lower, upper))
                        else:
                            if datetime.fromisoformat(lower) >= datetime.fromisoformat(upper):
                                raise ValueError("Date view start must precede view end.")
                            parsed[axis] = [lower, upper]
                    st.session_state[f"{key}_view"] = parsed
                except (ValueError, TypeError) as exc:
                    st.error(f"Chart view not changed: {exc}")
            if st.button("Reset chart view", key=f"{key}_reset"):
                st.session_state.pop(f"{key}_view", None)
            for axis, bounds in st.session_state.get(f"{key}_view", {}).items():
                display.update_layout(**{f"{axis}axis": {"range": bounds, "autorange": False}})
        _inspect(original, key, labels)
    display = scaled_figure(display, styles.get_font_scale())
    return st.plotly_chart(display, **kwargs)
