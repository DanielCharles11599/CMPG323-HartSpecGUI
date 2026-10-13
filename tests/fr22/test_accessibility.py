# test_accessibility.py — FR-22 display policy, contrast and non-mutation checks.
from __future__ import annotations

import ast
import copy
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
import pytest

from utils.accessibility import (
    FONT_SCALES, accessible_theme, contrast_ratio, normalize_font_scale, preferences,
    region_options, restore_preferences, selected_region_index, validate_view_range,
)
from utils.accessibility_plotly import axis_bounds, inspected_value, scaled_figure

APP = Path(__file__).resolve().parents[2] / "hartspec_gui"


def design_tokens():
    """Read literal approved tables without requiring Streamlit to be installed."""
    tree = ast.parse((APP / "utils/styles.py").read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") in ("THEMES", "STATUS_BADGES"):
            expression = ast.Expression(node.value)
            values[node.target.id] = eval(compile(expression, "<tokens>", "eval"), {"__builtins__": {}}, values)
    return values


@pytest.mark.parametrize("value", FONT_SCALES)
def test_supported_scales(value):
    assert normalize_font_scale(value) == value
    assert normalize_font_scale(float(value)) == value


@pytest.mark.parametrize("value", [None, True, False, "200", "100;display:none", [], {}, float("nan"),
                                   float("inf"), -200, 0, 99, 101, 300])
def test_invalid_scale_cannot_inject_css(value):
    assert normalize_font_scale(value) == 100


def test_preferences_are_separate_from_pipeline_and_restore_safely():
    state = {"theme": "dark", "font_scale": 175, "pipeline_data": {"fit": [1.3]}, "auth": "keep"}
    original = copy.deepcopy(state)
    assert preferences(state) == {"theme": "dark", "font_scale": 175}
    restore_preferences(state, {"theme": "light", "font_scale": 200, "auth": "overwrite"})
    assert state["pipeline_data"] == original["pipeline_data"] and state["auth"] == "keep"
    assert state["font_scale"] == 200 and state["theme"] == "light"
    restore_preferences(state, {"theme": "invalid", "font_scale": "tiny"})
    restore_preferences(state, {})
    restore_preferences(state, None)
    assert state["font_scale"] == 200 and state["theme"] == "light"


@pytest.mark.parametrize("name", ["light", "dark"])
def test_text_and_controls_pass_contrast_on_owned_surfaces(name):
    tokens = design_tokens()
    base = tokens["THEMES"][name]
    original = copy.deepcopy(base)
    theme = accessible_theme(base)
    assert base == original
    for text in ("text-body", "text-heading", "text-muted", "text-faint"):
        for background in ("bg-primary", "bg-panel", "bg-panel-alt"):
            assert contrast_ratio(theme[text], theme[background]) >= 4.5, (text, background)
    assert contrast_ratio(theme["sidebar-text-inactive"], theme["bg-sidebar"]) >= 4.5
    assert contrast_ratio(theme["text-on-accent"], theme["accent"]) >= 4.5
    for background in ("bg-primary", "bg-panel", "bg-panel-alt"):
        assert contrast_ratio(theme["control-border"], theme[background]) >= 3
    assert theme["accent"] == "#587BBD"
    assert tokens["LCP_COLOR"] == "#1F77B4" and tokens["RCP_COLOR"] == "#FF7F0E"
    for fill, text in tokens["STATUS_BADGES"][name].values():
        assert contrast_ratio(text, fill) >= 4.5


def test_contrast_formula_known_values_no_rounding():
    assert contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21)
    assert contrast_ratio("#587BBD", "#FFFFFF") < 4.5
    assert contrast_ratio("#587BBD", "#000000") > 4.5


@pytest.mark.parametrize(
    "first,last",
    [(0, 0), (5, 2), (float("nan"), 3), (0, float("inf")),
     ("x", 3), (False, 2), (None, 2)],
)
def test_reject_invalid_view_limits(first, last):
    with pytest.raises(ValueError):
        validate_view_range(first, last)


def test_view_limits_are_not_scientific_selection():
    assert validate_view_range("-1.23", "4.56789") == (-1.23, 4.56789)


def test_region_selector_uses_exact_indices_and_rejects_stale_values():
    rows = [{"start": -1.2, "end": 0.5}, {"start": 2.0, "end": 3.1}]
    saved = copy.deepcopy(rows)
    options = region_options(rows)
    assert options[1]["value"] == 1 and "2.0 to 3.1" in options[1]["label"]
    assert selected_region_index(1, rows) == 1
    for bad in (True, None, -1, 2, "1", 1.5):
        with pytest.raises(ValueError):
            selected_region_index(bad, rows)
    assert rows == saved


@pytest.mark.parametrize("scale", FONT_SCALES)
def test_plot_scaling_is_copy_only_and_scales_explicit_overrides(scale):
    figure = go.Figure(
        go.Scatter(x=np.arange(3), y=np.array([1.23456789, 4.0, 6.0]),
                   line={"color": "#1F77B4"}, name="LCP")
    )
    figure.update_layout(height=270, font={"size": 10}, margin={"l": 40, "b": 30},
                         xaxis={"tickfont": {"size": 8}, "title": {"text": "Vlsr", "font": {"size": 11}},
                                "range": [0, 2]}, annotations=[{"text": "exact", "x": 1, "y": 4,
                                                               "font": {"size": 12}}])
    before = figure.to_json()
    result = scaled_figure(figure, scale)
    assert figure.to_json() == before
    assert result.layout.font.size == 10 * scale / 100
    assert result.layout.xaxis.tickfont.size == 8 * scale / 100
    assert result.layout.annotations[0].font.size == 12 * scale / 100
    assert result.layout.height == round(270 * scale / 100)
    assert result.layout.xaxis.range == figure.layout.xaxis.range
    np.testing.assert_array_equal(result.data[0].y, figure.data[0].y)
    assert result.data[0].line.color == "#1F77B4"


def test_numeric_date_and_category_axis_bounds():
    assert axis_bounds(go.Figure(go.Scatter(x=[3, 2, float("nan"), 1], y=[1, 2, 3, 4])), "x") == (1, 3, "number")
    assert axis_bounds(go.Figure(go.Scatter(x=["2026-01-01", "2026-01-03"], y=[2, 3])), "x") == (
        "2026-01-01", "2026-01-03", "date")
    assert axis_bounds(go.Figure(go.Scatter(x=["LCP", "RCP"], y=[2, 3])), "x") is None
    assert axis_bounds(go.Figure(), "x") is None


def test_point_and_heatmap_inspectors_are_exact_not_interpolated():
    trace = go.Scatter(x=[-2.3, 1.1], y=[1.23456789, 7.890123], text=["first", "second"])
    assert inspected_value(trace, 1) == {"X": 1.1, "Y": 7.890123, "Annotation": "second"}
    heatmap = go.Heatmap(x=[-1, 2], y=[3, 4], z=[[1, 2], [3, 4]])
    assert inspected_value(heatmap, 1, 0) == {"X": -1, "Y": 4, "Z": 3}
    with pytest.raises(ValueError):
        inspected_value(trace, 2)
