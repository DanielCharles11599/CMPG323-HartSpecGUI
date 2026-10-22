# test_export_page_polish.py — FR-18/19/20/22: read-only Page 08 presentation contracts.
from __future__ import annotations

import ast
from contextlib import contextmanager
from html.parser import HTMLParser
from pathlib import Path
import sys
from types import ModuleType

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from utils import export_page_ui
from utils.accessibility_help import help_link_html

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "hartspec_gui"


class ParsedHTML(HTMLParser):
    """Collect text and element attributes without executing markup."""

    def __init__(self, text):
        super().__init__()
        self.text, self.tags = [], []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


class ReviewUI(ModuleType):
    """A presentation-only facade that records nesting, pagination and native grids."""

    def __init__(self):
        super().__init__("streamlit")
        self.html, self.grids, self.keys = [], [], []
        self.controls = {}
        self.session_state = {}
        self.depth = 0
        self.render_depths = []

    @contextmanager
    def container(self, **kwargs):
        self.depth += 1
        try:
            yield
        finally:
            self.depth -= 1

    def markdown(self, text, **kwargs):
        self.html.append(text)
        self.render_depths.append(self.depth)

    def caption(self, text):
        pass

    def selectbox(self, label, options, *, key):
        self.keys.append(key)
        return self.controls.get(key, options[0])

    def checkbox(self, label, *, key):
        self.keys.append(key)
        return self.controls.get(key, False)

    def dataframe(self, frame, **kwargs):
        self.grids.append(frame)


@pytest.fixture
def ui(monkeypatch):
    fake = ReviewUI()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    return fake


def test_help_visible_label_is_compact_but_new_tab_remains_announced():
    parsed = ParsedHTML(help_link_html("light", 100))
    assert "".join(parsed.text) == "Keyboard and accessibility help"
    link = next(attrs for tag, attrs in parsed.tags if tag == "a")
    assert link["target"] == "_blank"
    assert set(link["rel"].split()) == {"noopener", "noreferrer"}
    assert "opens in a new tab" in link["aria-label"]
    assert not any(attrs.get("class") == "hs-help-hint" for _, attrs in parsed.tags)


def test_section_really_contains_title_and_body_and_escapes_title(ui):
    with export_page_ui.section("Review <not markup>"):
        ui.markdown("Chart body")
    assert ui.render_depths == [1, 1]
    assert "&lt;not markup&gt;" in ui.html[0]
    assert "<h2" in ui.html[0] and ui.depth == 0


@pytest.mark.parametrize("index,stripe", [(0, "even"), (1, "odd"), (2, "even")])
def test_session_rows_keep_native_controls_grouped(ui, index, stripe):
    with export_page_ui.history_row(index):
        ui.markdown("Native Load control")
    assert ui.render_depths == [1, 1]
    assert f"hs-export-history-{stripe}" in ui.html[0]


def test_history_labels_cannot_inject_html():
    text = export_page_ui.history_text('<img src=x onerror="bad()">')
    assert "<img" not in text and "&lt;img" in text


@pytest.mark.parametrize("hide_index", [True, False])
def test_review_table_preserves_values_and_escapes_all_cells(hide_index):
    frame = pd.DataFrame({"<header>": ['<script>bad()</script>', "LCP ± Δv"], "Value": [1.23456789, -1000]})
    before = frame.copy(deep=True)
    html = export_page_ui.review_table_html(frame, 'Rows <1> "quoted"', hide_index=hide_index)
    assert_frame_equal(frame, before)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "&lt;header&gt;" in html and "1.23456789" in html
    parsed = ParsedHTML(html)
    region = next(attrs for tag, attrs in parsed.tags if tag == "div")
    assert region["role"] == "region" and region["tabindex"] == "0"
    assert region["aria-label"] == 'Rows <1> "quoted"'
    assert all(attrs.get("scope") == "col" for tag, attrs in parsed.tags if tag == "th")
    assert any(tag == "caption" for tag, _ in parsed.tags)


@pytest.mark.parametrize("total", [0, 1, 50, 51, 130])
def test_paging_reaches_every_filtered_event_without_state_mutation(ui, total):
    frame = pd.DataFrame({"Entry": list(range(total)), "Message": [f"EVENT-{i}-END" for i in range(total)]})
    before = frame.copy(deep=True)
    count = max(1, (total + 49) // 50)
    seen = []
    for number in range(count):
        ui.controls["export_observation_log_events_review_page"] = f"{number + 1} of {count}"
        export_page_ui.render_review_table(frame)
        parsed = ParsedHTML(ui.html[-1])
        seen.extend(value for value in parsed.text if value.startswith("EVENT-"))
    assert seen == frame["Message"].tolist()
    assert_frame_equal(frame, before)
    assert ui.session_state == {} and ui.grids == []
    assert all(key.startswith("export_observation_log_") for key in ui.keys)
    assert ("export_observation_log_events_review_page" in ui.keys) == (total > 50)


def test_optional_native_grid_receives_the_full_original_dataset(ui):
    frame = pd.DataFrame({"Entry": range(120), "Message": ["Recorded"] * 120})
    styled = frame.style
    ui.controls.update({"export_observation_log_events_review_page": "3 of 3",
                        "export_observation_log_events_review_grid": True})
    export_page_ui.render_review_table(styled)
    assert ui.grids == [styled]
    assert len(ui.grids[0].data) == 120


def test_event_and_parameter_widgets_have_distinct_keys(ui):
    export_page_ui.render_review_table(pd.DataFrame({"Message": ["Recorded"]}))
    export_page_ui.render_review_table(pd.DataFrame({"Parameter": ["PWV"]}))
    assert len(set(ui.keys)) == len(ui.keys) == 2


def test_dataframe_column_called_data_is_not_mistaken_for_styler(ui):
    export_page_ui.render_review_table(pd.DataFrame({"data": [123], "Message": ["Recorded"]}))
    assert "123" in ui.html[-1]


def test_page_eight_uses_new_sections_without_changing_export_actions():
    source = (APP / "pages/08_Export_and_Session.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    names = [ast.unparse(call.func) for call in calls]
    assert names.count("render_observation_log") == 1
    assert names.count("export_preview_ui.render_export_preview") == 1
    assert "styles.render_panel_open" not in names
    assert "export_logic.build_export_csv" in names and "export_logic.build_graphs_pdf" in names
    assert "session_store.load_session" in names
    assert source.index('"Mark export complete"') < source.rindex('session_store.checkpoint_session(')
    assert "table_renderer=export_page_ui.render_review_table" in source


def test_presentation_module_never_writes_science_or_sessions():
    tree = ast.parse((APP / "utils/export_page_ui.py").read_text(encoding="utf-8"))
    prohibited = {"save_session", "load_session", "checkpoint_session", "log_event", "mark_stage_complete",
                  "write_text", "write_bytes"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            assert ast.unparse(node.func).split(".")[-1] not in prohibited


def test_manual_copies_document_the_page_eight_exception():
    manual = (ROOT / "docs/user_manual/keyboard_accessibility.md").read_text(encoding="utf-8")
    assert manual == (APP / "help/keyboard_accessibility.md").read_text(encoding="utf-8")
    assert "Page 08 exception" in manual and "Interactive table tools" in manual
