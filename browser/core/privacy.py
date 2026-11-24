"""Privacy engine for browser.

Components:
  * PrivacyInterceptor      — blocks tracker/ad/fingerprinting requests before
                              the network stack sees them (QWebEngineUrlRequest
                              interceptor, runs in the Chromium IO thread).
  * CookiePolicy            — first-party/third-party cookie control through the
                              profile cookie store filter.
  * FingerprintingScripts   — injected JavaScript that reduces the surface
                              available for fingerprinting.

Counters are exposed for the privacy dashboard. All matching is local.
"""

from __future__ import annotations

import threading
from typing import Dict, Tuple

from ..data import lists


class Counters:
    """Thread-safe block counters (updated from Chromium IO threads)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.trackers = 0
        self.cookies = 0
        self.ads = 0
        self.requests = 0
        self.sites: Dict[str, int] = {}

    def hit(self, kind: str, host: str, first_party: str = "") -> None:
        with self._lock:
            if kind == "tracker":
                self.trackers += 1
            elif kind == "cookie":
                self.cookies += 1
            elif kind == "ad":
                self.ads += 1
            else:
                self.requests += 1
            key = first_party or host
            if key:
                self.sites[key] = self.sites.get(key, 0) + 1

    def snapshot(self) -> Tuple[int, int, int, int, Dict[str, int]]:
        with self._lock:
            return (self.trackers, self.cookies, self.ads, self.requests,
                    dict(self.sites))

    def reset(self) -> None:
        with self._lock:
            self.trackers = self.cookies = self.ads = self.requests = 0
            self.sites.clear()


class PrivacyPolicy:
    """Holds the knobs the interceptor reads on every request.

    Kept separate from Settings so the Chromium IO thread never touches the
    settings store; values are mirrored here on change.
    """

    def __init__(self) -> None:
        self.block_trackers = True
        self.block_third_party_cookies = True
        self.block_all_cookies = False
        self.fingerprinting = "light"       # off | light | strict
        self.block_mixed_content = True
        self.custom_block: frozenset[str] = frozenset()
        self.custom_allow: frozenset[str] = frozenset()   # per-site cookie allows
        self.level = "balanced"
        self.adblock_enabled = True

    @classmethod
    def from_settings(cls, settings) -> "PrivacyPolicy":
        p = cls()
        p.sync(settings)
        return p

    def sync(self, settings) -> None:
        self.block_trackers = bool(settings.get("privacy.block_trackers"))
        self.block_third_party_cookies = bool(settings.get("privacy.block_third_party_cookies"))
        self.block_all_cookies = bool(settings.get("privacy.block_all_cookies"))
        self.fingerprinting = settings.get("privacy.anti_fingerprinting", "light")
        self.block_mixed_content = bool(settings.get("security.block_mixed_content"))
        self.level = settings.get("privacy.level", "balanced")
        self.adblock_enabled = bool(settings.get("adblock.enabled", True))
        self.custom_block = frozenset(
            settings.get("privacy.custom_blocked_domains", []) or [])
        self.custom_allow = frozenset(
            settings.get("privacy.custom_tracker_allow", []) or [])


class PrivacyInterceptor:
    """QWebEngineUrlRequestInterceptor implementation (assigned in app layer).

    The Qt object (created in app.py via QtBridge) calls ``decide`` which
    returns True to block. Keeping the logic pure-Python here makes the whole
    decision path unit-testable without a running engine.
    """

    def __init__(self, counters: Counters, policy: PrivacyPolicy):
        self.counters = counters
        self.policy = policy
        self.adblock = None                 # core.adblock.ListManager
        self._first_party: Dict[int, str] = {}   # frame/request chain hints

    # -- pure decision logic ------------------------------------------------
    def decide(self, url_host: str, url_path: str, url_scheme: str,
               first_party_host: str, resource_type: int = -1,
               navigation: bool = False) -> bool:
        """Return True to block the request."""
        pol = self.policy
        # Never block the internal scheme or navigations to it.
        if url_scheme == "browser":
            return False
        host = url_host.lower()

        # Ad blocking (filter lists like uBlock Origin): first decision so a
        # blocked ad can never be "rescued" by tracker allowlists.
        paused = False
        if self.adblock is not None and first_party_host:
            paused = self.adblock.is_paused(first_party_host)
        if self.adblock is not None and pol.adblock_enabled and first_party_host:
            if not paused:
                from .filterengine import type_for_qt
                rtype = "document" if navigation else type_for_qt(resource_type)
                url_text = (f"{url_scheme}://{url_host.lower()}{url_path}"
                            if url_path.startswith("/") else
                            f"{url_scheme}://{url_host.lower()}/{url_path}")
                if self.adblock.engine.match(url_text, host, first_party_host,
                                             rtype):
                    self.counters.hit("ad", host, first_party_host)
                    return True

        # Mixed content: insecure subresources on a secure page. The page
        # security state is reported by the UI layer via note_page_security.
        if pol.block_mixed_content and first_party_host:
            if url_scheme == "http" and not navigation:
                if self._page_is_secure.get(first_party_host):
                    self.counters.hit("request", host, first_party_host)
                    return True

        if host in pol.custom_block:
            self.counters.hit("request", host, first_party_host)
            return True

        if pol.block_trackers and not paused and host not in pol.custom_allow:
            if lists.is_tracker(host, url_path):
                self.counters.hit("tracker", host, first_party_host)
                return True

        return False

    # -- cookie decision ------------------------------------------------------
    def cookie_allowed(self, cookie_host: str, first_party_host: str,
                       is_third_party: bool) -> bool:
        pol = self.policy
        if pol.block_all_cookies:
            return False
        if first_party_host and first_party_host in pol.custom_allow:
            return True
        if is_third_party and pol.block_third_party_cookies:
            self.counters.hit("cookie", cookie_host, first_party_host)
            return False
        return True

    _page_is_secure: Dict[str, bool] = {}

    def note_page_security(self, host: str, is_https: bool) -> None:
        self._page_is_secure[host] = is_https


# ---------------------------------------------------------------------------
# Injected scripts (anti-fingerprinting)
# ---------------------------------------------------------------------------

_FP_LIGHT_JS = """
(function () {
  if (window.__browserPrivacyHooked) return;
  Object.defineProperty(window, '__browserPrivacyHooked', {value: true});
  // Reduce precision of high-resolution timers.
  try {
    var origNow = performance.now.bind(performance);
    performance.now = function () { return Math.round(origNow() / 100) * 100; };
    var origDateNow = Date.now.bind(Date);
    Date.now = function () { return Math.round(origDateNow() / 100) * 100; };
  } catch (e) {}
  // Limit navigator.hardwareConcurrency granularity.
  try {
    Object.defineProperty(navigator, 'hardwareConcurrency', {get: function () { return 4; }});
    Object.defineProperty(navigator, 'deviceMemory', {get: function () { return 8; }});
  } catch (e) {}
})();
"""

_FP_STRICT_JS = """
(function () {
  if (window.__browserPrivacyHooked) return;
  Object.defineProperty(window, '__browserPrivacyHooked', {value: true});
  // Canvas: add deterministic noise before reads so read-back differs.
  try {
    var origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function () {
      try { this.getContext('2d') && this.getContext('2d').getImageData(0, 0, 1, 1); } catch (e) {}
      return origToDataURL.apply(this, arguments);
    };
    var origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    CanvasRenderingContext2D.prototype.getImageData = function (x, y, w, h) {
      var data = origGetImageData.call(this, x, y, w, h);
      for (var i = 0; i < data.data.length; i += 997) {
        data.data[i] = data.data[i] ^ 1;
      }
      return data;
    };
  } catch (e) {}
  // Audio fingerprinting: perturb frequency data.
  try {
    var origFA = AnalyserNode.prototype.getFloatFrequencyData;
    AnalyserNode.prototype.getFloatFrequencyData = function (arr) {
      origFA.call(this, arr);
      for (var i = 0; i < arr.length; i++) arr[i] += 0.0001 * (i % 7 - 3);
    };
  } catch (e) {}
  // WebRTC: restrict to default (no host candidates leak without consent).
  try {
    var PC = window.RTCPeerConnection;
    if (PC) {
      var P = PC.prototype;
      var origLocal = P.createOffer;
      P.createOffer = function (opts) {
        opts = Object.assign({iceTransportPolicy: 'relay'}, opts || {});
        return origLocal.call(this, opts);
      };
    }
  } catch (e) {}
  // Font/probe resistance: cap plugin and mime enumerations.
  try {
    Object.defineProperty(navigator, 'plugins', {get: function () { return []; }});
  } catch (e) {}
})();
"""

_WEBRTC_DISABLE_JS = """
(function () {
  try {
    var blocked = function () { throw new Error('WebRTC disabled by browser'); };
    window.RTCPeerConnection = blocked;
    window.webkitRTCPeerConnection = blocked;
    window.RTCDataChannel = blocked;
  } catch (e) {}
})();
"""


def fingerprint_script(level: str) -> str:
    """JS that perturbs timing/canvas reads at the given level."""
    if level == "strict":
        return _FP_STRICT_JS
    if level == "light":
        return _FP_LIGHT_JS
    return ""


def webrtc_script(policy_mode: str) -> str:
    """JS that stubs RTCPeerConnection for the given policy."""
    if policy_mode == "disable":
        return _WEBRTC_DISABLE_JS
    return ""


DO_NOT_TRACK_HEADERS = {"DNT": "1", "Sec-GPC": "1"}
