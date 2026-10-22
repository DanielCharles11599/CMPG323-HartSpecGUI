# test_ui_spacing_theme.py — regression checks for Page 04 iframe spacing and sidebar session contrast.
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "hartspec_gui"


def test_page4_iframe_is_compact_and_has_no_extra_streamlit_spacer():
    path = APP / "pages" / "04_Baseline_Editor.py"
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    assignments = {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
    }
    assert assignments["IFRAME_HEIGHT"] == 880
    assert "height:{styles.SECTION_GAP}px" not in text


def test_pages_01_to_03_scope_native_widget_theme_away_from_sidebar():
    """Page-local widget CSS must target only the main view, never stSidebar."""
    for name in ("01_Source_Browser.py", "02_File_Loader.py", "03_Bandpass_Correction.py"):
        text = (APP / "pages" / name).read_text(encoding="utf-8")
        assert '[data-testid="stAppViewContainer"] [data-testid="stExpander"]' in text
        assert '[data-testid="stExpander"] summary,' not in text.replace(
            '[data-testid="stAppViewContainer"] [data-testid="stExpander"] summary,', ""
        )
