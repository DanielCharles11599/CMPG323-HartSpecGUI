# test_product_headers_browser.py — header-only CSS checks at normal and enlarged text sizes.
"""Synthetic DOM using real CSS; these checks are not full Streamlit/Dash UAT."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from test_browser_smoke import page
from test_product_headers import dash_style_functions, theme_module
from utils import export_page_ui

_PAGE_FIXTURE_REFERENCE = page
APP = Path(__file__).resolve().parents[2] / "hartspec_gui"
pytestmark = pytest.mark.skipif(os.environ.get("FR22_BROWSER_TESTS") != "1", reason="Browser checks are opt-in")


def colour(element):
    """Get an element's opaque computed background as a hex colour."""
    rgb = element.evaluate("e => getComputedStyle(e).backgroundColor")
    channels = rgb.removeprefix("rgb(").removesuffix(")").split(",")
    return "#" + "".join(f"{int(channel):02X}" for channel in channels)


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("scale", [100, 200])
def test_streamlit_header_strips_not_body_or_borders(page, monkeypatch, mode, scale):
    styles, ui = theme_module(monkeypatch, mode, scale)
    styles.inject_base_css()
    theme = styles.get_theme()
    html = "".join(ui.fragments) + f'''<style>{export_page_ui.page_css(theme)}</style>
      <div class="stApp"><div class="hs-panel">
      <div id="panel-title" class="hs-panel-title">Source browser</div><p id="body">Unchanged body</p></div>
      <div data-testid="stMarkdownContainer"><h2 class="hs-export-section-title">Observation log</h2></div>
      <div class="hs-accessible-table" tabindex="0"><table><thead><tr><th>Metric</th></tr></thead>
      <tbody><tr><td id="row1">North–South</td></tr><tr><td id="row2">East–West</td></tr></tbody></table></div></div>'''
    page.set_content(html)
    assert colour(page.locator(".hs-panel")) == theme["bg-panel"]
    assert page.locator(".hs-panel").evaluate("e => getComputedStyle(e).borderTopWidth") == "1px"
    assert colour(page.locator("#row2")) == theme["bg-panel-alt"]
    for selector in (".hs-accessible-table th", ".hs-export-section-title"):
        assert colour(page.locator(selector)) == theme["table-header-bg"]
    if mode == "dark":
        assert colour(page.locator("#panel-title")) == "#111827"
    else:
        assert page.locator("#panel-title").evaluate("e => getComputedStyle(e).backgroundColor") == "rgba(0, 0, 0, 0)"
        assert page.locator("#panel-title").evaluate("e => getComputedStyle(e).padding") == "0px"
    assert page.locator("#panel-title").evaluate("e => e.scrollHeight <= e.clientHeight")


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("scale", [100, 200])
def test_marked_baseline_header_only(page, monkeypatch, mode, scale):
    styles, _ = theme_module(monkeypatch, mode, scale)
    theme = styles.get_theme()
    root = dash_style_functions(styles)["_root_style"](mode, scale)
    variables = ";".join(f"{key}:{value}" for key, value in root.items() if key.startswith("--"))
    css = (APP / "dash_apps/assets/baseline_editor.css").read_text(encoding="utf-8")
    page.set_content(f'''<style>html{{font-size:{16 * scale / 100}px}}{css}</style>
      <div class="hs-dash-root" style="{variables}">
      <h2 class="hs-panel-title">Baseline editor</h2><div class="hs-selection-feedback">Saved checkpoint</div>
      <div class="hs-dash-panel hs-canvas-panel"><div id="caption" class="hs-panel-title">Select baseline regions</div>
      <div id="plot" style="height:150px;background:var(--hs-bg-panel)">Spectrum</div></div>
      <div class="hs-keyboard-tools"><table><thead><tr><th>Sample</th></tr></thead><tbody><tr><td>1</td></tr></tbody>
      </table></div></div>''')
    assert colour(page.locator(".hs-canvas-panel")) == theme["bg-panel"]
    assert colour(page.locator("#plot")) == theme["bg-panel"]
    assert page.locator("#caption").evaluate("e => getComputedStyle(e).backgroundColor") == "rgba(0, 0, 0, 0)"
    assert colour(page.locator(".hs-keyboard-tools th")) == theme["table-header-bg"]
    title = page.locator(".hs-dash-root > h2")
    if mode == "dark":
        assert colour(title) == "#111827"
    else:
        assert title.evaluate("e => getComputedStyle(e).backgroundColor") == "rgba(0, 0, 0, 0)"
        assert title.evaluate("e => getComputedStyle(e).padding") == "0px"
    assert title.evaluate("e => e.scrollWidth <= e.clientWidth")
