# test_surface_borders.py — dark decorative edges; no data, controls or light-mode changes.
"""Exercise the actual shared theme and iframe HTML without starting a server."""
from __future__ import annotations

import ast
import html
from pathlib import Path
import re
from typing import Mapping

import pandas as pd
import pytest

from test_product_headers import dash_style_functions, theme_module

APP = Path(__file__).resolve().parents[2] / "hartspec_gui"
BORDER_CSS = APP / "utils/dark_surface_borders.css"


def header_html(styles, frame):
    """Run only the real FITS table renderer; no file loading or Streamlit app."""
    tree = ast.parse((APP / "pages/02_File_Loader.py").read_text(encoding="utf-8-sig"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_header_table_html"]
    assert len(nodes) == 1
    namespace = {
        "styles": styles, "pd": pd, "html": html, "Mapping": Mapping,
        "HEADER_TABLE_HEIGHT": 240, "HEADER_TABLE_ROW_HEIGHT": 28,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "header_html", "exec"), namespace)
    return namespace["_header_table_html"](frame, styles.get_theme())


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("fallback", ["border-default", "border-subtle"])
def test_surface_colour_does_not_mutate_the_palette(monkeypatch, mode, fallback):
    styles, ui = theme_module(monkeypatch, mode)
    theme = styles.get_theme()
    original = dict(theme)
    state = dict(ui.session_state)
    colour = styles.surface_border_colour(theme, fallback)
    assert colour == ("#111827" if mode == "dark" else theme[fallback])
    assert theme == original
    assert ui.session_state == state
    assert theme["border-subtle"] == ("#2B3A52" if mode == "dark" else "#E2E8F0")
    assert theme["border-default"] == ("#334155" if mode == "dark" else "#CBD5E1")


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("scale", [100, 200])
def test_border_css_is_injected_only_for_dark_mode(monkeypatch, mode, scale):
    styles, ui = theme_module(monkeypatch, mode, scale)
    state = dict(ui.session_state)
    styles.inject_base_css()
    css = BORDER_CSS.read_text(encoding="utf-8")
    assert (css in "".join(ui.fragments)) == (mode == "dark")
    assert ui.session_state == state
    assert 'border-color: var(--hs-control-border)' in "".join(ui.fragments)


def test_decorative_overrides_do_not_style_controls_fills_or_geometry():
    css = re.sub(r"/\*.*?\*/", "", BORDER_CSS.read_text(encoding="utf-8"), flags=re.DOTALL)
    bodies = re.findall(r"\{([^{}]*)\}", css)
    assert len(bodies) == 2
    assert all(body.strip() == "border-color: var(--hs-table-header-bg, #111827) !important;" for body in bodies)
    for name in ("button", "input", "select", "textarea", "focus", "svg", "canvas"):
        assert re.search(rf"\b{name}\b", css) is None


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_dash_border_property_does_not_repurpose_axes_or_control_tokens(monkeypatch, mode):
    styles, _ = theme_module(monkeypatch, mode)
    theme = styles.get_theme()
    root = dash_style_functions(styles)["_root_style"](mode, 100)
    assert root["--hs-surface-border"] == styles.surface_border_colour(theme)
    for name in ("bg-primary", "bg-panel", "bg-panel-alt", "border-default", "border-subtle", "control-border",
                 "focus-ring", "table-header-bg", "table-header-text"):
        assert root[f"--hs-{name}"] == theme[name]


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_fits_iframe_changes_only_the_outer_border_colour(monkeypatch, mode):
    styles, _ = theme_module(monkeypatch, mode)
    theme = styles.get_theme()
    frame = pd.DataFrame({"Object": ["<unchanged & escaped>", "second row"], "Value": [1.23456789, 3.0]})
    before = frame.copy(deep=True)
    text = header_html(styles, frame)
    wrap = re.search(r"(?<![\w-])\.wrap \{([^}]+)\}", text).group(1)
    expected = "#111827" if mode == "dark" else theme["border-subtle"]
    assert f"border:1px solid {expected};" in wrap
    assert f"background:{theme['bg-panel']}" in wrap
    assert f"border-bottom:1px solid {theme['border-subtle']}" in text
    assert f"outline:3px solid {theme['control-border']}" in text
    assert "&lt;unchanged &amp; escaped&gt;" in text
    assert "1.23456789" in text
    assert 'tabindex="0"' in text
    pd.testing.assert_frame_equal(frame, before)
