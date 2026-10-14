# test_visual_polish_browser.py — FR-22 synthetic DOM checks, not native Streamlit UAT.
"""Opt in with FR22_BROWSER_TESTS=1 and an installed Chromium/Playwright."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType

import pytest

# The existing browser module skips cleanly when optional Playwright is absent.
from test_browser_smoke import page
from playwright.sync_api import Error as BrowserError
from utils.accessibility import contrast_ratio
from utils.accessibility_help import help_link_html

_PAGE_FIXTURE_REFERENCE = page
APP = Path(__file__).resolve().parents[2] / "hartspec_gui"
pytestmark = pytest.mark.skipif(os.environ.get("FR22_BROWSER_TESTS") != "1", reason="Browser checks are opt-in")


def rgb_hex(value):
    """Convert a computed opaque rgb() value for contrast measurement."""
    channels = value.removeprefix("rgb(").removesuffix(")").split(",")
    return "#" + "".join(f"{int(channel.strip()):02X}" for channel in channels)


def fixture_html(monkeypatch, theme, scale):
    """Use actual app CSS around deliberately synthetic BaseWeb-like elements."""
    ui = ModuleType("streamlit")
    ui.session_state = {"theme": theme, "font_scale": scale}
    fragments = []
    ui.markdown = lambda text, **kwargs: fragments.append(text)
    monkeypatch.setitem(sys.modules, "streamlit", ui)
    spec = importlib.util.spec_from_file_location("_fr22_visual_styles", APP / "utils/styles.py")
    styles = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(styles)
    styles.inject_base_css()
    link = help_link_html(theme, scale, base_path="/hartspec")
    return "".join(fragments) + '''
        <style>
        body { margin:0; font-family:Arial,sans-serif; }
        .stApp { display:flex; min-height:100vh; }
        aside { padding:1rem; box-sizing:border-box; flex-shrink:0; }
        main { padding:2rem; min-width:0; flex:1; }
        h1 { font-size:1.5rem; } p { line-height:1.6; }
        button { padding:.5rem .75rem; cursor:pointer; }
        button p { margin:0; }
        [data-baseweb="select"] > div {
          border:1px solid; display:flex; align-items:center; padding:.5rem;
          gap:.2rem; margin-block:.5rem 1.25rem;
        }
        [data-baseweb="select"] input { width:2px; padding:0; font-size:1rem; }
        [data-baseweb="select"] svg { margin-left:auto; width:1rem; height:1rem; }
        #close { display:block; margin-left:auto; }
        #close svg, #reopen svg { height:1rem; width:1rem; }
        .radio { display:inline-flex; align-items:center; padding:.375rem; border-radius:6px; }
        .radio input { opacity:0; position:absolute; width:1px; height:1px; }
        .radio span::before { content:'●'; margin-right:.5rem; }
        [data-testid="stExpander"] details { padding:.5rem; margin-top:1rem; }
        </style>
        <div class="stApp">
        <aside data-testid="stSidebar">
          <button id="close" kind="header" data-testid="baseButton-header" aria-label="Close sidebar">
            <svg viewBox="0 0 24 24"><path d="M14 4L6 12L14 20L16 18L10 12L16 6Z"/></svg>
          </button>
          <h2 style="color:white;font-size:1.125rem">HARTSPEC</h2>
          <div data-testid="stWidgetLabel"><p>Font size (%)</p></div>
          <div data-baseweb="select" id="font-select"><div id="font-control">
            <div id="font-value">''' + str(scale) + '''</div>
            <input id="font-search" role="combobox" aria-label="Font size (%)" autocomplete="off">
            <svg viewBox="0 0 24 24"><path d="M6 9L12 15L18 9Z"/></svg>
          </div></div>''' + link + '''
          <div data-testid="stExpander"><details open><summary>Load Session</summary>
            <div data-testid="stMarkdownContainer"><p>Press <strong>Enter</strong> to open a session.</p></div>
          </details></div>
        </aside>
        <main>
          <div data-testid="collapsedControl"><button id="reopen" aria-label="Open sidebar">
            <svg viewBox="0 0 24 24"><path d="M8 4L16 12L8 20L6 18L12 12L6 6Z"/></svg>
          </button></div>
          <h1>Control styling verification</h1>
          <p>Synthetic layout using the application's shared CSS. Not a native Streamlit render.</p>
          <label class="radio" id="radio-label"><input id="fit-radio" type="radio" name="fit" checked>
            <span>2D Gaussian</span></label>
          <div data-testid="stWidgetLabel"><p>Event order</p></div>
          <div data-baseweb="select" id="event-select"><div id="event-control">
            <div id="event-value">Original recorded order</div>
            <input id="event-search" role="combobox" aria-label="Event order">
            <svg viewBox="0 0 24 24"><path d="M6 9L12 15L18 9Z"/></svg>
          </div></div>
          <button id="continue" data-testid="baseButton-primary"><p>Continue to Baseline Block Editor →</p></button>
        </main></div>'''


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("scale", [100, 200])
def test_field_text_icons_and_single_control_focus(page, monkeypatch, theme, scale):
    page.set_content(fixture_html(monkeypatch, theme, scale))
    font_color = page.locator("#font-value").evaluate("e => getComputedStyle(e).color")
    font_bg = page.locator("#font-control").evaluate("e => getComputedStyle(e).backgroundColor")
    assert contrast_ratio(rgb_hex(font_color), rgb_hex(font_bg)) >= 4.5
    sidebar_bg = page.locator("aside").evaluate("e => getComputedStyle(e).backgroundColor")
    close_fill = page.locator("#close svg").evaluate("e => getComputedStyle(e).fill")
    assert contrast_ratio(rgb_hex(close_fill), rgb_hex(sidebar_bg)) >= 3
    # Programmatic focus after a keyboard key matches Chromium's focus-visible heuristic.
    page.keyboard.press("Tab")
    page.locator("#font-search").focus()
    assert page.locator("#font-search").evaluate("e => getComputedStyle(e).outlineStyle") == "none"
    assert page.locator("#font-control").evaluate("e => getComputedStyle(e).outlineWidth") == "2px"
    assert page.locator("#font-control").evaluate("e => getComputedStyle(e).boxShadow") == "none"
    assert page.locator("#font-control").evaluate("e => getComputedStyle(e).outlineOffset") == "-2px"
    assert page.locator("#font-search").evaluate("e => getComputedStyle(e).caretColor") == font_color
    page.locator("#fit-radio").focus()
    assert page.locator("#fit-radio").evaluate("e => getComputedStyle(e).outlineStyle") == "none"
    assert page.locator("#radio-label").evaluate("e => getComputedStyle(e).outlineWidth") == "2px"
    page.locator("#event-search").focus()
    assert page.locator("#event-search").evaluate("e => getComputedStyle(e).outlineStyle") == "none"
    assert page.locator("#event-control").evaluate("e => getComputedStyle(e).outlineWidth") == "2px"
    assert page.locator("#continue").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(88, 123, 189)"
    text = page.locator("#continue p").evaluate("e => getComputedStyle(e).color")
    assert contrast_ratio(rgb_hex(text), "#587BBD") >= 4.5
    assert page.locator(".hs-help-link").evaluate("e => e.scrollWidth <= e.clientWidth")
    screenshot_dir = os.environ.get("FR22_SCREENSHOT_DIR")
    if screenshot_dir:
        output = Path(screenshot_dir)
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / f"controls_{theme}_{scale}.png"), full_page=True)


def test_help_keyboard_link_opens_new_tab_without_copying_private_query(page, monkeypatch):
    html = fixture_html(monkeypatch, "dark", 150)
    page.context.route(
        "http://127.0.0.1:8765/**",
        lambda route: route.fulfill(status=200, body=html, content_type="text/html"),
    )
    original_url = "http://127.0.0.1:8765/hartspec/Bandpass_Correction?recovery=private-do-not-copy"
    try:
        page.goto(original_url)
    except BrowserError as exc:
        if "ERR_BLOCKED_BY_ADMINISTRATOR" in str(exc):
            pytest.skip("This Chromium environment blocks navigation, including intercepted localhost routes")
        raise
    page.locator(".hs-help-link").focus()
    with page.expect_popup() as opened:
        page.keyboard.press("Enter")
    popup = opened.value
    popup.wait_for_load_state()
    assert "/hartspec/Keyboard_Help?" in popup.url
    assert "display_theme=dark" in popup.url and "display_font_scale=150" in popup.url
    assert "private" not in popup.url and "recovery" not in popup.url
    assert page.url == original_url
    assert popup.evaluate("window.opener === null")
    popup.close()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_dash_select_focus_is_on_the_whole_control_not_search_input(page, theme):
    css = (APP / "dash_apps/assets/baseline_editor.css").read_text(encoding="utf-8")
    background, text = ("#FFFFFF", "#000000") if theme == "light" else ("#1E293B", "#FFFFFF")
    page.set_content(f'''<style>{css}</style>
        <div class="hs-dash-root" style="--hs-focus-ring:{text}; --hs-text-body:{text};
             --hs-bg-panel:{background}; --hs-control-border:{text}">
        <div class="Select"><div class="Select-control" id="dash-control">
          <span class="Select-value-label">Region 1</span>
          <span class="Select-input"><input id="dash-input" aria-label="Region to edit"></span>
        </div></div></div>''')
    page.keyboard.press("Tab")
    assert page.locator("#dash-input").evaluate("e => e === document.activeElement")
    assert page.locator("#dash-input").evaluate("e => getComputedStyle(e).outlineStyle") == "none"
    assert page.locator("#dash-control").evaluate("e => getComputedStyle(e).outlineWidth") == "2px"
    assert page.locator("#dash-control").evaluate("e => getComputedStyle(e).outlineOffset") == "-2px"
    assert page.locator("#dash-control").evaluate("e => getComputedStyle(e).boxShadow") == "none"
