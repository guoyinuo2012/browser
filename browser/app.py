"""AppState — shared application state for browser.

Creates and wires the engine profiles (default + private), managers, the
browser:// scheme, interceptors, cookie filters, script injection and
windows. Private profiles are off-the-record: nothing they touch is
persisted, and they are wiped when the last private window closes.
"""

from __future__ import annotations

import os
from typing import List, Optional

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtWidgets import QApplication

from PyQt6.QtWebEngineCore import (
    QWebEngineProfile, QWebEngineUrlRequestInterceptor,
    QWebEngineUrlScheme, QWebEngineCookieStore, QWebEngineScript)

from . import paths, constants
from .settings import Settings
from .storage import Store
from .core.privacy import Counters, PrivacyPolicy, PrivacyInterceptor
from .core.security import SafeBrowsing
from .core.vault import Vault
from .core.extensions import ExtensionManager
from .core.permissions import PermissionManager
from .core.downloads import DownloadManager
from .pages.handler import SchemeHandler, Services
from .data import lists


def configure_engine() -> None:
    """Engine configuration that MUST happen before QApplication exists."""
    scheme = QWebEngineUrlScheme(constants.SCHEME)
    scheme.setSyntax(QWebEngineUrlScheme.Syntax.Host)
    scheme.setFlags(QWebEngineUrlScheme.Flag.SecureScheme)
    QWebEngineUrlScheme.registerScheme(scheme)

    flags = []
    proxy = os.environ.get("BROWSER_PROXY", "")
    if not proxy:
        # Honor the user's proxy settings (manual mode) at startup; changing
        # them requires a restart, like in other Chromium browsers.
        try:
            import json as _json
            cfg = paths.config_file()
            if cfg is not None and cfg.exists():
                vals = _json.loads(cfg.read_text(encoding="utf-8"))
                if vals.get("advanced.proxy_mode") == "manual":
                    proxy = vals.get("advanced.proxy_server") or ""
        except (OSError, ValueError):
            pass    # unreadable settings simply mean no proxy flag
    if proxy:
        flags.append(f"--proxy-server={proxy}")
    # Tor mode overrides any manual proxy: pin everything to the SOCKS proxy
    # and forbid local DNS resolution (no DNS leak).
    try:
        from .core.tor import engine_flags_for
        flags.extend(engine_flags_for(Settings()))
    except Exception:
        pass    # Tor flags are best-effort at engine-config time
    if flags:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(
            flags + [os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")]).strip()


class _QtRequestInterceptor(QWebEngineUrlRequestInterceptor):
    """Chromium IO-thread interceptor delegating to PrivacyInterceptor."""

    def __init__(self, logic: PrivacyInterceptor, parent=None):
        super().__init__(parent)
        self.logic = logic

    def interceptRequest(self, info) -> None:  # noqa: N802
        url = info.requestUrl()
        host = url.host()
        first_party = info.firstPartyUrl().host()
        blocked = self.logic.decide(
            host, url.path(), url.scheme(), first_party,
            resource_type=info.resourceType(),
            navigation=info.resourceType() in (
                info.ResourceType.ResourceTypeMainFrame,
                info.ResourceType.ResourceTypeXhr,
                info.ResourceType.ResourceTypeDocument,
                info.ResourceType.ResourceTypeSubFrame),
        )
        if blocked:
            info.block(True)


class AppState(QObject):
    """Wires everything; owned by main()."""

    counters_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        paths.ensure_dirs()

        self.settings = Settings()
        self.store = Store(paths.database_file())
        self.counters = Counters()
        self.policy = PrivacyPolicy.from_settings(self.settings)
        self.logic = PrivacyInterceptor(self.counters, self.policy)

        # restore last counters (privacy dashboard continuity is local only)
        saved = self.settings.get("internal.stats", {})
        self.counters.trackers = int(saved.get("trackers_blocked", 0))
        self.counters.cookies = int(saved.get("cookies_blocked", 0))
        self.counters.ads = int(saved.get("ads_blocked", 0))
        self.counters.requests = int(saved.get("requests_blocked", 0))
        self.counters.sites = dict(self.settings.get("internal.stats_by_site", {}))

        self.vault = Vault(paths.vault_file(), paths.data_dir() / "vault.key",
                           auto_lock_minutes=int(self.settings.get(
                               "passwords.auto_lock_minutes", 30)))
        self.extensions = ExtensionManager(self.settings, paths.data_dir())
        new_ids = self.extensions.sync_builtins()
        self._allow_builtins_private(new_ids)
        self.permissions = PermissionManager(self.settings)
        from .core.adblock import ListManager
        self.adblock = ListManager(self.settings, paths.data_dir() / "adblock",
                                   lists.domain_of)
        self.logic.adblock = self.adblock
        self.adblock.rebuild()
        from .core.tor import TorManager
        self.tor = TorManager(self.settings, paths.data_dir())
        self.safe_browsing = SafeBrowsing(
            enabled=bool(self.settings.get("security.safe_browsing", True)),
            consent=bool(self.settings.get("security.safe_browsing_consent")),
            api_key=self.settings.get("security.safe_browsing_api_key", ""))

        # ---- engine profiles -------------------------------------------------
        self.profile = QWebEngineProfile("browser-default", None)
        self._setup_profile(self.profile, persistent=True)
        self.private_profile = self._create_private_profile()

        # ---- downloads ---------------------------------------------------------
        self.downloader = DownloadManager(self.settings, self.store)
        self.profile.downloadRequested.connect(self.downloader.handle_request)
        self.private_profile.downloadRequested.connect(self.downloader.handle_request)

        # ---- services / scheme -------------------------------------------------
        self.services = Services()
        self._wire_services()
        self.scheme_handler = SchemeHandler(self.services)
        self.profile.installUrlSchemeHandler(constants.SCHEME, self.scheme_handler)
        self.private_profile.installUrlSchemeHandler(constants.SCHEME, self.scheme_handler)

        # ---- settings reactions ---------------------------------------------------
        self.settings.observe(self._on_setting)

        self._windows: List = []

    # ------------------------------------------------------------------ #
    def _setup_profile(self, profile: QWebEngineProfile, persistent: bool) -> None:
        profile.setUrlRequestInterceptor(_QtRequestInterceptor(self.logic, profile))
        if persistent:
            profile.setPersistentStoragePath(str(paths.default_profile_dir()))
            profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        else:
            profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        cookie_store = profile.cookieStore()
        cookie_store.setCookieFilter(self._cookie_filter)
        s = profile.settings()
        s.setAttribute(s.WebAttribute.JavascriptEnabled,
                       bool(self.settings.get("advanced.javascript_enabled", True)))
        s.setAttribute(s.WebAttribute.AutoLoadImages,
                       bool(self.settings.get("advanced.images_enabled", True)))
        s.setAttribute(s.WebAttribute.DnsPrefetchEnabled, False)   # privacy: no prefetch
        s.setAttribute(s.WebAttribute.HyperlinkAuditingEnabled, False)  # no <ping>
        s.setAttribute(s.WebAttribute.ScrollAnimatorEnabled,
                       not bool(self.settings.get("appearance.reduced_motion")))
        s.setAttribute(s.WebAttribute.PdfViewerEnabled, True)
        try:
            s.setAttribute(s.WebAttribute.ReadingFromCanvasEnabled,
                           self.policy.fingerprinting != "strict")
        except Exception:
            pass    # optional hardening knob; absent on some Qt builds
        if persistent and self.settings.get("advanced.spellcheck", True):
            profile.setSpellCheckEnabled(True)
            try:
                profile.setSpellCheckLanguages(
                    [self.settings.get("advanced.spellcheck_languages", "en-US")])
            except Exception:
                pass    # dictionary missing: cosmetic only
        # DNT / GPC request headers: added via a global script using fetch/XHR
        # wrappers is unreliable; WebEngine exposes them at navigation level
        # through Chromium flags. We send them via interceptor on every request.
        profile.scripts().insert(self._dnt_script())

    def _dnt_script(self) -> QWebEngineScript:
        script = QWebEngineScript()
        script.setName("browser-dnt-gpc")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(True)
        # navigator-level opt-out signals honored by cooperative sites
        script.setSourceCode(
            "Object.defineProperty(navigator,'doNotTrack',{get:()=>'%s'});"
            "Object.defineProperty(navigator,'globalPrivacyControl',{get:()=>%s});"
            % ("1" if self.settings.get("privacy.do_not_track", True) else "unspecified",
               "true" if self.settings.get("privacy.global_privacy_control", True) else "false"))
        return script

    def _cookie_filter(self, request) -> bool:
        """QWebEngineCookieStore filter: returns True to allow the cookie.

        All cookies go through the policy (including first-party ones) so
        that "block all cookies" and per-site rules are enforced.
        """
        first_party = request.firstPartyUrl().host() if request.firstPartyUrl().isValid() else ""
        origin = request.origin()
        host = origin.host() if origin.isValid() else ""
        return self.logic.cookie_allowed(host, first_party,
                                         is_third_party=request.thirdParty())

    def _create_private_profile(self) -> QWebEngineProfile:
        prof = QWebEngineProfile(None)   # no storage name = off-the-record
        self._setup_profile(prof, persistent=False)
        return prof

    def destroy_private_profile(self, profile) -> None:
        try:
            profile.cookieStore().deleteAllCookies()
            profile.clearHttpCache()
            profile.setParent(None)
            profile.deleteLater()
        except RuntimeError:
            pass
        self.private_profile = self._create_private_profile()

    # ------------------------------------------------------------------ #
    def _wire_services(self) -> None:
        s = self.services
        s.settings = self.settings
        s.store = self.store
        s.vault = self.vault
        s.counters = self.counters
        s.policy = self.policy
        s.extensions = self.extensions
        s.permissions = self.permissions
        s.adblock = self.adblock
        s.safe_browsing = self.safe_browsing
        s.downloader = self.downloader
        s.network = self.nam          # shared QNetworkAccessManager for list fetches
        s.interceptor_logic = self.logic   # mixed-content page security reports
        s.tor = self.tor

        def engine_name() -> str:
            return self.settings.get("search.default_engine", "DuckDuckGo")

        def engine_url() -> str:
            name = engine_name()
            from .core.search import BUILTIN_ENGINES
            for ce in self.settings.get("search.custom_engines", []):
                if ce.get("name") == name:
                    return ce["url"]
            eng = BUILTIN_ENGINES.get(name, BUILTIN_ENGINES["DuckDuckGo"])
            return eng.search_url

        s.engine_name = engine_name
        s.engine_search_url = engine_url

    def _on_setting(self, key, _value) -> None:
        if key.startswith("privacy.") or key.startswith("adblock."):
            self.policy.sync(self.settings)
        elif key.startswith("security."):
            self.safe_browsing.enabled = bool(self.settings.get("security.safe_browsing", True))
            self.safe_browsing.consent = bool(self.settings.get("security.safe_browsing_consent"))
        elif key == "passwords.auto_lock_minutes":
            self.vault.change_auto_lock(int(_value or 0))

    def persist_counters(self) -> None:
        t, c, ads, r, sites = self.counters.snapshot()
        self.settings.set("internal.stats", {"trackers_blocked": t, "cookies_blocked": c,
                                             "ads_blocked": ads,
                                             "requests_blocked": r}, save=False)
        self.settings.set("internal.stats_by_site", sites, save=False)
        self.settings.save()

    # ------------------------------------------------------------------ #
    def windows(self) -> List:
        return list(self._windows)

    def open_window(self, private: bool = False, urls: Optional[List[str]] = None):
        from .ui.browser_window import BrowserWindow
        w = BrowserWindow(self, private=private, urls=urls)
        self._windows.append(w)
        w.destroyed.connect(lambda *_: self._forget_window(w))
        self.downloader.warn_requested.connect(w._on_download_warning)
        self.counters_changed.connect(w.refresh_shield)
        w.refresh_shield()
        w.show()
        return w

    def _forget_window(self, w) -> None:
        if w in self._windows:
            self._windows.remove(w)

    def private_window_count(self) -> int:
        return sum(1 for w in self._windows if w.private)

    def _allow_builtins_private(self, new_ids: List[str]) -> None:
        """Newly installed built-in extensions run in private windows by
        default (user can revoke per extension on browser://extensions;
        neither sync nor restart will re-add)."""
        if not new_ids:
            return
        allowed = list(self.settings.get("extensions.allow_in_private", []))
        changed = False
        for ext_id in new_ids:
            if ext_id not in allowed:
                allowed.append(ext_id)
                changed = True
        if changed:
            self.settings.set("extensions.allow_in_private", allowed)

    def nam(self):
        """Shared QNetworkAccessManager (list updates, omnibox suggestions)."""
        if not hasattr(self, "_nam"):
            from PyQt6.QtNetwork import QNetworkAccessManager
            self._nam = QNetworkAccessManager(self)
        return self._nam

    # ------------------------------------------------------------------ #
    def check_updates(self, parent=None) -> None:
        """Runs a signed-manifest update check if a feed is configured."""
        from PyQt6.QtWidgets import QMessageBox, QApplication
        from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest
        from .core import updates
        updates.set_current_version(constants.APP_VERSION)
        url = self.settings.get("updates.manifest_url", "")
        if not url:
            QMessageBox.information(
                parent, "browser",
                f"browser {constants.APP_VERSION}\n\n"
                "No update feed is configured. browser never phones home: "
                "add a signed update feed in Settings → Advanced to enable "
                "update checks. Updates are only applied after signature "
                "verification, and downgrades are refused.")
            return
        if not updates.feed_trusted(paths.data_dir()):
            QMessageBox.information(
                parent, "browser",
                "This update feed was never approved. The first check will ask "
                "you to trust its signing key.")
        nam = QNetworkAccessManager(self)   # parent to self: survive reply
        reply = nam.get(QNetworkRequest(QUrl(url)))

        def done() -> None:
            data = bytes(reply.readAll())
            reply.deleteLater()
            manifest, err = updates.parse_manifest(data)
            if manifest is None:
                QMessageBox.warning(parent, "browser", f"Update check failed: {err}")
                return
            from .core.updates import _load_trust
            trust = _load_trust(paths.data_dir())
            ok, msg = updates.verify_manifest(manifest, trust)
            if not ok:
                QMessageBox.warning(parent, "browser", f"Update rejected: {msg}")
                return
            if not trust.get("pubkey"):
                updates.approve_feed(paths.data_dir(), manifest["pubkey"])
            QMessageBox.information(
                parent, "browser",
                f"Update {manifest['version']} is available and its signature "
                f"verified.\n\nDownload: {manifest['url']}\n\n"
                "browser verifies the package hash before you install it. "
                "It will not install anything automatically.")

        reply.finished.connect(done)
