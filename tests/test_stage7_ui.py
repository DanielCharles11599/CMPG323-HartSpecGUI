# test_stage7_ui.py — actual Page 07 functions with a headless widget-contract double.
"""Checks rerun/state/optimizer gating, NOT browser pixels or a real Streamlit runtime."""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest

from utils import accessibility_ui, fit_figures, fitting_helpers as fh, fitting_inputs, fitting_state as fs
from utils import spectrum_resolution
from test_stage7_final import original_function

APP = Path(__file__).resolve().parents[1] / "hartspec_gui"


class Rerun(Exception):
    """Simulate Streamlit's nonlocal rerun control flow."""


class State(dict):
    """Support Streamlit's attribute and mapping access forms."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class UI:
    """Deliberately small explicit widget API; unexpected methods fail the test."""
    def __init__(self):
        self.session_state = State(session_id="stage7test", pipeline_data={}, completed_stages=set(), audit_log=[],
                                   theme="light", font_scale=100)
        self.controls, self.pressed, self.charts, self.messages = {}, set(), {}, []
        self.widgets, self.keys, self.saved = {}, set(), None
        self.column_config = SimpleNamespace(**{
            name: lambda *a, **k: None
            for name in ("TextColumn", "NumberColumn", "CheckboxColumn")
        })

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def begin(self):
        self.charts, self.messages, self.widgets, self.keys = {}, [], {}, set()

    def _value(self, label, key, default):
        assert key not in self.keys, f"Duplicate widget key: {key}"
        self.keys.add(key)
        value = self.controls.get(key, self.controls.get(label, self.session_state.get(key, default)))
        self.session_state[key] = value
        self.widgets[key] = {"label": label, "value": value}
        return value

    def set_page_config(self, **kwargs):
        pass

    def container(self, **kwargs):
        return self

    def expander(self, *args, **kwargs):
        return self

    def columns(self, widths):
        return [self] * (widths if isinstance(widths, int) else len(widths))

    def spinner(self, message):
        assert message == "Fitting spectrum..."
        return self

    def markdown(self, text, **kwargs):
        self.messages.append(("markdown", text))

    def caption(self, text):
        self.messages.append(("caption", text))

    def info(self, text):
        self.messages.append(("info", text))

    def warning(self, text):
        self.messages.append(("warning", text))

    def error(self, text):
        self.messages.append(("error", text))

    def success(self, text):
        self.messages.append(("success", text))

    def radio(self, label, options, **kwargs):
        self.radio_options = tuple(options)
        return self._value(label, kwargs["key"], options[0])

    def slider(self, label, minimum, maximum, value, *, key, **kwargs):
        value = self._value(label, key, value)
        assert minimum <= value <= maximum
        return value

    def number_input(self, label, *, value, key, min_value=None, max_value=None, **kwargs):
        value = self._value(label, key, value)
        assert min_value is None or value >= min_value
        assert max_value is None or value <= max_value
        return value

    def selectbox(self, label, options, *, key, index=0, **kwargs):
        value = self._value(label, key, options[index])
        assert value in options
        self.widgets[key]["options"] = tuple(options)
        self.widgets[key]["format_func"] = kwargs.get("format_func", str)
        return value

    def checkbox(self, label, *, key, value=False, **kwargs):
        return self._value(label, key, value)

    def button(self, label, *, key, disabled=False, **kwargs):
        assert key not in self.keys
        self.keys.add(key)
        self.widgets[key] = {"label": label, "disabled": disabled}
        clicked = key in self.pressed and not disabled
        self.pressed.discard(key)
        return clicked

    def data_editor(self, data, *, key, **kwargs):
        assert key not in self.keys
        self.keys.add(key)
        self.editor_key = key
        self.editor_columns = list(data.columns)
        self.session_state.setdefault(key, {})
        return self.controls.get(key, data).copy()

    def dataframe(self, data, **kwargs):
        return None

    def plotly_chart(self, figure, **kwargs):
        assert kwargs.get("key") is not None
        assert kwargs["key"] not in self.charts
        self.charts[kwargs["key"]] = figure
        return figure

    def rerun(self):
        raise Rerun

    def switch_page(self, page):
        raise AssertionError("This test should not navigate")


def _page_namespace(ui, monkeypatch):
    """Compile the actual page definitions; replace browser services, not its function bodies."""
    theme = {"bg-panel": "#FFFFFF", "text-body": "#334155", "text-muted": "#64748B",
             "border-default": "#CBD5E1", "accent": "#587BBD"}
    styles = SimpleNamespace(get_theme=lambda: theme, get_theme_name=lambda: ui.session_state["theme"],
                             get_font_scale=lambda: ui.session_state["font_scale"],
                             get_fit_line_color=lambda: "#DC2626", plotly_layout_theme=lambda t: {},
                             inject_base_css=lambda: None, render_page_header=lambda *a: None,
                             render_dataframe=ui.dataframe, render_plotly_chart=accessibility_ui.render_plotly_chart)
    monkeypatch.setattr(accessibility_ui, "_streamlit", lambda: ui)
    monkeypatch.setattr(accessibility_ui, "_styles", lambda: styles)

    def log(message):
        ui.session_state["audit_log"].append({"ts": "00:00:00", "message": message})

    def checkpoint(message):
        ui.saved = json.loads(json.dumps({
            "pipeline_data": ui.session_state.pipeline_data,
            "stages": fh.stages_from_pipeline(ui.session_state.pipeline_data),
            "audit_log": ui.session_state["audit_log"],
        }, allow_nan=False))

    store = SimpleNamespace(init_session_state=lambda: None, log_event=log, completed_before=lambda n: 0,
                            mark_stage_complete=lambda key: ui.session_state["completed_stages"].add(key),
                            checkpoint_session=checkpoint)
    namespace = dict(Any=Any, np=np, pd=pd, go=go, st=ui, copy=copy, json=json, styles=styles, session_store=store,
                     fh=fh, fs=fs, fitting_inputs=fitting_inputs, fit_figures=fit_figures,
                     spectrum_resolution=spectrum_resolution, render_sidebar=lambda n: None,
                     baseline_editor_bridge=SimpleNamespace(
                         read_bridge=lambda s: None, spectrum_fingerprint=lambda s: "x",
                     ))
    tree = ast.parse((APP / "pages/07_Spectral_Fitting.py").read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Assign))]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP / "pages/07_Spectral_Fitting.py"), "exec"), namespace)
    return namespace


@pytest.fixture
def page(monkeypatch):
    ui = UI()
    namespace = _page_namespace(ui, monkeypatch)
    original = fh._clc_function
    functions = {"Gaussf": SimpleNamespace(gaussf=original_function("Gaussf.py", "gaussf")),
                 "fit_max": SimpleNamespace(fit_max=original_function("fit_max.py", "fit_max"))}
    monkeypatch.setattr(fh, "_clc_function", lambda module, name, function:
                        original(module or functions[name], name, function))

    def run():
        for _ in range(4):
            ui.begin()
            try:
                namespace["main"]()
                return ui
            except Rerun:
                continue
        raise AssertionError("Unexpected rerun loop")
    return SimpleNamespace(ui=ui, namespace=namespace, run=run)


def observed(ui):
    """Fixture only: already-calibrated spectrum and the metadata Graph 3 requires."""
    v = np.linspace(-20, 20, 1024)
    y = fh.gaussian(v, 10., -4., 2.5) + np.random.default_rng(23).normal(0, .02, v.size)
    ui.session_state["calibrated_spectrum"] = {"Vlsr": v, "LCP": y / 2, "RCP": y / 2}
    ui.session_state.pipeline_data.update({
        "05_calibration_dashboard": {"pss": {"lcp_window_mean": 1., "rcp_window_mean": 1.}},
        "06_pointing_correction": {"correction_factor": 0., "input_source": "test"}})
    return v, y


def test_selector_order_and_exact_graph_colours(page):
    observed(page.ui)
    page.run()
    assert page.ui.radio_options == fh.FIT_TYPES
    assert page.ui.charts["chart_fit_lcp"].data[0].line.color == "#1F77B4"
    assert page.ui.charts["chart_fit_rcp"].data[0].line.color == "#FF7F0E"
    data, model = page.ui.charts["chart_fit_1d"].data
    assert data.line.color == "#4B5563" and model.line.color == "#DC2626" and model.line.dash == "dash"


def test_1d_only_recomputes_on_science_parameter_changes(page, monkeypatch):
    observed(page.ui)
    real = fh.run_gaussf
    calls = []
    monkeypatch.setattr(fh, "run_gaussf", lambda *a, **k: (calls.append(1) or real(*a, **k)))
    page.run()
    page.ui.session_state["theme"] = "dark"
    page.ui.session_state["font_scale"] = 125
    page.run()
    assert len(calls) == 1
    page.ui.controls["HPBW (km/s, fixed)"] = 3.
    page.run()
    assert len(calls) == 2


def test_polynomial_window_and_curve_are_both_on_graph3(page):
    observed(page.ui)
    page.ui.controls["fit_type"] = "Polynomial Peak"
    page.run()
    fig = page.ui.charts["chart_fit_poly"]
    assert len(fig.data) == 2 and len(fig.layout.shapes) == 1
    assert fig.data[1].line.dash == "dash"
    entry = page.ui.session_state.pipeline_data[fs.STAGE_KEY]["modes"]["Polynomial Peak"]
    assert entry["options"]["half_width_channels"] == 10


@pytest.mark.parametrize("order,label", [(2, "2nd"), (3, "3rd"), (4, "4th")])
def test_polynomial_labels_restore_and_serialize_as_integer_orders(page, order, label):
    """Widget labels match 1.32 AppTest serialization; the persisted scientific order remains an int."""
    observed(page.ui)
    page.ui.controls["fit_type"] = "Polynomial Peak"
    stage = fs.ensure_stage(page.ui.session_state.pipeline_data)
    stage["modes"]["Polynomial Peak"] = {"options": {"polynomial_order": order}}
    page.run()
    entry = stage["modes"]["Polynomial Peak"]
    widget_key = next(key for key, widget in page.ui.widgets.items() if widget["label"] == "Polynomial Order")
    widget = page.ui.widgets[widget_key]
    assert widget["options"] == ("2nd", "3rd", "4th")
    assert widget["value"] == label
    # This is the exact displayed-value lookup that failed inside AppTest 1.32.
    displayed = [widget["format_func"](option) for option in widget["options"]]
    assert displayed.index(str(widget["value"])) == order - 2
    assert type(entry["options"]["polynomial_order"]) is int
    assert entry["options"]["polynomial_order"] == order
    page.ui.pressed.add("fit_save")
    page.run()
    assert page.ui.saved["stages"]["fitting"]["params"]["polynomial_order"] == order

    # A pre-hotfix numeric widget may still exist in a live Streamlit session.
    # It must not replace the new string-valued widget when the page reruns.
    page.ui.session_state.pop(widget_key)
    page.ui.session_state[widget_key.removesuffix("_label")] = order
    page.run()
    assert page.ui.widgets[widget_key]["value"] == label


def test_polynomial_label_edits_refit_once_and_survive_mode_switches(page, monkeypatch):
    observed(page.ui)
    calls = []
    original = fh.run_fit_max

    def measured(*args, **kwargs):
        calls.append(args[4])
        return original(*args, **kwargs)

    monkeypatch.setattr(fh, "run_fit_max", measured)
    page.ui.controls["fit_type"] = "Polynomial Peak"
    page.run()
    assert calls == [4]
    for label, order in (("2nd", 2), ("3rd", 3), ("4th", 4)):
        page.ui.controls["Polynomial Order"] = label
        page.run()
        page.run()
        assert calls[-1] == order
    assert calls == [4, 2, 3, 4]
    page.ui.controls["fit_type"] = "Multi-Component"
    page.run()
    page.ui.controls["fit_type"] = "Polynomial Peak"
    page.run()
    assert calls == [4, 2, 3, 4]
    assert not page.ui.widgets["fit_save"]["disabled"]


def test_2d_fallback_runs_only_on_explicit_button(page, monkeypatch):
    calls = []
    real = fh.run_2d_gauss
    monkeypatch.setattr(fh, "run_2d_gauss", lambda *a, **k: (calls.append(1) or real(*a, **k)))
    page.ui.controls["fit_type"] = "2D Gaussian"
    page.run()
    assert ("info", "Synthetic Test Map Active") in page.ui.messages and not calls
    assert [t.type for t in page.ui.charts["chart_fit_2d"].data] == ["heatmap"]
    page.ui.pressed.add("fit_2d_run")
    page.run()
    assert len(calls) == 1
    entry = page.ui.session_state.pipeline_data[fs.STAGE_KEY]["modes"]["2D Gaussian"]
    assert entry["result"]["ok"] and np.asarray(entry["result"]["pcov"]).shape == (7, 7)
    assert page.ui.widgets["fit_save"]["disabled"]  # cannot commit a synthetic observation
    page.ui.session_state["theme"] = "dark"
    page.ui.session_state["font_scale"] = 200
    page.run()
    assert len(calls) == 1
    page.ui.controls["Amplitude"] = 3.5
    page.run()
    assert len(calls) == 1
    assert any("not current" in text for kind, text in page.ui.messages if kind == "warning")


def test_changed_spatial_data_never_reuses_cached_contours(page):
    page.ui.controls["fit_type"] = "2D Gaussian"
    m = fh.synthetic_map_2d()
    page.ui.session_state["map_2d_data"] = fs.json_safe(m)
    page.ui.pressed.add("fit_2d_run")
    page.run()
    assert len(page.ui.charts["chart_fit_2d"].data) == 3
    page.ui.session_state["map_2d_data"]["data"] = m.data[::-1].tolist()  # same shape and sum
    page.run()
    assert len(page.ui.charts["chart_fit_2d"].data) == 1
    assert page.ui.widgets["fit_save"]["disabled"]


def test_none_map_always_uses_synthetic_fallback_not_old_snapshot(page):
    page.ui.controls["fit_type"] = "2D Gaussian"
    page.ui.session_state["map_2d_data"] = fs.json_safe(fh.synthetic_map_2d())
    page.run()
    assert "map_snapshot" in page.ui.session_state.pipeline_data[fs.STAGE_KEY]
    page.ui.session_state["map_2d_data"] = None
    page.run()
    assert ("info", "Synthetic Test Map Active") in page.ui.messages
    assert "map_snapshot" not in page.ui.session_state.pipeline_data[fs.STAGE_KEY]


def test_multi_editor_and_manual_fit_are_button_gated(page, monkeypatch):
    observed(page.ui)
    page.ui.controls["fit_type"] = "Multi-Component"
    page.run()
    assert page.ui.editor_columns == ["Component ID", "Amplitude", "Center Velocity", "FWHM", "Fixed/Free"]
    real, calls = fh.refit_free, []
    monkeypatch.setattr(fh, "refit_free", lambda *a, **k: (calls.append(1) or real(*a, **k)))
    params = fh.renumber([dict(amplitude=9., center=-3.8, fwhm=2., fixed=False)])
    page.ui.controls[page.ui.editor_key] = fh.df_from_params(params)
    page.ui.controls["Auto-Decomposition: add components up to the stopping criteria"] = False
    page.run()
    assert not calls
    page.ui.pressed.add("fit_multicomp_run")
    page.run()
    assert len(calls) == 1
    entry = page.ui.session_state.pipeline_data[fs.STAGE_KEY]["modes"]["Multi-Component"]
    assert entry["result"]["ok"] and np.asarray(entry["result"]["covariance"]).shape == (3, 3)
    page.run()
    assert len(calls) == 1
    assert not page.ui.widgets["fit_save"]["disabled"]
    fig = page.ui.charts["chart_fit_multicomp"]
    assert any(t.yaxis == "y2" and t.name.startswith("Residual") for t in fig.data)


def test_fit_commit_writes_all_mode_state_and_invalidation_removes_overlay(page):
    observed(page.ui)
    page.run()
    page.ui.pressed.add("fit_save")
    page.run()
    assert page.ui.saved["stages"]["fitting"]["type"] == "gaussian_1d"
    assert fs.STAGE_KEY in page.ui.session_state["completed_stages"]
    assert "latest_fit" in page.ui.session_state
    page.ui.controls["HPBW (km/s, fixed)"] = 3.1
    page.run()
    assert "latest_fit" not in page.ui.session_state
    assert fs.STAGE_KEY not in page.ui.session_state["completed_stages"]


def test_real_map_can_be_committed_with_covariance_and_replay_snapshot(page):
    page.ui.controls["fit_type"] = "2D Gaussian"
    page.ui.session_state["map_2d_data"] = fs.json_safe(fh.synthetic_map_2d())
    page.ui.pressed.add("fit_2d_run")
    page.run()
    assert not page.ui.widgets["fit_save"]["disabled"]
    page.ui.pressed.add("fit_save")
    page.run()
    saved = page.ui.saved["stages"]["fitting"]
    assert saved["type"] == "gaussian_2d" and len(saved["state"]["covariance"]) == 7
    assert "map_snapshot" in saved["state"] and "latest_fit" not in page.ui.session_state


def test_invalid_map_is_reported_instead_of_silently_replacing_observations(page):
    page.ui.controls["fit_type"] = "2D Gaussian"
    page.ui.session_state["map_2d_data"] = {"data": [[1, 2]], "x": [0, 1], "y": [0]}
    page.run()
    assert any("map_2d_data must contain" in text for kind, text in page.ui.messages if kind == "error")
    assert not any(text == "Synthetic Test Map Active" for _, text in page.ui.messages)


def test_view_only_chart_keys_are_forwarded_without_changing_original_arrays(page):
    ui = page.ui
    fig = go.Figure(go.Scatter(x=[1., 2.], y=[3., 4.]))
    before = fig.to_json()
    accessibility_ui.render_plotly_chart(fig, key="chart_fit_1d", theme=None)
    assert "chart_fit_1d" in ui.charts and fig.to_json() == before
