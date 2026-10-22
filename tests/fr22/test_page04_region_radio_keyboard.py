# test_page04_region_radio_keyboard.py — FR-05/FR-22: keyboard selection of baseline table rows.
"""Exercise the table-radio keyboard actions without changing scientific code."""
from __future__ import annotations

import html
import os
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[2] / "hartspec_gui"
SCRIPT = ROOT / "dash_apps" / "assets" / "accessibility.js"


def test_table_radios_handle_arrows_space_and_individual_tab_stops():
    """Selection is dispatched through the real radio click, not a visual-only highlight."""
    code = SCRIPT.read_text(encoding="utf-8")
    assert 'key === "ArrowDown"' in code
    assert 'key === "ArrowUp"' in code
    assert 'key === "Home"' in code and 'key === "End"' in code
    assert 'focusRadioAt(nextIndex, true)' in code
    assert 'radio.click()' in code
    assert 'nextRadioTabStop(radios, index, event.shiftKey)' in code
    assert 'visitedRadioIndices' in code
    assert 'event.stopImmediatePropagation()' in code
    assert 'document.getElementById("delete-region")' in code
    assert 'polynomialModeRadio()' in code
    assert 'radio.setAttribute("aria-label"' in code
    assert 'event.preventDefault()' in code


@pytest.mark.skipif(os.environ.get("FR22_BROWSER_TESTS") != "1", reason="Optional Chromium test")
def test_keyboard_can_select_another_row_and_sync_velocity_inputs_in_iframe():
    """Reproduce the seven-row case: selected last, arrow wrap, and row-by-row Tab."""
    sync_api = pytest.importorskip("playwright.sync_api")
    browser_path = os.environ.get("CHROMIUM_PATH") or shutil.which("chromium")
    if not browser_path:
        pytest.skip("Chromium not installed; set CHROMIUM_PATH")

    script = SCRIPT.read_text(encoding="utf-8")
    child = """
      <style>:root { --hs-bg-primary:#fff; }</style>
      <div id="root">
        <a href="#region-controls" class="hs-skip-link">Skip</a>
        <div id="region-controls">
          <div id="region-choice"><input aria-label="Region to edit" value="Region 7"></div>
          <input id="region-start" value="-52.1">
          <input id="region-end" value="-51">
          <button id="add-region">Add flat region</button>
          <button id="update-region">Update selected</button>
          <button id="delete-region">Delete selected</button>
        </div>
        <div id="block-table"><table><tbody>
          <tr><td><input type="radio" name="table-row-0" data-row="0"></td><td>-48.5</td></tr>
          <tr><td><input type="radio" name="table-row-1" data-row="1"></td><td>-43</td></tr>
          <tr><td><input type="radio" name="table-row-2" data-row="2"></td><td>-39.1</td></tr>
          <tr><td><input type="radio" name="table-row-3" data-row="3"></td><td>-33.6</td></tr>
          <tr><td><input type="radio" name="table-row-4" data-row="4"></td><td>-45.3</td></tr>
          <tr><td><input type="radio" name="table-row-5" data-row="5"></td><td>-50</td></tr>
          <tr><td><input type="radio" name="table-row-6" data-row="6" checked></td><td>-52.1</td></tr>
        </tbody></table></div>
        <div id="selection-mode"><label><input type="radio" name="poly" checked>Automatic</label>
         <label><input type="radio" name="poly">Manual</label></div>
        <button id="fit-polynomial">Fit Polynomial</button>
        <p id="editor-end" tabindex="0">End</p>
      </div>
      <script>
        const rows = [
          [-48.5, -47.2], [-43, -40.9], [-39.1, -36.6], [-33.6, -32.1],
          [-45.3, -44.3], [-50, -48.6], [-52.1, -51]
        ];
        document.querySelector('#block-table').addEventListener('click', function (ev) {
          if (!ev.target.matches('input[type="radio"]')) return;
          let index = Number(ev.target.dataset.row);
          document.querySelectorAll('#block-table input[type="radio"]').forEach(function (radio) {
            radio.checked = Number(radio.dataset.row) === index;
          });
          // A stand-in for the real Dash selected_rows -> region-choice callback.
          document.querySelector('#region-choice input').value = 'Region ' + (index + 1);
          document.getElementById('region-start').value = rows[index][0];
          document.getElementById('region-end').value = rows[index][1];
          window.lastDashSelectedRow = index;
        });
      </script>
      <script>""" + script + "</script>"
    outer = ('<button id="before">Before</button><iframe id="editor" srcdoc="' +
             html.escape(child, quote=True) + '"></iframe><button id="after">After</button>')
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=browser_path, headless=True, args=["--no-sandbox"]
        )
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_content(outer)
            frame = page.frame_locator("#editor")
            radios = frame.locator('#block-table input[type="radio"]')
            delete = frame.locator("#delete-region")
            mode = frame.locator('#selection-mode input[type="radio"]').first
            delete.focus()

            page.keyboard.press("Tab")
            assert radios.nth(6).evaluate("e => e === document.activeElement")
            page.keyboard.press("ArrowDown")  # last row wraps to first
            assert radios.nth(0).is_checked()
            assert radios.nth(0).evaluate("e => e === document.activeElement")
            assert frame.locator('#region-choice input').input_value() == "Region 1"
            assert frame.locator("#region-start").input_value() == "-48.5"
            assert frame.locator("#region-end").input_value() == "-47.2"

            page.keyboard.press("Tab")  # focus row 2, do not select yet
            assert radios.nth(1).evaluate("e => e === document.activeElement")
            assert radios.nth(0).is_checked()
            page.keyboard.press("Space")  # Space commits row 2
            assert radios.nth(1).is_checked()
            assert frame.locator('#region-choice input').input_value() == "Region 2"
            page.keyboard.press("ArrowUp")
            assert radios.nth(0).is_checked()
            page.keyboard.press("End")
            assert radios.nth(6).is_checked()
            page.keyboard.press("Home")
            assert radios.nth(0).is_checked()
            page.keyboard.press("Shift+Tab")  # reverse direction wraps to last
            assert radios.nth(6).evaluate("e => e === document.activeElement")
            for n in range(5, 0, -1):
                page.keyboard.press("Shift+Tab")
                assert radios.nth(n).evaluate("e => e === document.activeElement")
            page.keyboard.press("Shift+Tab")
            assert delete.evaluate("e => e === document.activeElement")

            delete.focus()
            page.keyboard.press("Tab")  # selected first
            for n in range(1, 7):
                page.keyboard.press("Tab")
                assert radios.nth(n).evaluate("e => e === document.activeElement")
            page.keyboard.press("Tab")
            assert mode.evaluate("e => e === document.activeElement")
            page.keyboard.press("Shift+Tab")
            assert radios.nth(6).evaluate("e => e === document.activeElement")
            assert radios.nth(6).get_attribute("aria-label") == "Select baseline region 7"

            # The issue reported by the user: checked *last* row can still Tab
            # to every other row, then leave without trapping focus.
            radios.nth(6).click()
            delete.focus()
            page.keyboard.press("Tab")
            assert radios.nth(6).evaluate("e => e === document.activeElement")
            for n in range(0, 6):
                page.keyboard.press("Tab")
                assert radios.nth(n).evaluate("e => e === document.activeElement")
            page.keyboard.press("Tab")
            assert mode.evaluate("e => e === document.activeElement")
        finally:
            browser.close()
