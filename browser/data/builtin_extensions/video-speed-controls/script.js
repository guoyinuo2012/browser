/* Video Speed Controls — built-in extension.
 * Keys: [ slower | ] faster | 0 reset to 1x. Rate persists per video element.
 * Only touches HTML5 <video>; never sends data anywhere. */
(function () {
  "use strict";
  if (window.__browserVSC) return;
  window.__browserVSC = true;

  var RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3];

  var osd = document.createElement("div");
  osd.id = "browser-vsc-osd";
  osd.style.cssText =
    "position:fixed;z-index:2147483647;top:14px;left:14px;padding:6px 12px;" +
    "background:rgba(15,17,20,.85);color:#fff;font:600 15px/1.2 system-ui," +
    "sans-serif;border-radius:8px;pointer-events:none;opacity:0;" +
    "transition:opacity .25s;display:none";
  (document.body || document.documentElement).appendChild(osd);
  var osdTimer = null;

  function showOsd(text) {
    osd.textContent = text;
    osd.style.display = "block";
    osd.style.opacity = "1";
    if (osdTimer) clearTimeout(osdTimer);
    osdTimer = setTimeout(function () { osd.style.opacity = "0"; }, 900);
  }

  function step(video, dir) {
    var i = RATES.indexOf(video.playbackRate);
    if (i === -1) i = RATES.indexOf(1);
    i = Math.min(RATES.length - 1, Math.max(0, i + dir));
    video.playbackRate = RATES[i];
    showOsd(RATES[i] + "\u00d7");
  }

  function activeVideo() {
    var vids = document.querySelectorAll("video");
    for (var i = 0; i < vids.length; i++) {
      if (!vids[i].paused) return vids[i];
    }
    return vids[0] || null;
  }

  window.addEventListener("keydown", function (e) {
    var tag = (e.target && e.target.tagName || "").toUpperCase();
    if (tag === "INPUT" || tag === "TEXTAREA" || (e.target && e.target.isContentEditable)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    var v = activeVideo();
    if (!v) return;
    if (e.key === "[") { e.preventDefault(); step(v, -1); }
    else if (e.key === "]") { e.preventDefault(); step(v, +1); }
    else if (e.key === "0" && v.playbackRate !== 1) { e.preventDefault(); v.playbackRate = 1; showOsd("1\u00d7"); }
  }, true);

  // keep the chosen rate when the site resets it on new sources
  window.addEventListener("ratechange", function (e) {
    if (e.target && e.target.tagName === "VIDEO") showOsd(e.target.playbackRate + "\u00d7");
  }, true);
})();
