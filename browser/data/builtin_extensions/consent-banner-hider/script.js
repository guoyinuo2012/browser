/* Consent Banner Hider — built-in extension.
 * Hide-only: removes known consent/cookie banner roots and the dark
 * backdrops they put up, and un-sticks scroll locks they set.
 * It never clicks, never "accepts for you", and sends nothing anywhere. */
(function () {
  "use strict";
  if (window.__browserCBH) return;
  window.__browserCBH = true;

  var SELECTORS = [
    /* OneTrust */
    "#onetrust-banner-sdk", "#onetrust-consent-sdk", ".onetrust-pc-dark-filter",
    "#onetrust-portal-btn", ".ot-bnr-save-banner",
    /* Cookiebot */
    "#CybotCookiebotDialog", "#CybotCookiebotDialogBodyUnderlay",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    /* Didomi */
    "#didomi-host", "div[id^='didomi-popup']",
    /* Sourcepoint / others */
    "div[id^='sp_message_container']", ".sp_message_container",
    "#truste-consent-track", ".truste-box-overlay",
    /* Common generic patterns */
    "#cookie-banner", "#cookie-consent", "#cookieconsent", "#cookie-box",
    "#gdpr-banner", "#gdpr-consent", "#consent-banner", "#cmp-banner",
    ".cookie-banner", ".cookie-consent", ".consent-banner", ".consent-overlay",
    ".gdpr-banner", ".gdpr-consent", ".cc-banner", ".cc-window",
    "[class*='cookie-banner']", "[id*='cookie-banner']",
    "[class*='consent-banner']", "[class*='CookieBanner']",
    /* Newsletter / interstitial popups */
    "[class*='newsletter-popup']", "[class*='newsletter-modal']",
    "[class*='signup-modal'][aria-modal='true']"
  ].join(",");

  function sweep() {
    try {
      var found = document.querySelectorAll(SELECTORS);
      for (var i = 0; i < found.length; i++) {
        var el = found[i];
        if (el.style.display !== "none") el.style.setProperty("display", "none", "important");
      }
      // consent SDKs lock scrolling with inline styles on html/body
      if (document.documentElement) {
        document.documentElement.style.setProperty("overflow-y", "auto", "important");
        document.documentElement.style.removeProperty("position");
      }
      if (document.body) {
        document.body.style.setProperty("overflow-y", "auto", "important");
        if (document.body.style.position === "fixed") document.body.style.position = "";
      }
    } catch (err) { /* keep sweeping quietly */ }
  }

  var run = (function () { var t = null; return function () { if (t) return; t = setTimeout(function () { t = null; sweep(); }, 120); }; })();

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", sweep);
  sweep();
  new MutationObserver(run).observe(document.documentElement, { childList: true, subtree: true });
})();
