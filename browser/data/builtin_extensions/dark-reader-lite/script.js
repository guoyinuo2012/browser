/* Dark Reader Lite — built-in extension.
 * Inverts the page, then re-inverts media and common embeds so images and
 * videos keep their true colors. Enabled per site from Tools → Extensions. */
(function () {
  "use strict";
  if (window.__browserDark) return;
  window.__browserDark = true;
  var s = document.createElement("style");
  s.id = "browser-dark-style";
  s.textContent =
    "html{-webkit-filter:invert(1) hue-rotate(180deg);filter:invert(1) hue-rotate(180deg);" +
    "background:#0e0f11 !important}" +
    "img,video,picture,canvas,svg,iframe,embed,object,[style*='background-image']{" +
    "-webkit-filter:invert(1) hue-rotate(180deg);filter:invert(1) hue-rotate(180deg)}" +
    "::selection{background:#666 !important;color:#fff !important}";
  (document.head || document.documentElement).appendChild(s);
})();
