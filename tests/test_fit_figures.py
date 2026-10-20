# test_fit_figures.py — unit tests for utils/fit_figures.py (Page 07 graphs; FR-14/15/17).
#
# Builds figures from plain dicts, so no Streamlit runtime is needed -- only plotly. Asserts the plotted data, colours,
# dash styles, subplot layout and window highlight, not pixels.

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hartspec_gui"))

from utils import fit_figures, fitting_helpers  # noqa: E402

THEME = {"bg-panel": "#FFFFFF", "text-body": "#334155", "text-muted": "#64748B", "border-default": "#CBD5E1",
         "accent": "#587BBD"}
LAYOUT = {}  # styles.plotly_layout_theme() output is theme styling only; not needed to test data/structure
FIT_RED = "#DC2626"
V = np.linspace(-20, 20, 1024)
PARAMS = fitting_helpers.renumber([
    {"amplitude": 8.0, "center": -5.0, "fwhm": 2.0, "fixed": False},
    {"amplitude": 4.0, "center": 6.0, "fwhm": 3.0, "fixed": False},
])


def _y(seed=0):
    rng = np.random.default_rng(seed)
    return fitting_helpers.composite(V, PARAMS) + rng.normal(0, 0.15, V.size)


def _by_name(fig, prefix):
    return [t for t in fig.data if (t.name or "").startswith(prefix)]


def _multi(params=PARAMS, y=None):
    return fit_figures.multi_figure(V, _y() if y is None else y, params, "Jy", THEME, LAYOUT,
                                    data_color="#4B5563", fit_color=FIT_RED)


# ---- spectrum_figure ------------------------------------------------------------------------------------------
def test_spectrum_figure_traces_colours_and_dash():
    fig = fit_figures.spectrum_figure(
        [("Graph 3", V, _y(), "#4B5563", "solid"), ("Fit", V, _y(), FIT_RED, "dash")], "Intensity (Jy)", THEME, LAYOUT)
    assert [t.name for t in fig.data] == ["Graph 3", "Fit"]
    assert fig.data[1].line.color == FIT_RED and fig.data[1].line.dash == "dash"
    assert fig.layout.xaxis.title.text == "Vlsr (km/s)" and fig.layout.yaxis.title.text == "Intensity (Jy)"
    assert fig.layout.paper_bgcolor == THEME["bg-panel"] and fig.layout.plot_bgcolor == THEME["bg-panel"]
    assert fig.layout.legend.title.text and "km/s" in fig.data[0].hovertemplate


def test_spectrum_figure_highlights_window_only_when_given():
    plain = fit_figures.spectrum_figure([("s", V, _y(), "#000", "solid")], "I", THEME, LAYOUT)
    assert len(plain.layout.shapes) == 0
    fig = fit_figures.spectrum_figure([("s", V, _y(), "#000", "solid")], "I", THEME, LAYOUT, window=(-2.0, -8.0))
    assert len(fig.layout.shapes) == 1
    shape = fig.layout.shapes[0]
    assert (shape.x0, shape.x1) == (-8.0, -2.0) and shape.opacity == fit_figures.WINDOW_FILL_OPACITY


def test_spectrum_figure_keeps_nan_gaps_for_windowed_fit():
    curve = np.full(V.size, np.nan)
    curve[500:520] = 1.0
    fig = fit_figures.spectrum_figure([("Fit", V, curve, FIT_RED, "dash")], "I", THEME, LAYOUT)
    assert np.isnan(np.asarray(fig.data[0].y, dtype=float)).sum() == V.size - 20


def test_spectrum_figure_ignores_non_finite_hline_and_window():
    fig = fit_figures.spectrum_figure([("s", V, _y(), "#000", "solid")], "I", THEME, LAYOUT, hline=float("nan"),
                                      window=(float("nan"), 1.0))
    assert len(fig.layout.shapes) == 0


