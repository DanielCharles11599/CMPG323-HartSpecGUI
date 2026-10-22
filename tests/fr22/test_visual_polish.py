# test_visual_polish.py — FR-22: readable controls, safe help links and truthful fit notes.
from __future__ import annotations

import ast
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from utils.accessibility_help import help_link_html, help_preferences, read_help_text

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "hartspec_gui"


class LinkParser(HTMLParser):
    """Read generated link attributes without evaluating HTML."""

    def __init__(self, text):
        super().__init__()
        self.attributes = {}
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        if tag == "a":
            self.attributes = dict(attributes)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("scale", [100, 125, 150, 175, 200])
def test_manual_link_only_contains_display_preferences(theme, scale):
    attributes = LinkParser(help_link_html(theme, scale, base_path="/hartspec/")).attributes
    url = urlsplit(attributes["href"])
    assert url.path == "/hartspec/Keyboard_Help"
    assert parse_qs(url.query) == {"display_theme": [theme], "display_font_scale": [str(scale)]}
    assert not url.netloc and not url.fragment
    assert attributes["target"] == "_blank"
    assert set(attributes["rel"].split()) == {"noopener", "noreferrer"}


@pytest.mark.parametrize("query,expected", [
    ({}, ("light", 100)),
    ({"display_theme": "dark", "display_font_scale": "200", "recovery": "private"}, ("dark", 200)),
    ({"display_theme": ["dark"], "display_font_scale": "bad"}, ("light", 100)),
    ({"display_theme": "<script>", "display_font_scale": "125.5"}, ("light", 100)),
    ({"display_font_scale": True}, ("light", 100)),
    ({"display_font_scale": "999999"}, ("light", 100)),
])
def test_help_preferences_are_allowlisted(query, expected):
    assert help_preferences(query) == expected


def test_help_page_does_not_load_or_write_reductions():
    text = (APP / "pages/Keyboard_Help.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    assert "read_help_text()" in text and "styles.inject_base_css()" in text
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert "session_store" not in ast.unparse(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"recover_checkpoint", "load_session", "save_session", "checkpoint_session"}
    sidebar = (APP / "utils/sidebar.py").read_text(encoding="utf-8")
    stage_node = next(node for node in ast.parse(sidebar).body
                      if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "STAGES")
    assert len(stage_node.value.elts) == 8
    assert 'st.expander("Keyboard and accessibility help")' not in sidebar
    assert "help_link_html" in sidebar


def test_bundled_manual_and_documentation_chapter_match():
    assert read_help_text() == (ROOT / "docs/user_manual/keyboard_accessibility.md").read_text(encoding="utf-8")
    for term in ["Shift + Tab", "Region to edit", "Table page", "Graph 4", "three-component"]:
        assert term in read_help_text()


def test_bandpass_continue_is_primary_and_keeps_its_existing_key():
    tree = ast.parse((APP / "pages/03_Bandpass_Correction.py").read_text(encoding="utf-8"))
    node = next(node for node in ast.walk(tree) if isinstance(node, ast.Call) and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "Continue to Baseline Block Editor →")
    kwargs = {item.arg: ast.literal_eval(item.value) for item in node.keywords}
    assert kwargs["type"] == "primary" and kwargs["key"] == "continue_to_baseline"


def test_sidebar_does_not_force_a_colour_on_all_descendants():
    text = (APP / "utils/styles.py").read_text(encoding="utf-8")
    assert '[data-testid="stSidebar"] *' not in text
    css = (APP / "utils/accessibility.css").read_text(encoding="utf-8")
    assert '[data-baseweb="select"] :is(div, span, svg)' in css
    assert 'input:is([type="checkbox"], [type="radio"]):focus-visible' in css
    assert '0 0 0 6px' not in css
    assert 'caret-color: var(--hs-text-body)' in css


def test_fitting_modes_describe_real_spatial_and_iterative_models():
    text = (APP / "pages/07_Spectral_Fitting.py").read_text(encoding="utf-8")
    assert "def _map_fit" in text and "fh.run_2d_gauss" in text
    assert "Synthetic Test Map Active" in text
    assert "fh.run_auto_decomposition" in text
    assert "not a spatial 2D Gaussian fit" not in text
    assert "fixed three-component Gaussian fit" not in text
