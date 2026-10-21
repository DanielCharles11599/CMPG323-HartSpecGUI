/* FR-22: document-local appearance and keyboard access for the embedded Dash editor.
 * Dash 2.16's dcc.Dropdown is the controlled form input; html.Select has no
 * value prop and cannot participate in the region-selection callbacks.
 * Intercept Tab only at this dropdown, before React Select consumes it.
 * Arrow keys and Space operate the real Dash DataTable radios; Enter and Escape
 * remain native. Tab and Shift+Tab move across rows and out of the editor.
 */
(function () {
  "use strict";
  var lastBackground = "";
  function synchronize() {
    var root = document.getElementById("root");
    if (!root) return;
    var css = window.getComputedStyle(root);
    var size = css.getPropertyValue("--hs-root-size").trim();
    var background = css.getPropertyValue("--hs-bg-primary").trim();
    if (size && document.documentElement.style.fontSize !== size) {
      document.documentElement.style.fontSize = size;
    }
    if (background && background !== lastBackground) {
      document.body.style.backgroundColor = background;
      lastBackground = background;
    }
    var names = {
      "region-choice": "Region to edit",
      "manual-order-lcp": "LCP polynomial order",
      "manual-order-rcp": "RCP polynomial order"
    };
    Object.keys(names).forEach(function (id) {
      var host = document.getElementById(id);
      var input = host && host.querySelector("input");
      if (input && input.getAttribute("aria-label") !== names[id]) {
        input.setAttribute("aria-label", names[id]);
      }
    });
  }

  function regionTabNavigation(event) {
    if (event.key !== "Tab") return;
    var target = event.target;
    var host = target && target.closest && target.closest("#region-choice");
    if (!host) return;

    var destination = document.getElementById("region-start");
    if (event.shiftKey) {
      var candidates = document.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
        'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      destination = null;
      Array.prototype.forEach.call(candidates, function (node) {
        // Select the last visible, enabled focus target before the dropdown.
        if (node !== host && !host.contains(node) && node.getClientRects().length &&
            (node.compareDocumentPosition(host) & Node.DOCUMENT_POSITION_FOLLOWING)) {
          destination = node;
        }
      });
      if (!destination) destination = document.querySelector(".hs-skip-link");
    }
    if (!destination) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    destination.focus();
  }

  /* Dash DataTable does not expose the region radio inputs as a native
   * named radio group, so ArrowUp/ArrowDown can appear to do nothing.
   * Intercept keys at the table radio only. Click the real Dash input rather
   * than assigning checked, so the existing selected_rows -> dropdown
   * callback runs and the selected editing bounds update normally.
   *
   * Tabs visit ALL rows once, starting at the selected row, then exit to
   * polynomial controls. Arrow keys wrap, like a normal radio group.
   */
  function tableRadios() {
    var table = document.getElementById("block-table");
    if (!table) return [];
    return Array.prototype.filter.call(
      table.querySelectorAll('input[type="radio"]:not(:disabled)'),
      function (radio) { return !!radio.getClientRects().length; }
    );
  }

  function selectedRowRadio() {
    var radios = tableRadios();
    return radios.find(function (radio) { return radio.checked; }) || radios[0] || null;
  }

  function polynomialModeRadio() {
    var group = document.getElementById("selection-mode");
    if (!group) return null;
    return group.querySelector('input[type="radio"]:checked:not(:disabled)') ||
      group.querySelector('input[type="radio"]:not(:disabled)');
  }

  function focusRadioAt(index, activate) {
    var radios = tableRadios();
    var radio = radios[index];
    if (!radio) return;
    if (activate && !radio.checked) radio.click();
    // A Dash selection can re-render the input. Re-find it after the event.
    radio = tableRadios()[index] || radio;
    radio.focus();
    if (activate) {
      window.requestAnimationFrame(function () {
        var replacement = tableRadios()[index];
        // Do not steal focus back if the user has already pressed Tab.
        var active = document.activeElement;
        if (replacement && (active === radio || active === document.body)) replacement.focus();
      });
    }
  }

  function labelTableRadios() {
    tableRadios().forEach(function (radio, index) {
      if (!radio.hasAttribute("aria-label")) {
        radio.setAttribute("aria-label", "Select baseline region " + (index + 1));
      }
      if (!radio.hasAttribute("title")) {
        radio.setAttribute("title", "Up/Down: select region; Tab: next row; Space: select");
      }
    });
  }

  // Tracks one Tab traversal, so even when the last row is selected a user
  // can Tab to every other region before leaving the table. Not an infinite trap.
  var visitedRadioIndices = null;
  var radioTabDirection = null;

  function nextRadioTabStop(radios, index, backwards) {
    var direction = backwards ? -1 : 1;
    if (!visitedRadioIndices || radioTabDirection !== direction) {
      visitedRadioIndices = new Set([index]);
      radioTabDirection = direction;
    }
    var nextIndex = (index + direction + radios.length) % radios.length;
    if (visitedRadioIndices.has(nextIndex)) {
      visitedRadioIndices = null;
      radioTabDirection = null;
      return backwards ? document.getElementById("delete-region") :
        (polynomialModeRadio() || document.getElementById("fit-polynomial"));
    }
    visitedRadioIndices.add(nextIndex);
    return radios[nextIndex];
  }

  function editorTableNavigation(event) {
    var target = event.target;
    if (!target || !target.closest) return;
    var key = event.key;
    if (key !== "Tab" && key !== "ArrowUp" && key !== "ArrowDown" &&
        key !== "ArrowLeft" && key !== "ArrowRight" && key !== "Home" &&
        key !== "End" && key !== " " && key !== "Spacebar") return;

    var radios = tableRadios();
    var index = radios.indexOf(target);
    var destination = null;

    if (key === "Tab") {
      if (target.id === "delete-region" && !event.shiftKey) {
        destination = selectedRowRadio() || polynomialModeRadio() || document.getElementById("fit-polynomial");
        var entryIndex = radios.indexOf(destination);
        visitedRadioIndices = entryIndex >= 0 ? new Set([entryIndex]) : null;
        radioTabDirection = entryIndex >= 0 ? 1 : null;
      } else if (index !== -1) {
        destination = nextRadioTabStop(radios, index, event.shiftKey);
      } else if (event.shiftKey && target.matches('input[type="radio"]') &&
                 target.closest("#selection-mode")) {
        destination = radios[radios.length - 1] || document.getElementById("delete-region");
        var lastIndex = radios.indexOf(destination);
        visitedRadioIndices = lastIndex >= 0 ? new Set([lastIndex]) : null;
        radioTabDirection = lastIndex >= 0 ? -1 : null;
      }
      if (!destination || !destination.getClientRects().length) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      destination.focus();
      return;
    }

    if (index < 0) return; // Never override polynomial-mode arrows or other inputs.
    var nextIndex = index;
    if (key === "ArrowUp" || key === "ArrowLeft") {
      nextIndex = (index + radios.length - 1) % radios.length;
    } else if (key === "ArrowDown" || key === "ArrowRight") {
      nextIndex = (index + 1) % radios.length;
    } else if (key === "Home") {
      nextIndex = 0;
    } else if (key === "End") {
      nextIndex = radios.length - 1;
    } else if (key !== " " && key !== "Spacebar") {
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    visitedRadioIndices = null;
    radioTabDirection = null;
    focusRadioAt(nextIndex, true);
  }

  var scheduled = false;
  var observer = new MutationObserver(function () {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(function () {
      scheduled = false;
      synchronize();
      labelTableRadios();
    });
  });
  function start() {
    observer.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ["style"]});
    // Capture before React Select's bubble listener; it otherwise treats Tab as
    // an option-selection key and can keep focus inside the Streamlit iframe.
    document.addEventListener("keydown", regionTabNavigation, true);
    document.addEventListener("keydown", editorTableNavigation, true);
    synchronize();
    labelTableRadios();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