# ---- multi_figure ---------------------------------------------------------------------------------------------
def test_multi_figure_top_panel_has_observed_components_and_dashed_red_composite():
    fig = _multi()
    top = [t for t in fig.data if t.yaxis in (None, "y")]
    assert top[0].name.startswith("Observed") and top[0].line.dash in (None, "solid")
    comps = _by_name(fig, "Comp")
    assert len(comps) == 2 and all(c.line.dash == "dot" and c.line.width <= 1 for c in comps)
    assert len({c.line.color for c in comps}) == 2  # visually distinct
    composite = _by_name(fig, "Composite")[0]
    assert composite.line.color == FIT_RED and composite.line.dash == "dash"
    assert np.allclose(composite.y, fitting_helpers.composite(V, PARAMS))


def test_multi_figure_residual_panel_is_data_minus_model_with_zero_and_sigma_lines():
    y = _y()
    fig = _multi(y=y)
    bottom = [t for t in fig.data if t.yaxis == "y2"]
    resid = _by_name(fig, "Residual")[0]
    assert resid.yaxis == "y2" and np.allclose(resid.y, y - fitting_helpers.composite(V, PARAMS))
    zero = _by_name(fig, "Zero")[0]
    assert list(zero.y) == [0.0, 0.0] and zero.yaxis == "y2"
    sigma = fitting_helpers.estimate_noise(y)
    plus, minus = _by_name(fig, "+σ"), _by_name(fig, "−σ")
    assert len(plus) == 1 and len(minus) == 1 and len(bottom) == 4
    assert np.allclose(plus[0].y, [sigma, sigma]) and np.allclose(minus[0].y, [-sigma, -sigma])
    assert plus[0].line.dash == "dash" and minus[0].line.dash == "dash"


def test_multi_figure_layout_matches_spec():
    fig = _multi()
    top, bottom = fig.layout.yaxis.domain, fig.layout.yaxis2.domain
    assert abs((top[1] - top[0]) / (bottom[1] - bottom[0]) - 0.7 / 0.3) < 0.01
    assert abs(top[0] - bottom[1] - 0.05) < 1e-6  # vertical_spacing
    assert fig.layout.xaxis.matches == "x2" or fig.layout.xaxis2.matches == "x"  # shared x axis
    assert fig.layout.xaxis2.title.text == "Vlsr (km/s)"
    assert "Jy" in fig.layout.yaxis.title.text and "Jy" in fig.layout.yaxis2.title.text
    assert fig.layout.legend.title.text


def test_multi_figure_with_no_components_draws_data_and_residual_without_composite():
    fig = _multi(params=[])
    assert not _by_name(fig, "Composite") and not _by_name(fig, "Comp")
    assert np.allclose(_by_name(fig, "Residual")[0].y, _y())


def test_multi_figure_omits_sigma_lines_when_noise_cannot_be_estimated():
    fig = fit_figures.multi_figure(V[:2], np.array([1.0, 2.0]), [], "K", THEME, LAYOUT, data_color="#4B5563",
                                   fit_color=FIT_RED)
    assert not _by_name(fig, "+σ") and not _by_name(fig, "−σ")
    flat = fit_figures.multi_figure(V, np.zeros(V.size), PARAMS[:1], "K", THEME, LAYOUT, data_color="#4B5563",
                                    fit_color=FIT_RED)
    assert not _by_name(flat, "+σ")  # zero noise -> no degenerate band


# ---- map_figure (FR-16) -------------------------------------------------------------------------------------------
def _map_fig(model=True):
    z = np.arange(12.0).reshape(3, 4)
    return fit_figures.map_figure(z, np.arange(4.0), np.arange(3.0), z * 0.9 if model else None, "Intensity (K)",
                                  "arcmin", THEME, LAYOUT, fit_color=FIT_RED)


def test_map_figure_has_heatmap_with_red_contour_overlay():
    fig = _map_fig()
    assert [type(t).__name__ for t in fig.data] == ["Heatmap", "Contour"]
    heat, contour = fig.data
    assert np.asarray(heat.z).shape == (3, 4) and heat.name == "Observed map"
    assert contour.line.color == FIT_RED and contour.contours.coloring == "none" and contour.showscale is False
    assert contour.name == "2D Gaussian fit"
    assert "arcmin" in fig.layout.xaxis.title.text and "arcmin" in fig.layout.yaxis.title.text
    assert fig.layout.paper_bgcolor == THEME["bg-panel"]


def test_map_figure_without_a_fit_shows_only_the_heatmap():
    assert [type(t).__name__ for t in _map_fig(model=False).data] == ["Heatmap"]
