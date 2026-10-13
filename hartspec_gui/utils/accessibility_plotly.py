# accessibility_plotly.py — FR-22: presentation-only Plotly font scaling and value inspection.
"""Operate on copies. No fitting, calibration, smoothing or selection math lives here."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from math import isfinite
from numbers import Real
from typing import Any

from utils.accessibility import normalize_font_scale


def scaled_figure(figure: Any, percentage: int = 100):
    """Copy a Plotly figure and scale explicit text/margins after page overrides.

    Plotly renders SVG/canvas text rather than inheriting the app's CSS root size.
    Applying this once, at the rendering boundary, also covers annotation/tick
    overrides on individual pages. Trace values/colours and axis ranges are kept.
    """
    import plotly.graph_objects as go
    factor = normalize_font_scale(percentage) / 100
    result = go.Figure(figure)
    if factor == 1:
        return result
    layout = result.layout.to_plotly_json()

    def visit(value: Any, parent: str = "") -> None:
        if isinstance(value, dict):
            if parent.endswith("font") and isinstance(value.get("size"), Real):
                value["size"] *= factor
            for key, item in value.items():
                # Do not scale template defaults as well as explicit figure fonts.
                if key != "template":
                    visit(item, key)
        elif isinstance(value, list):
            for item in value:
                visit(item, parent)

    visit(layout)
    # Keep x/y/z array objects out of the JSON conversion entirely. Newer Plotly
    # versions can encode arrays; a display-only adapter must preserve values.
    for trace in result.data:
        for key in ("textfont", "hoverlabel"):
            value = getattr(trace, key, None)
            if value is not None and hasattr(value, "to_plotly_json"):
                item = value.to_plotly_json()
                visit(item, key)
                trace.update(**{key: item})
    if isinstance(layout.get("height"), Real):
        layout["height"] = round(layout["height"] * factor)
    for key in ("l", "r", "t", "b"):
        if isinstance(layout.get("margin", {}).get(key), Real):
            layout["margin"][key] = round(layout["margin"][key] * factor)
    result.update_layout(layout)
    return result


def trace_sequence(trace: Any, name: str) -> list:
    """Read array-like trace coordinates without ambiguous NumPy truth tests."""
    value = getattr(trace, name, None)
    if value is None:
        return []
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value) if not isinstance(value, (str, bytes, Mapping)) else []


def axis_bounds(figure: Any, axis: str) -> tuple[Any, Any, str] | None:
    """Return numeric/date limits for the main x/y axis, or None for categories."""
    values = []
    for trace in figure.data:
        if getattr(trace, f"{axis}axis", None) in (None, axis):
            values.extend(trace_sequence(trace, axis))
    if not values:
        return None
    if all(isinstance(value, Real) for value in values):
        finite = [float(v) for v in values if isfinite(v)]
        if not finite:
            return None
        lower, upper = min(finite), max(finite)
        if lower == upper:
            delta = abs(lower) * 0.05 or 1.0
            lower, upper = lower - delta, upper + delta
        return lower, upper, "number"
    try:
        dates = [v.isoformat() if isinstance(v, (date, datetime)) else str(v) for v in values]
        parsed = [datetime.fromisoformat(v) for v in dates]
        return dates[parsed.index(min(parsed))], dates[parsed.index(max(parsed))], "date"
    except (ValueError, TypeError):
        return None


def inspected_value(trace: Any, index: int, column: int = 0) -> dict[str, Any]:
    """Expose the same stored chart values without requiring a mouse hover.

    Heatmap/contour rows use row+column indexing. Indices are zero-based here;
    the UI labels the first sample as 1. No interpolation/rounding is performed.
    """
    x, y, z = (trace_sequence(trace, key) for key in ("x", "y", "z"))
    if z:
        if not 0 <= index < len(z) or not 0 <= column < len(z[index]):
            raise ValueError("Choose an existing chart row and column.")
        return {"X": x[column] if column < len(x) else column,
                "Y": y[index] if index < len(y) else index, "Z": z[index][column]}
    size = max(len(x), len(y))
    if not 0 <= index < size:
        raise ValueError("Choose an existing chart sample.")
    result = {"X": x[index] if index < len(x) else index, "Y": y[index] if index < len(y) else None}
    text = trace_sequence(trace, "text")
    if index < len(text):
        result["Annotation"] = text[index]
    return result
