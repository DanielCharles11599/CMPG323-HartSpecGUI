# export_page_ui.py — FR-18/19/20/22: presentation-only Page 08 sections and review tables.
"""Use the existing table palette without changing scientific data or persistence.

The semantic table is the default review surface; the optional native grid retains
sorting/copying controls. All dynamic text is escaped before entering HTML.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from html import escape
from importlib import import_module
from pathlib import Path
from typing import Any

import pandas as pd

PAGE_SIZE = 50
CSS_PATH = Path(__file__).with_name("export_page.css")


def page_css(theme: Mapping[str, str]) -> str:
    """Bind Page 08 classes to shared palette tokens, never to per-page colours."""
    keys = ("table-header-bg", "table-header-text", "bg-panel", "bg-panel-alt", "text-body", "border-default")
    variables = ";".join(f"--hs-export-{key}:{theme[key]}" for key in keys)
    return f".stApp{{{variables}}}\n" + CSS_PATH.read_text(encoding="utf-8")


def inject_css(theme: Mapping[str, str]) -> None:
    """Load only the Page 08 component classes on the export page."""
    import_module("streamlit").markdown(f"<style>{page_css(theme)}</style>", unsafe_allow_html=True)


@contextmanager
def section(title: str) -> Iterator[None]:
    """Keep the heading, controls and chart in one actual Streamlit container."""
    st = import_module("streamlit")
    with st.container(border=True):
        st.markdown(f'<h2 class="hs-export-section-title">{escape(title)}</h2>', unsafe_allow_html=True)
        yield


@contextmanager
def history_row(index: int) -> Iterator[None]:
    """Group each existing native Load action with its saved-session description."""
    st = import_module("streamlit")
    stripe = "even" if index % 2 == 0 else "odd"
    with st.container():
        st.markdown(
            f'<span class="hs-export-history-marker hs-export-history-{stripe}" aria-hidden="true"></span>',
            unsafe_allow_html=True,
        )
        yield


def history_text(text: Any) -> str:
    """Escape saved-session labels rather than treating them as HTML markup."""
    return f'<span class="hs-export-history-text">{escape(str(text))}</span>'


def review_table_html(frame: Any, caption: str, *, height: int = 240, hide_index: bool = True) -> str:
    """Build a bounded, keyboard-scrollable, blue-header table from the supplied rows.

    Text is wrapped, not truncated or rounded; arbitrary messages cannot inject
    tags or attributes. The source DataFrame is only read, never edited.
    """
    columns = list(frame.columns) if hide_index else [frame.index.name or "Row", *frame.columns]
    headers = "".join(f'<th scope="col">{escape(str(column))}</th>' for column in columns)
    rows = []
    for index, row in frame.iterrows():
        values = row.tolist() if hide_index else [index, *row.tolist()]
        cells = "".join(f"<td>{escape(str(value))}</td>" for value in values)
        rows.append(f"<tr>{cells}</tr>")
    # rem units grow with the existing global font-size setting; keep a bounded
    # scroll region instead of making a long audit log consume the whole page.
    max_height = max(120, min(int(height), 480)) / 16
    return (
        f'<div class="hs-export-review-table" role="region" tabindex="0" '
        f'aria-label="{escape(caption, quote=True)}" style="max-height:{max_height:g}rem">'
        '<table><caption class="hs-export-sr-only">' + escape(caption) + '</caption>'
        f'<thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def render_review_table(
    data: Any, *, height: int = 240, use_container_width: bool = True, hide_index: bool = True,
) -> None:
    """Show a themed review table and optional native table tools for the same rows.

    The 50-row pages cover the entire filtered dataset. Label strings are the
    actual selectbox values, compatible with the pinned Streamlit AppTest runner.
    All controls use the existing export_observation_log_ presentation namespace.
    """
    st = import_module("streamlit")
    frame = data.data if isinstance(getattr(data, "data", None), pd.DataFrame) else pd.DataFrame(data)
    is_events = "Message" in frame.columns
    kind, title = ("events", "Observation events") if is_events else ("parameters", "Committed parameters")
    key = f"export_observation_log_{kind}_review"
    total = len(frame)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    labels = [f"{number + 1} of {pages}" for number in range(pages)]
    selected = st.selectbox("Table page", labels, key=f"{key}_page") if pages > 1 else labels[0]
    start = labels.index(selected) * PAGE_SIZE
    caption = f"{title}: rows {start + 1 if total else 0}–{min(start + PAGE_SIZE, total)} of {total}"
    st.markdown(
        review_table_html(frame.iloc[start:start + PAGE_SIZE], caption, height=height, hide_index=hide_index),
        unsafe_allow_html=True,
    )
    if pages > 1:
        st.caption(caption)
    if st.checkbox("Interactive table tools", key=f"{key}_grid"):
        st.caption("Optional grid for sorting, resizing columns and copying values; the recorded data is unchanged.")
        st.dataframe(data, height=height, use_container_width=use_container_width, hide_index=hide_index)
