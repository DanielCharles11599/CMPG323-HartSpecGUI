# test_wiring.py — FR-22 static contracts for version-pinned application integration.
from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "hartspec_gui"


def source(relative: str) -> str:
    return (APP / relative).read_text(encoding="utf-8")


def test_every_page_injects_shared_styles_and_charts_use_the_shared_adapter():
    for path in (APP / "pages").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "styles.inject_base_css()" in text
        tree = ast.parse(text)
        assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                       and isinstance(node.func.value, ast.Name) and node.func.value.id == "st"
                       and node.func.attr in ("plotly_chart", "dataframe") for node in ast.walk(tree)), path.name


def test_keyboard_css_does_not_hide_native_sidebar_reopen_control():
    css = source("utils/accessibility.css")
    assert ":focus-visible" in css and "label:has(input:focus-visible)" in css
    assert "#MainMenu, footer, header" not in source("utils/styles.py")
    assert "collapsedControl" in css
    assert "flex-wrap: wrap" in css
    assert "hs-skip-link" in source("utils/sidebar.py")
    assert 'id="hs-main-content" tabindex="-1"' in source("utils/styles.py")


def test_dash_carries_scale_in_bridge_and_frame_revision():
    page = source("pages/04_Baseline_Editor.py")
    assert "font_scale=styles.get_font_scale()" in page
    assert '{styles.get_theme_name()}-{styles.get_font_scale()}' in page
    assert "scrolling=True" in page
    bridge = source("utils/baseline_editor_bridge.py")
    assert '"font_scale": normalize_font_scale(font_scale)' in bridge
    dash = source("dash_apps/baseline_editor.py")
    assert 'State("region-choice", "value")' in dash
    assert 'htmlFor="region-start"' in dash and 'htmlFor="region-end"' in dash
    assert 'id="editor-end", tabIndex=0' in dash
    assert 'Input("view-range-store", "data")' in dash
    assert "scaled_figure(spectrum_fig, scale)" in dash


def test_display_preferences_checkpoint_without_replaying_widget_keys():
    store = source("utils/session_store.py")
    assert '"preferences": preferences(state)' in store
    assert 'restore_preferences(state, data.get("preferences"))' in store
    sidebar = source("utils/sidebar.py")
    assert 'st.session_state["font_scale"]' in sidebar
    assert 'st.session_state["_a11y_font_scale"]' in sidebar
    assert 'checkpoint_session("Display font size changed", allow_empty=True)' in sidebar


def test_shared_helpers_can_be_used_inside_an_existing_expander():
    assert "st.expander(" not in source("utils/accessibility_ui.py")


def test_local_js_never_traps_keys_or_accesses_parent_document():
    js = source("dash_apps/assets/accessibility.js")
    assert "MutationObserver" in js and "aria-label" in js
    for bad in ("parent.document", "top.document", "preventDefault", "keydown", "fetch(", "https://"):
        assert bad not in js


def test_header_table_has_keyboard_scrolling_and_no_truncated_hover_only_values():
    page = source("pages/02_File_Loader.py")
    tree = ast.parse(page)
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_header_table_html")
    text = ast.get_source_segment(page, function)
    assert 'tabindex="0" role="region"' in text
    assert "styles.get_font_scale()" in text
    assert "white-space:normal" in text
