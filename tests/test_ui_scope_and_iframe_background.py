"""Regression tests for Page 01-03 sidebar CSS isolation and Page 04 Dash iframe background."""
from __future__ import annotations

import ast
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "hartspec_gui"
MAIN_SCOPE = '[data-testid="stAppViewContainer"]'


def _read(relative: str) -> str:
    return (APP_ROOT / relative).read_text(encoding="utf-8")


def test_pages_01_to_03_scope_expander_overrides_to_main_content():
    for name in ("01_Source_Browser.py", "02_File_Loader.py", "03_Bandpass_Correction.py"):
        text = _read(f"pages/{name}")
        expander_lines = [line.strip() for line in text.splitlines() if 'stExpander"]' in line]
        assert expander_lines, f"{name} should still theme its main-content expanders"
        assert all(MAIN_SCOPE in line for line in expander_lines), (
            f"{name} has an unscoped stExpander selector that can recolor the shared sidebar: {expander_lines}"
        )


def test_page01_scopes_toggle_icon_and_text_input_overrides():
    text = _read("pages/01_Source_Browser.py")
    for token in ('stExpanderToggleIcon', 'stTextInput'):
        lines = [line.strip() for line in text.splitlines() if token in line and "data-testid" in line]
        assert lines
        assert all(MAIN_SCOPE in line for line in lines)


def test_page02_scopes_widget_labels_and_inputs():
    text = _read("pages/02_File_Loader.py")
    for token in ('stWidgetLabel', 'stTextArea', 'stTextInput'):
        lines = [line.strip() for line in text.splitlines() if token in line and "data-testid" in line]
        assert lines
        assert all(MAIN_SCOPE in line for line in lines)


def test_page03_scopes_widget_and_alert_overrides():
    text = _read("pages/03_Bandpass_Correction.py")
    for token in ('stWidgetLabel', 'stAlert'):
        lines = [line.strip() for line in text.splitlines() if token in line and "data-testid" in line]
        assert lines
        assert all(MAIN_SCOPE in line for line in lines)


def test_dash_root_fills_iframe_with_active_theme_background():
    source = _read("dash_apps/baseline_editor.py")
    tree = ast.parse(source)
    root_style = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_root_style")
    return_node = next(node for node in ast.walk(root_style) if isinstance(node, ast.Return))
    assert isinstance(return_node.value, ast.Dict)
    pairs = {
        key.value: value
        for key, value in zip(return_node.value.keys, return_node.value.values)
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert isinstance(pairs.get("backgroundColor"), ast.Subscript)
    assert ast.unparse(pairs["backgroundColor"]) == "theme['bg-primary']"
    assert isinstance(pairs.get("minHeight"), ast.Constant) and pairs["minHeight"].value == "100vh"
    assert isinstance(pairs.get("boxSizing"), ast.Constant) and pairs["boxSizing"].value == "border-box"
