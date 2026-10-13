# test_ui_adapters.py — FR-22 headless rendering contracts (not browser acceptance).
from __future__ import annotations

import copy
import importlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pandas as pd
import plotly.graph_objects as go
import pytest

APP = Path(__file__).resolve().parents[2] / "hartspec_gui"


class UI(ModuleType):
    """Small explicit API double for the new display-only adapters."""
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {"theme": "light", "font_scale": 100, "pipeline_data": {"original": [1.23]}}
        self.controls, self.html, self.charts, self.frames = {}, [], [], []
        self.downloads, self.errors, self.keys = [], [], []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def container(self):
        return self

    def form(self, key):
        return self

    def columns(self, number):
        return [self] * number

    def markdown(self, body, **kwargs):
        self.html.append(body)

    def caption(self, text):
        pass

    def error(self, text):
        self.errors.append(text)

    def checkbox(self, label, *, key):
        self.keys.append(key)
        return self.controls.get(label, False)

    def button(self, label, *, key):
        self.keys.append(key)
        return self.controls.get(label, False)

    def form_submit_button(self, label):
        return self.controls.get(label, False)

    def selectbox(self, label, options, *, key, **kwargs):
        self.keys.append(key)
        return self.controls.get(label, options[0])

    def multiselect(self, label, options, *, default, key, **kwargs):
        self.keys.append(key)
        return self.controls.get(label, default)

    def text_input(self, label, *, value, key):
        self.keys.append(key)
        return self.controls.get(label, value)

    def number_input(self, label, *, min_value, max_value, value, step, key):
        self.keys.append(key)
        return self.controls.get(label, value)

    def dataframe(self, frame, **kwargs):
        self.frames.append(frame)

    def plotly_chart(self, figure, **kwargs):
        self.charts.append(figure)

    def download_button(self, label, data, **kwargs):
        self.downloads.append(data)


@pytest.fixture
def display(monkeypatch):
    fake = UI()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    package = importlib.import_module("utils")
    spec = importlib.util.spec_from_file_location("_fr22_styles", APP / "utils/styles.py")
    styles = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(styles)
    monkeypatch.setattr(package, "styles", styles, raising=False)
    spec = importlib.util.spec_from_file_location("_fr22_display", APP / "utils/accessibility_ui.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return fake, module, styles


def test_chart_controls_copy_the_figure_and_do_not_change_pipeline(display):
    ui, module, styles = display
    ui.session_state["font_scale"] = 200
    ui.controls.update({"Keyboard chart controls and values": True, "Visible chart series": [0],
                        "X: view start": "0.5", "X: view end": "1.5", "Apply chart view": True,
                        "Inspect chart values without hovering": True})
    fig = go.Figure([go.Scatter(x=[0, 1, 2], y=[1.23456789, 2, 4], name="LCP"),
                     go.Scatter(x=[0, 1, 2], y=[3, 4, 5], name="RCP")])
    fig.update_layout(height=300, font={"size": 11})
    before = fig.to_json()
    science = copy.deepcopy(ui.session_state["pipeline_data"])
    module.render_plotly_chart(fig, use_container_width=True, theme=None)
    assert fig.to_json() == before and ui.session_state["pipeline_data"] == science
    assert ui.charts[0].layout.font.size == 22
    assert ui.charts[0].layout.xaxis.range == (0.5, 1.5)
    assert ui.charts[0].data[1].visible is False
    assert any("1.23456789" in text for text in ui.html)


def test_invalid_view_retains_previous_view(display):
    ui, module, styles = display
    ui.controls.update({"Keyboard chart controls and values": True, "X: view start": "0.5",
                        "X: view end": "1.5", "Apply chart view": True})
    fig = go.Figure(go.Scatter(x=[0, 1, 2], y=[1, 2, 4]))
    module.render_plotly_chart(fig)
    ui.session_state["_a11y_chart_counter"] = 0
    ui.controls["X: view end"] = "nan"
    module.render_plotly_chart(fig)
    assert ui.errors
    assert ui.charts[-1].layout.xaxis.range == (0.5, 1.5)


def test_scalable_table_escapes_values_and_reaches_every_row(display):
    ui, module, styles = display
    ui.session_state["font_scale"] = 200
    frame = pd.DataFrame({"Message": ["<script>unsafe</script>"] * 123})
    module.render_dataframe(frame, hide_index=True)
    assert not ui.frames
    assert "<script>unsafe</script>" not in "".join(ui.html)
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in "".join(ui.html)
    assert "Rows 1–50 of 123" in "".join(ui.html)
    ui.session_state["_a11y_table_counter"] = 0
    ui.controls["Table page"] = 2
    module.render_dataframe(frame, hide_index=True)
    assert "Rows 101–123 of 123" in ui.html[-1]
    assert len(ui.downloads[-1].splitlines()) == 124
    assert ui.session_state["pipeline_data"] == {"original": [1.23]}


def test_default_table_keeps_native_grid_and_supplement_is_opt_in(display):
    ui, module, styles = display
    frame = pd.DataFrame({"A": [1, 2]})
    module.render_dataframe(frame)
    assert len(ui.frames) == 1 and not ui.html


def test_two_same_figures_get_distinct_widget_keys(display):
    ui, module, styles = display
    fig = go.Figure(go.Scatter(x=[0, 1], y=[0, 2]))
    module.render_plotly_chart(fig)
    module.render_plotly_chart(fig)
    assert len(ui.keys) == len(set(ui.keys))
