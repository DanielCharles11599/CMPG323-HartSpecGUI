# test_page04_tab_boundary.py — FR-05/FR-22: accessible focus across the baseline block table.
"""Regression checks for Page 04's DataTable boundary and iframe keyboard flow."""
from __future__ import annotations

import html
import os
from pathlib import Path
import shutil

import pytest


APP = Path(__file__).resolve().parents[2] / "hartspec_gui"
ASSETS = APP / "dash_apps" / "assets"


def test_table_boundary_keeps_a_forward_and_reverse_focus_path():
    """The editor must not send Tab into Dash's spreadsheet focus trap."""
    script = (ASSETS / "accessibility.js").read_text(encoding="utf-8")
    assert 'target.id === "delete-region" && !event.shiftKey' in script
    assert 'table.querySelectorAll(' in script
    assert 'ArrowDown' in script
    assert 'focusRadioAt(nextIndex, true)' in script
    assert 'target.closest("#selection-mode")' in script
    assert 'destination.focus()' in script
    assert 'document.addEventListener("keydown", editorTableNavigation, true)' in script


def test_table_radio_focus_ring_does_not_get_removed_by_generic_css():
    """Table radios do not have enclosing labels to act as focus indicators."""
    css = (ASSETS / "baseline_editor.css").read_text(encoding="utf-8")
    assert '#block-table input[type="radio"]:focus-visible' in css
    assert '#block-table input[type="radio"]:focus' in css
    assert "outline: 2px solid var(--hs-focus-ring" in css


@pytest.mark.skipif(os.environ.get("FR22_BROWSER_TESTS") != "1", reason="Optional local Chromium test")
def test_iframe_tab_routes_through_data_table_and_back():
    """Check tab/shift-tab with an iframe and a realistic focusable Dash grid."""
    sync_api = pytest.importorskip("playwright.sync_api")
    executable = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium")
    if not executable:
        pytest.skip("Chromium not installed; set CHROMIUM_PATH")

    script = (ASSETS / "accessibility.js").read_text(encoding="utf-8")
    css = (ASSETS / "baseline_editor.css").read_text(encoding="utf-8")
    child = f"""
      <style>
        :root {{ --hs-focus-ring:#0f172a; --hs-bg-primary:#fff; }}
        {css}
      </style>
      <div id="root" class="hs-dash-root" style="--hs-root-size:16px; --hs-bg-primary:#fff">
        <a class="hs-skip-link" href="#region-controls">Skip chart</a>
        <div id="region-controls">
          <div id="region-choice"><input aria-label="Region to edit"></div>
          <input id="region-start" aria-label="Start velocity">
          <input id="region-end" aria-label="End velocity">
          <button id="add-region">Add flat region</button>
          <button id="update-region">Update selected</button>
          <button id="delete-region">Delete selected</button>
        </div>
        <div id="block-table" class="dash-table-container">
          <table><tbody>
            <tr><td><input type="radio" name="table-radio" aria-label="Region 1"></td></tr>
            <tr><td><input type="radio" name="table-radio" aria-label="Region 2" checked></td></tr>
          </tbody></table>
          <div tabindex="0" id="grid-cell" aria-label="data grid cell">Grid focus trap</div>
        </div>
        <div id="selection-mode">
          <label><input type="radio" name="poly-mode" value="auto" checked>Automatic</label>
          <label><input type="radio" name="poly-mode" value="manual">Manual</label>
        </div>
        <button id="fit-polynomial">Fit Polynomial</button>
        <p id="editor-end" tabindex="0">End of editor</p>
      </div>
      <script>{script}</script>
    """
    outer = (
        '<button id="before">Before editor</button>'
        '<iframe id="dash" title="Baseline editor" srcdoc="' + html.escape(child, quote=True) + '"></iframe>'
        '<button id="after">After editor</button>'
    )
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=executable, headless=True, args=["--no-sandbox"]
        )
        try:
            page = browser.new_page(viewport={"width": 1360, "height": 900})
            page.set_content(outer)
            frame = page.frame_locator("#dash")
            delete = frame.locator("#delete-region")
            delete.focus()
            page.keyboard.press("Tab")
            chosen = frame.locator('input[name="table-radio"]:checked')
            assert chosen.evaluate("e => document.activeElement === e")
            assert chosen.evaluate("e => getComputedStyle(e).outlineWidth") == "2px"

            page.keyboard.press("Tab")  # selected last -> first row
            first = frame.locator('input[name="table-radio"]').first
            assert first.evaluate("e => document.activeElement === e")
            page.keyboard.press("Tab")  # now past all table rows
            mode = frame.locator('input[name="poly-mode"]:checked')
            assert mode.evaluate("e => document.activeElement === e")
            page.keyboard.press("Shift+Tab")
            assert chosen.evaluate("e => document.activeElement === e")
            page.keyboard.press("Shift+Tab")
            first = frame.locator('input[name="table-radio"]').first
            assert first.evaluate("e => document.activeElement === e")
            page.keyboard.press("Shift+Tab")
            assert delete.evaluate("e => document.activeElement === e")

            for _ in range(4):
                page.keyboard.press("Tab")
            assert frame.locator("#fit-polynomial").evaluate("e => document.activeElement === e")
            page.keyboard.press("Tab")
            assert frame.locator("#editor-end").evaluate("e => document.activeElement === e")
            page.keyboard.press("Tab")
            assert page.locator("#after").evaluate("e => document.activeElement === e")
            page.keyboard.press("Shift+Tab")
            assert frame.locator("#editor-end").evaluate("e => document.activeElement === e")
        finally:
            browser.close()
