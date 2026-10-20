# fit_figures.py — FR-14/15/16/17: Plotly figure builders for Page 07 (spectrum + fit overlay, dual panel).
#
# Streamlit-free so the figures can be unit-tested: callers pass the active theme token dict and the dict returned by
# styles.plotly_layout_theme(theme). Backgrounds are set explicitly from the theme's bg-panel token because Plotly
# does not inherit them from injected CSS (Build Spec §2).
from __future__ import annotations

import math
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from utils import fitting_helpers

# Distinct hues for the individual Gaussian components -- none is LCP blue, RCP orange or fit red.
COMPONENT_COLORS = ("#2CA02C", "#9467BD", "#8C564B", "#E377C2", "#17BECF", "#BCBD22")
WINDOW_FILL_OPACITY = 0.15


def _hover(name: str, y_title: str) -> str:
    """Hover tooltip showing the trace name, velocity and intensity with units."""
    return f"<b>{name}</b><br>Vlsr: %{{x:.3f}} km/s<br>{y_title}: %{{y:.4g}}<extra></extra>"


def _apply_theme(fig: go.Figure, theme: Mapping[str, str], layout_theme: Mapping[str, Any], height: int,
                 legend_y: float) -> None:
    """Shared chart styling: themed backgrounds, no gridlines, legend with a title."""
    fig.update_layout(**layout_theme)
    fig.update_layout(
        height=height, margin=dict(l=40, r=20, t=10, b=40),
        paper_bgcolor=theme["bg-panel"], plot_bgcolor=theme["bg-panel"],
        font=dict(color=theme["text-body"]),
        legend=dict(orientation="h", y=legend_y, title_text="Series"),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False, zeroline=False, color=theme["text-muted"])
    fig.update_yaxes(showgrid=False, zeroline=False, color=theme["text-muted"])


def spectrum_figure(traces: Sequence[tuple[str, Any, Any, str, str]], y_title: str, theme: Mapping[str, str],
                    layout_theme: Mapping[str, Any], *, height: int = 280, hline: Optional[float] = None,
                    window: Optional[tuple[float, float]] = None) -> go.Figure:
    """Themed line chart. ``traces`` = (name, x, y, colour, dash); ``window`` = (v_lo, v_hi) in km/s to highlight.

    NaN values in a trace leave a gap (used for a polynomial fitted over a window only).
    """
    fig = go.Figure()
    for name, x, y, color, dash in traces:
        fig.add_scatter(x=x, y=y, mode="lines", line=dict(color=color, width=1.6, dash=dash), name=name,
                        hovertemplate=_hover(name, y_title))
    if hline is not None and np.isfinite(hline):
        fig.add_hline(y=hline, line=dict(color=theme["text-muted"], width=1, dash="dot"))
    if window is not None and all(np.isfinite(window)):
        fig.add_vrect(x0=min(window), x1=max(window), fillcolor=theme["accent"], opacity=WINDOW_FILL_OPACITY,
                      line_width=0, layer="below")
    _apply_theme(fig, theme, layout_theme, height, legend_y=-0.25)
    fig.update_xaxes(title_text="Vlsr (km/s)")
    fig.update_yaxes(title_text=y_title)
    return fig


