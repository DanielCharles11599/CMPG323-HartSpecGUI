# test_browser_smoke.py — FR-22 isolated HTML/CSS/JS checks, NOT full-application UAT.
"""Opt in with FR22_BROWSER_TESTS=1; uses a local Chromium, no browser download."""
from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest

pytest.importorskip("playwright.sync_api", reason="Optional isolated browser smoke tests")
from playwright.sync_api import sync_playwright  # noqa: E402

APP = Path(__file__).resolve().parents[2] / "hartspec_gui"
pytestmark = pytest.mark.skipif(os.environ.get("FR22_BROWSER_TESTS") != "1", reason="Browser checks are opt-in")


@pytest.fixture
def page():
    executable = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium")
    if not executable:
        pytest.skip("Set CHROMIUM_PATH to an installed Chromium browser")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable, headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        yield page
        browser.close()


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_owned_css_scaling_and_visible_keyboard_focus(page, mode):
    css = (APP / "utils/accessibility.css").read_text(encoding="utf-8")
    background, text = ("#FFFFFF", "#334155") if mode == "light" else ("#1E293B", "#FFFFFF")
    page.set_content(f'''<style>:root {{ --hs-root-size:16px; --hs-bg-panel:{background};
        --hs-text-body:{text}; --hs-focus-ring:{text};
        --hs-sidebar-width:220px; --hs-text-on-accent:#000000; }}{css}</style>
        <div class="stApp" style="background:{background}">
        <a class="hs-skip-link" href="#hs-main-content">Skip to page content</a>
        <div class="hs-page-header"><h1 id="hs-main-content" tabindex="-1">Baseline regions</h1></div>
        <button id="action" data-testid="baseButton-primary"><p>Apply chart view</p></button>
        <input id="velocity" aria-label="Start velocity" value="-12.4"></div>''')
    assert page.locator("#action p").evaluate("e => getComputedStyle(e).fontSize") == "12px"
    page.keyboard.press("Tab")
    assert page.locator(".hs-skip-link").evaluate("e => e === document.activeElement")
    page.keyboard.press("Enter")
    assert page.locator("#hs-main-content").evaluate("e => e === document.activeElement")
    page.keyboard.press("Tab")
    assert page.locator("#action").evaluate("e => e === document.activeElement")
    assert page.locator("#action").evaluate("e => getComputedStyle(e).outlineWidth") == "2px"
    assert page.locator("#action").evaluate("e => getComputedStyle(e).boxShadow") == "none"
    page.evaluate("document.documentElement.style.setProperty('--hs-root-size', '32px')")
    assert page.locator("#action p").evaluate("e => getComputedStyle(e).fontSize") == "24px"
    assert page.locator("#action").evaluate("e => e.scrollHeight <= e.clientHeight")


def test_dash_document_local_scaling_and_input_names(page):
    script = (APP / "dash_apps/assets/accessibility.js").read_text(encoding="utf-8")
    page.set_content('''<div id="root" style="--hs-root-size:32px; --hs-bg-primary:#395790;">
        <div id="region-choice"><input></div><div id="manual-order-lcp"><input></div>
        <div id="manual-order-rcp"><input></div></div>''')
    page.add_script_tag(content=script)
    page.wait_for_function("getComputedStyle(document.documentElement).fontSize === '32px'")
    assert page.locator("#region-choice input").get_attribute("aria-label") == "Region to edit"
    assert page.locator("#manual-order-lcp input").get_attribute("aria-label") == "LCP polynomial order"
    page.evaluate("document.getElementById('root').style.setProperty('--hs-root-size', '20px')")
    page.wait_for_function("getComputedStyle(document.documentElement).fontSize === '20px'")
    page.evaluate('''window.styleMutations = 0; new MutationObserver(m => window.styleMutations += m.length)
        .observe(document.body, {attributes: true, attributeFilter: ['style']})''')
    page.wait_for_timeout(150)
    assert page.evaluate("window.styleMutations") == 0


def test_region_dropdown_tab_and_shift_tab_escape_react_focus_trap(page):
    """Intercept only Tab on the region dropdown; preserve regular keyboard focus order."""
    script = (APP / "dash_apps/assets/accessibility.js").read_text(encoding="utf-8")
    page.set_content('''
      <div id="root" style="--hs-root-size:16px; --hs-bg-primary:#ffffff">
        <a class="hs-skip-link" href="#region-controls">Skip chart</a>
        <div id="spectrum-graph" tabindex="0">Spectrum</div>
        <div id="region-controls">
          <label for="region-choice-input">Region to edit</label>
          <div id="region-choice" class="Select"><input id="region-choice-input"></div>
          <input id="region-start" aria-label="Start velocity">
          <input id="region-end" aria-label="End velocity">
        </div>
      </div>''')
    # Mimic a component consuming Tab at the React bubbling phase.
    page.evaluate('''document.getElementById('region-choice').addEventListener('keydown',
      function (event) { if (event.key === 'Tab') { event.preventDefault(); } });''')
    page.add_script_tag(content=script)
    region = page.locator("#region-choice input")
    region.focus()
    page.keyboard.press("Tab")
    assert page.locator("#region-start").evaluate("e => document.activeElement === e")
    region.focus()
    page.keyboard.press("Shift+Tab")
    assert page.locator("#spectrum-graph").evaluate("e => document.activeElement === e")
    # The script must not interfere with Tab on numeric inputs.
    page.locator("#region-start").focus()
    page.keyboard.press("Tab")
    assert page.locator("#region-end").evaluate("e => document.activeElement === e")
