# test_export_page_polish_browser.py — FR-22: synthetic browser checks for Page 08 CSS.
"""Opt-in component checks, not a native Streamlit application acceptance test."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType

import pandas as pd
import pytest

from test_browser_smoke import page
from utils import export_page_ui
from utils.accessibility import contrast_ratio
from utils.accessibility_help import help_link_html

_PAGE_FIXTURE_REFERENCE = page
APP = Path(__file__).resolve().parents[2] / "hartspec_gui"
pytestmark = pytest.mark.skipif(os.environ.get("FR22_BROWSER_TESTS") != "1", reason="Browser checks are opt-in")


def rgb_hex(value):
    """Read a computed opaque RGB colour for contrast checks."""
    channels = value.removeprefix("rgb(").removesuffix(")").split(",")
    return "#" + "".join(f"{int(channel.strip()):02X}" for channel in channels)


def fixture_html(monkeypatch, mode, scale):
    """Render real application CSS/helper HTML around a synthetic Streamlit-like DOM."""
    fake = ModuleType("streamlit")
    fake.session_state = {"theme": mode, "font_scale": scale}
    fragments = []
    fake.markdown = lambda text, **kwargs: fragments.append(text)
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    spec = importlib.util.spec_from_file_location("_fr22_export_browser_styles", APP / "utils/styles.py")
    styles = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(styles)
    styles.inject_base_css()
    theme = styles.get_theme()
    title = "Final calibrated LCP/RCP preview — CLC RMS and peak"
    table = export_page_ui.review_table_html(
        pd.DataFrame({"Entry": range(50), "Timestamp (recorded)": ["19:39:20"] * 50,
                      "Message": ["Synthetic entry — a long filename and its original recorded message."] * 50,
                      "Record note": [""] * 50}),
        "Synthetic observation events", height=240,
    )
    return "".join(fragments) + f'''<style>{export_page_ui.page_css(theme)}
        body {{ margin:0; font-family:Arial,sans-serif; }}
        .stApp {{ padding:1.5rem; min-height:100vh; }}
        #outer {{ max-width:1100px; margin:auto; }}
        [data-testid="stVerticalBlock"] {{ display:flex; flex-direction:column; gap:1rem; }}
        [data-testid="stSidebar"] {{ padding:1rem; margin-top:1.5rem; }}
        </style><div class="stApp"><main id="outer" data-testid="stVerticalBlockBorderWrapper">
        <div data-testid="stVerticalBlock">
          <div data-testid="stMarkdownContainer"><h1>Export &amp; Session</h1>
            <p>Page 08 CSS verification — synthetic component data, not an observation.</p></div>
          <div id="card" data-testid="stVerticalBlockBorderWrapper"><div data-testid="stVerticalBlock">
            <div class="element-container"><div data-testid="stMarkdownContainer">
              <h2 class="hs-export-section-title">{title}</h2></div></div>
            <div class="element-container"><div data-testid="stMarkdownContainer">
              <p>Chart controls and charts belong inside this panel.</p></div></div>
          </div></div>
          <div id="log" data-testid="stVerticalBlockBorderWrapper"><div data-testid="stVerticalBlock">
            <div class="element-container"><div data-testid="stMarkdownContainer">
              <h2 class="hs-export-section-title">Observation log</h2></div></div>
            <div class="element-container"><div data-testid="stMarkdownContainer">{table}</div></div>
          </div></div>
          <aside data-testid="stSidebar">{help_link_html(mode, scale)}</aside>
        </div></main></div>'''


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("scale", [100, 200])
def test_export_headers_wrap_focus_scroll_and_help_label(page, monkeypatch, mode, scale):
    page.set_content(fixture_html(monkeypatch, mode, scale))
    header = page.locator("#card h2")
    th = page.locator(".hs-export-review-table th").first
    for element in (header, th):
        fg = rgb_hex(element.evaluate("e => getComputedStyle(e).color"))
        bg = rgb_hex(element.evaluate("e => getComputedStyle(e).backgroundColor"))
        assert bg == ("#395790" if mode == "light" else "#111827") and fg == "#F1F5F9"
        assert contrast_ratio(fg, bg) >= 4.5
    for cell in (page.locator("tbody tr").nth(0).locator("td").first,
                 page.locator("tbody tr").nth(1).locator("td").first):
        fg = rgb_hex(cell.evaluate("e => getComputedStyle(e).color"))
        bg = rgb_hex(cell.evaluate("e => getComputedStyle(e).backgroundColor"))
        assert contrast_ratio(fg, bg) >= 4.5
    assert header.evaluate("e => e.scrollWidth <= e.clientWidth")
    assert page.locator("#outer").evaluate("e => getComputedStyle(e).padding") == "0px"
    assert page.locator("#card").evaluate("e => getComputedStyle(e).padding") == f"{scale * 16 // 100}px"
    table = page.locator(".hs-export-review-table")
    assert table.evaluate("e => e.scrollHeight > e.clientHeight")
    page.keyboard.press("Tab")
    table.focus()
    assert table.evaluate("e => e === document.activeElement")
    assert table.evaluate("e => getComputedStyle(e).outlineWidth") == "2px"
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(200)
    assert table.evaluate("e => e.scrollTop") > 0
    assert th.evaluate("e => getComputedStyle(e).position") == "sticky"
    link = page.locator(".hs-help-link")
    assert link.inner_text() == "Keyboard and accessibility help"
    assert link.get_attribute("target") == "_blank"
    assert "opens in a new tab" in link.get_attribute("aria-label")
    assert page.locator(".hs-help-hint").count() == 0
    output = os.environ.get("FR22_SCREENSHOT_DIR")
    if output:
        Path(output).mkdir(parents=True, exist_ok=True)
        table.evaluate("e => { e.scrollTop = 0; e.blur(); }")
        page.screenshot(path=str(Path(output) / f"export_{mode}_{scale}.png"), full_page=True)
