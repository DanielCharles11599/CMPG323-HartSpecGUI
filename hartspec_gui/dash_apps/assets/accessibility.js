/* FR-22: document-local font/background propagation and accessible names for
 * Dash 2.16's React Select input elements. No parent DOM access, no shortcuts,
 * no remote assets, no keyboard-event interception and no focus trapping. */
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
  var scheduled = false;
  var observer = new MutationObserver(function () {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(function () {
      scheduled = false;
      synchronize();
    });
  });
  function start() {
    observer.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ["style"]});
    synchronize();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
