# test_product_headers.py — presentation-only requirement-label and dark-header regression checks.
"""Check the requested header surfaces without changing data or application state."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import re
import sys
from types import ModuleType

import pytest

from utils.accessibility import accessible_theme, contrast_ratio, normalize_font_scale, relative_luminance

APP = Path(__file__).resolve().parents[2] / "hartspec_gui"
REQ_ID = re.compile(r"\b(?:FR|NFR|US)[-–‑]\d", re.IGNORECASE)


def theme_module(monkeypatch, mode="dark", scale=100):
    """Load the actual theme module without requiring a native frontend."""
    fake = ModuleType("streamlit")
    fake.session_state = {"theme": mode, "font_scale": scale}
    fake.fragments = []
    fake.markdown = lambda value, **kwargs: fake.fragments.append(value)
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    spec = importlib.util.spec_from_file_location("_product_header_styles", APP / "utils/styles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake


def dash_style_functions(styles):
    """Execute only the existing iframe style functions, without starting its server."""
    tree = ast.parse((APP / "dash_apps/baseline_editor.py").read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name in {"_root_style", "_theme_tokens"}]
    namespace = {"styles": styles, "accessible_theme": accessible_theme, "normalize_font_scale": normalize_font_scale}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "dash_style_functions", "exec"), namespace)
    return namespace


@pytest.mark.parametrize("mode,header,panel,alternate,page", [
    ("light", "#395790", "#FFFFFF", "#F8FAFC", "#FFFFFF"),
    ("dark", "#111827", "#1E293B", "#243044", "#395790"),
])
def test_only_header_fill_changes(monkeypatch, mode, header, panel, alternate, page):
    styles, _ = theme_module(monkeypatch, mode)
    theme = styles.get_theme()
    assert theme["table-header-bg"] == header
    assert theme["table-header-text"] == "#F1F5F9"
    assert theme["bg-panel"] == panel and theme["bg-panel-alt"] == alternate
    assert theme["bg-primary"] == page
    assert theme["border-default"] == ("#CBD5E1" if mode == "light" else "#334155")
    assert theme["border-subtle"] == ("#E2E8F0" if mode == "light" else "#2B3A52")
    assert styles.ACCENT == "#587BBD" and styles.HARTRAO_DARK_BLUE == "#395790"
    assert styles.LCP_COLOR == "#1F77B4" and styles.RCP_COLOR == "#FF7F0E"
    assert contrast_ratio(theme["table-header-text"], header) >= 4.5
    if mode == "dark":
        assert relative_luminance(header) < relative_luminance(panel) < relative_luminance(page)


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("scale", [100, 200])
def test_dash_header_variables_leave_canvas_fill_and_sizing_unchanged(monkeypatch, mode, scale):
    styles, _ = theme_module(monkeypatch, mode, scale)
    theme = styles.get_theme()
    result = dash_style_functions(styles)["_root_style"](mode, scale)
    assert result["backgroundColor"] == theme["bg-primary"]
    assert result["--hs-bg-panel"] == theme["bg-panel"]
    assert result["--hs-bg-panel-alt"] == theme["bg-panel-alt"]
    assert result["--hs-table-header-bg"] == theme["table-header-bg"]
    assert result["--hs-section-header-bg"] == ("#111827" if mode == "dark" else "transparent")
    assert result["--hs-root-size"] == f"{16 * scale / 100:g}px"


def test_static_ui_strings_no_longer_expose_requirement_ids():
    """Keep developer comments and docstrings, but not shipped labels/errors/help."""
    failures = []
    for path in sorted(APP.rglob("*.py")):
        if "clc" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
                    docs.add(id(node.body[0].value))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or id(node) in docs:
                continue
            text = re.sub(r"/\*.*?\*/", "", node.value, flags=re.DOTALL)
            if REQ_ID.search(text):
                failures.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert failures == []


def test_manual_and_help_have_same_requirement_free_text():
    manual = (APP.parent / "docs/user_manual/keyboard_accessibility.md").read_text(encoding="utf-8")
    assert manual == (APP / "help/keyboard_accessibility.md").read_text(encoding="utf-8")
    assert REQ_ID.search(manual) is None
    assert "not the full editable, iterative decomposition" in manual


def test_header_styles_do_not_target_the_dash_graph_or_data_cells():
    css = (APP / "dash_apps/assets/baseline_editor.css").read_text(encoding="utf-8")
    block = css.split("/* Only standalone header strips:", 1)[1].split("}", 1)[0]
    assert ".hs-dash-root > .hs-panel-title" in block
    assert ".hs-dash-root > .hs-grid-label" in block
    assert "spectrum-graph" not in block and ".hs-dash-panel" not in block and "td" not in block
    tree = ast.parse((APP / "dash_apps/baseline_editor.py").read_text(encoding="utf-8"))
    tables = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == "dash_table.DataTable"]
    assert len(tables) == 1
    header = next(kw.value for kw in tables[0].keywords if kw.arg == "style_header")
    assert ast.literal_eval(header)["backgroundColor"] == "var(--hs-table-header-bg)"
