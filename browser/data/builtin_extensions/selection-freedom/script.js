/* Selection Freedom — built-in extension.
 * Neutralizes common right-click/selection blockers (inline handlers and
 * bubbling listeners) and forces user-select. Runs only in the page; does
 * not modify the browser itself. */
(function () {
  "use strict";
  if (window.__browserSF) return;
  window.__browserSF = true;

  // 1. strip inline blocker handlers wherever they appear
  function strip(el) {
    if (!el) return;
    ["oncontextmenu", "onselectstart", "ondragstart"].forEach(function (a) {
      try { el[a] = null; } catch (err) { /* cross-origin doc: ignore */ }
    });
  }
  strip(document);
  strip(document.body);
  strip(document.documentElement);

  // 2. capture-phase stopper: fires before site handlers attached further
  //    down the tree, so blocked events never reach them.
  window.addEventListener("contextmenu", function (e) { e.stopPropagation(); }, true);
  window.addEventListener("selectstart", function (e) { e.stopPropagation(); }, true);
  window.addEventListener("dragstart", function (e) { e.stopPropagation(); }, true);
  window.addEventListener("mousedown", function (e) {
    if (e.button === 2) e.stopPropagation();
  }, true);

  // 3. CSS force-enable (document- and element-level user-select rules)
  var s = document.createElement("style");
  s.id = "browser-selection-freedom";
  s.textContent =
    "html,body,*{-webkit-user-select:auto !important;user-select:auto !important;" +
    "-webkit-touch-callout:default !important}";
  (document.head || document.documentElement).appendChild(s);
})();