def multi_figure(v: np.ndarray, y: np.ndarray, params: fitting_helpers.Params, unit_label: str,
                 theme: Mapping[str, str], layout_theme: Mapping[str, Any], *, data_color: str,
                 fit_color: str) -> go.Figure:
    """Dual-panel multi-component plot (FR-17).

    Top: observed spectrum (solid), each Gaussian G_i(v) (thin dotted), composite sum (dashed ``fit_color``).
    Bottom: residual (data - composite, solid), the y = 0 reference and dashed +/- sigma_RMS noise lines. sigma_RMS is
    ``fitting_helpers.estimate_noise(y)`` -- the same noise estimate the termination criteria use.
    """
    v = np.asarray(v, dtype=float)
    y = np.asarray(y, dtype=float)
    y_title = f"Intensity ({unit_label})"
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    fig.add_scatter(x=v, y=y, mode="lines", name="Observed (Graph 3)", line=dict(color=data_color, width=1.6),
                    hovertemplate=_hover("Observed (Graph 3)", y_title), row=1, col=1)
    for i, (p, curve) in enumerate(zip(params, fitting_helpers.component_curves(v, params))):
        fig.add_scatter(x=v, y=curve, mode="lines", name=f"{p['id']} G(v)",
                        line=dict(color=COMPONENT_COLORS[i % len(COMPONENT_COLORS)], width=1, dash="dot"),
                        hovertemplate=_hover(p["id"], y_title), row=1, col=1)
    model = fitting_helpers.composite(v, params)
    if params:
        fig.add_scatter(x=v, y=model, mode="lines", name="Composite fit ΣG(v)",
                        line=dict(color=fit_color, width=1.6, dash="dash"),
                        hovertemplate=_hover("Composite fit", y_title), row=1, col=1)
    residual_title = f"Residual ({unit_label})"
    fig.add_scatter(x=v, y=y - model, mode="lines", name="Residual (data − model)",
                    line=dict(color=theme["text-body"], width=1.2),
                    hovertemplate=_hover("Residual", residual_title), row=2, col=1)
    if v.size:
        span = [float(v.min()), float(v.max())]
        fig.add_scatter(x=span, y=[0.0, 0.0], mode="lines", name="Zero baseline", hoverinfo="skip",
                        line=dict(color=theme["border-default"], width=1), row=2, col=1)
        sigma = fitting_helpers.estimate_noise(y)
        if math.isfinite(sigma) and sigma > 0:
            for sign, label in ((1, "+σ_RMS"), (-1, "−σ_RMS")):
                fig.add_scatter(x=span, y=[sign * sigma] * 2, mode="lines", name=f"{label} ({sigma:.3g} {unit_label})",
                                line=dict(color=theme["text-muted"], width=1, dash="dash"),
                                hovertemplate=f"{label}: {sign * sigma:.4g} {unit_label}<extra></extra>",
                                row=2, col=1)
    _apply_theme(fig, theme, layout_theme, height=460, legend_y=-0.15)
    fig.update_xaxes(title_text="Vlsr (km/s)", row=2, col=1)
    fig.update_yaxes(title_text=y_title, row=1, col=1)
    fig.update_yaxes(title_text=residual_title, row=2, col=1)
    return fig


def map_figure(z: np.ndarray, x: np.ndarray, y: np.ndarray, model: Optional[np.ndarray], z_title: str,
               axis_unit: str, theme: Mapping[str, str], layout_theme: Mapping[str, Any], *,
               fit_color: str, dashed_contours: bool = False) -> go.Figure:
    """FR-16: heatmap of the observed 2D map with the fitted 2D Gaussian drawn as contour lines on top.

    ``z`` and ``model`` have shape (Ny, Nx). The contour lines use ``coloring="none"`` because Plotly ignores
    ``line.color`` when the contours are coloured by the colour scale.
    """
    fig = go.Figure()
    fig.add_trace(go.Heatmap(z=z, x=x, y=y, colorscale="Viridis", name="Observed map",
                             colorbar=dict(title=dict(text=z_title)),
                             hovertemplate="X: %{x:.3f}<br>Y: %{y:.3f}<br>" + z_title + ": %{z:.4g}<extra></extra>"))
    if model is not None:
        fig.add_trace(go.Contour(z=model, x=x, y=y, showscale=False, contours=dict(coloring="none"),
                                 line=dict(color=fit_color, width=2), name="2D Gaussian fit", showlegend=True,
                                 hovertemplate="Fit: %{z:.4g}<extra></extra>"))
    if model is not None and dashed_contours:
        # Plotly 5.20 Contour.line has no dash property. Keep its z/hover trace,
        # and draw the same level sets as dashed Scatter paths (no science refit).
        from matplotlib.figure import Figure
        surface = np.asarray(model, dtype=float)
        low, high = float(surface.min()), float(surface.max())
        if high > low:
            levels = np.linspace(low, high, 9)[1:-1]
            contour = fig.data[1]
            contour.update(line_width=0, showlegend=False,
                           contours=dict(start=float(levels[0]), end=float(levels[-1]),
                                         size=float(levels[1] - levels[0]), coloring="none"))
            scratch = Figure()
            axes = scratch.subplots()
            paths = axes.contour(x, y, surface, levels=levels)
            xs, ys = [], []
            for segments in paths.allsegs:
                for segment in segments:
                    xs.extend(segment[:, 0].tolist() + [None])
                    ys.extend(segment[:, 1].tolist() + [None])
            scratch.clear()
            fig.add_scatter(x=xs, y=ys, mode="lines", name="2D Gaussian fit (dashed)",
                            line=dict(color=fit_color, dash="dash", width=1.6), hoverinfo="skip")
    _apply_theme(fig, theme, layout_theme, height=420, legend_y=-0.2)
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(title_text=f"X offset ({axis_unit})")
    fig.update_yaxes(title_text=f"Y offset ({axis_unit})")
    return fig
